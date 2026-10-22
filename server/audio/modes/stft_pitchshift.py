"""stft_pitchshift: zero-padded STFT phase vocoder (stftpitchshift encode/
decode) with Lanczos-3 resampling, cepstral formant preservation and V/UV
blending, driven by the shared soft-retune trajectory (pYIN F0)."""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import (
    _apply_rms_envelope,
    _improved_lifter,
    _lanczos3_resample,
    _zp_istft,
    _zp_stft,
)
from server.audio.modes._retune import retune_log2
from server.utils.note_utils import note_name_to_freq

NAME = "stft_pitchshift"
USES_WORLD_CACHE = False


def autotune_stft_pitchshift(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    preserve_formants: bool = True,
    formant_shift_cents: int = 0,
    window_size: int = 1024,
    fft_size: int = 4096,
    hop_size: int = 256,
) -> np.ndarray:
    """Per-frame STFT phase vocoder pitch correction (v12).

    v12 improvements over v11:
      - Zero-padded FFT: 1024-sample Hann window, 4096-point FFT gives 4x
        frequency oversampling so harmonics span 8-16 bins and interpolation
        preserves valley depth.
      - Lanczos-3 resampler (6-tap windowed sinc) instead of 2-tap linear.
      - Improved cepstral formant preservation: magnitude floor, Hamming-
        windowed lifter, adaptive quefrency based on per-frame F0.
      - Voiced/unvoiced transition blending using pYIN voicing probability
        with sigmoid crossfade (eliminates clicks at word boundaries).
    """
    from stftpitchshift.vocoder import encode, decode
    from server.audio.pitch_detector import detect_pitch

    audio_arr = np.asarray(audio, dtype=np.float64)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono 1D array")
    if len(audio_arr) < int(0.1 * sr):
        raise ValueError("Audio is too short (min 0.1 s)")
    if sr <= 0:
        raise ValueError("sr must be positive")

    orig_len    = len(audio_arr)
    target_freq = float(note_name_to_freq(target_note))
    amount_f    = float(np.clip(amount, 0.0, 1.0))
    vib_f       = float(np.clip(preserve_vibrato, 0.0, 1.0))

    # ── pYIN F0 detection ─────────────────────────────────────────────────
    det           = detect_pitch(audio_arr.astype(np.float32), sr=sr, fast=False)
    f0_array      = np.asarray(det["f0_array"], dtype=np.float64)
    f0_times      = np.asarray(det["times"],    dtype=np.float64)
    voiced_probs  = np.asarray(det.get("voiced_probs",
                               np.zeros_like(f0_array)), dtype=np.float64)

    voiced_mask = np.isfinite(f0_array) & (f0_array > 50.0)
    if np.sum(voiced_mask) < 2:
        return audio_arr

    # ── Zero-padded STFT ──────────────────────────────────────────────────
    audio_f32 = audio_arr.astype(np.float32)
    frames = _zp_stft(audio_f32, window_size, fft_size, hop_size)
    n_frames, n_bins = frames.shape

    stft_times = (np.arange(n_frames) * hop_size + window_size / 2.0) / sr

    # ── Interpolate F0 + voicing probability onto STFT frame grid ─────────
    f0_voiced_vals = f0_array[voiced_mask]
    f0_interp = np.interp(
        stft_times,
        f0_times[voiced_mask], f0_voiced_vals,
        left=float(f0_voiced_vals[0]),
        right=float(f0_voiced_vals[-1]),
    )

    # Voicing confidence per STFT frame (Fix 4)
    vp_interp = np.interp(stft_times, f0_times, voiced_probs,
                           left=0.0, right=0.0)

    # Smooth voicing probability with exponential filter (~10 ms)
    vp_alpha = max(0.0, min(0.999, float(np.exp(
        -(hop_size / sr) / max(1e-6, 0.010)))))
    vp_smooth = vp_interp.copy()
    for i in range(1, len(vp_smooth)):
        vp_smooth[i] = vp_alpha * vp_smooth[i - 1] + (1.0 - vp_alpha) * vp_smooth[i]
    # Sigmoid gate: sharp transition around 0.5
    blend = 1.0 / (1.0 + np.exp(-15.0 * (vp_smooth - 0.5)))  # (n_frames,)

    # ── Per-frame ratio computation (mirrors autotune_soft_to_note) ───────
    hop_s    = hop_size / sr
    target_x = np.log2(max(1e-6, target_freq))
    x        = np.log2(np.maximum(f0_interp, 1e-6))

    new_x           = retune_log2(x, target_x, amount_f, vib_f, hop_s, retune_speed_ms)
    ratio_per_frame = np.power(2.0, new_x - x)

    # ── Encode: complex STFT -> (magnitude, instantaneous frequency) ──────
    frames = encode(frames, fft_size, hop_size, sr)

    # ── Improved cepstral formant preservation (Fix 3) ────────────────────
    envelopes: np.ndarray | None = None
    env_bad:   np.ndarray | None = None

    if preserve_formants:
        envelopes = _improved_lifter(frames.real, f0_interp, sr)
        env_bad = np.isinf(envelopes) | np.isnan(envelopes) | (
            np.abs(envelopes) < np.finfo(np.float32).tiny)
        frames.real /= np.where(env_bad, 1.0, envelopes)
        frames.real[env_bad] = 0.0

        if formant_shift_cents != 0:
            distortion = 2.0 ** (float(formant_shift_cents) / 1200.0)
            for i in range(n_frames):
                env_frame = envelopes[i].copy()
                env_frame[env_bad[i]] = 0.0
                envelopes[i] = _lanczos3_resample(env_frame, distortion)
            env_bad = np.isinf(envelopes) | np.isnan(envelopes) | (
                np.abs(envelopes) < np.finfo(np.float32).tiny)

    # ── Per-frame pitch shift (Lanczos-3 resampling, V/UV blending) ───────
    nyquist    = sr / 2.0
    mags_orig  = frames.real.copy()     # keep originals for V/UV blend
    freqs_orig = frames.imag.copy()
    mags_out   = mags_orig.copy()
    freqs_out  = freqs_orig.copy()

    for i in range(n_frames):
        b = blend[i]
        if b < 1e-4:
            continue                     # fully unvoiced — passthrough

        ratio = ratio_per_frame[i] if i < len(ratio_per_frame) else 1.0
        if not np.isfinite(ratio) or ratio <= 0.0 or abs(ratio - 1.0) < 1e-7:
            continue

        mag  = frames[i].real
        freq = frames[i].imag

        mag_s  = _lanczos3_resample(mag,  ratio)
        freq_s = _lanczos3_resample(freq, ratio) * ratio

        # Clamp (not zero) bins with invalid shifted frequency
        invalid = (freq_s <= 0.0) | (freq_s >= nyquist)
        mag_s[invalid]  = 0.0

        # V/UV blend (Fix 4): smooth crossfade instead of binary gate
        mags_out[i]  = b * mag_s  + (1.0 - b) * mags_orig[i]
        freqs_out[i] = b * freq_s + (1.0 - b) * freqs_orig[i]

    # ── Restore formant envelope ──────────────────────────────────────────
    if envelopes is not None and env_bad is not None:
        mags_out *= np.where(env_bad, 0.0, envelopes)

    frames_out = mags_out + 1j * freqs_out

    # ── Decode + ISTFT ────────────────────────────────────────────────────
    frames_out = decode(frames_out, fft_size, hop_size, sr)
    output     = _zp_istft(frames_out, window_size, fft_size, hop_size)

    # ── RMS correction ────────────────────────────────────────────────────
    output = _apply_rms_envelope(audio_arr, output,
                                 frame_len=2048, hop=512,
                                 gain_min=0.0, gain_max=8.0, smooth_sigma=2.0)

    if len(output) >= orig_len:
        output = output[:orig_len]
    else:
        output = np.pad(output, (0, orig_len - len(output)))

    return output


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None) -> np.ndarray:
    return autotune_stft_pitchshift(
        audio,
        int(sr),
        str(settings["target_note"]),
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        preserve_formants=bool(settings.get("preserve_formants", True)),
        formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
    )
