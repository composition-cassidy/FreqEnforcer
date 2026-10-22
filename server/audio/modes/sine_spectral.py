"""sine_spectral: cepstral spectral envelope x phase-vocoder resampled
excitation, with the shared soft-retune trajectory (pYIN F0)."""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import _apply_hf_rolloff, _apply_rms_envelope
from server.audio.modes._retune import retune_log2
from server.utils.note_utils import note_name_to_freq

NAME = "sine_spectral"
USES_WORLD_CACHE = False


def autotune_sine_spectral(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    preserve_formants: bool = True,
    formant_shift_cents: int = 0,
    fft_size: int = 2048,
    hop_size: int = 256,
    max_sines: int = 80,
    threshold_db: float = -80.0,
) -> np.ndarray:
    """
    Spectral Envelope + Excitation pitch correction.

    For each voiced STFT frame the algorithm is:
      1. Estimate the spectral envelope E[k] via cepstral smoothing of the
         original frame magnitude.  E[k] is a smooth function that covers
         EVERY FFT bin — it represents formants, not individual harmonics.
      2. Generate a Hann-windowed harmonic excitation signal: a sum of
         unit-amplitude cosines at TARGET_F0 * 1, 2, 3 ... up to Nyquist,
         with per-harmonic phase accumulators for continuity across frames.
      3. Take the rfft of the excitation → Exc[k].
      4. Output spectrum = E[k] * exp(j * angle(Exc[k])).
         * E[k] gives FULL spectral density — smooth, non-zero at every bin,
           shaped like the vocal tract formants.  No hollow gaps.
         * angle(Exc[k]) encodes the target pitch via harmonic phase
           structure; the Hann window causes sinc-like spectral spreading
           so the phase is well-defined between harmonics too.
      5. ISTFT overlap-add over all frames.
      6. RMS envelope correction to match the original dynamics.

    Unvoiced frames (no pYIN detection within ±1.5 hops) pass through
    unmodified directly in the STFT domain.
    """
    from server.audio.pitch_detector import detect_pitch
    from server.audio.sinusoidal import estimate_spectral_envelope
    from scipy.signal import stft, istft

    # ── validate ──────────────────────────────────────────────────────────
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio, dtype=np.float64)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")
    if audio_arr.shape[0] < int(0.1 * sr):
        raise ValueError("Audio is too short for sinusoidal processing (min 0.1 s)")

    orig_len    = len(audio_arr)
    target_freq = float(note_name_to_freq(target_note))
    amount_f    = float(np.clip(amount, 0.0, 1.0))
    vib_f       = float(np.clip(preserve_vibrato, 0.0, 1.0))
    nyquist     = sr / 2.0

    # ── pYIN F0 detection ─────────────────────────────────────────────────
    det      = detect_pitch(audio_arr, sr=sr, fast=False)
    f0_array = np.asarray(det["f0_array"], dtype=np.float64)
    f0_times = np.asarray(det["times"],    dtype=np.float64)

    if f0_array.size == 0 or not np.any(np.isfinite(f0_array)):
        return audio_arr  # fully unvoiced — pass through

    # ── STFT analysis ─────────────────────────────────────────────────────
    noverlap = fft_size - hop_size
    _, stft_times, Zxx = stft(
        audio_arr, sr,
        window='hann', nperseg=fft_size, noverlap=noverlap,
        boundary='zeros', padded=True,
    )
    # Zxx: complex, shape (n_bins, n_frames);  n_bins = fft_size//2+1
    n_bins, n_frames = Zxx.shape

    # ── Interpolate F0 onto the STFT frame grid ───────────────────────────
    voiced_mask = np.isfinite(f0_array) & (f0_array > 50.0)
    if np.sum(voiced_mask) < 2:
        return audio_arr

    # Extend stft_times to cover all frames (stft may return fewer times
    # than frame columns due to boundary handling)
    if len(stft_times) < n_frames:
        stft_times = np.arange(n_frames) * hop_size / sr

    f0_voiced_vals = f0_array[voiced_mask]
    f0_interp = np.interp(
        stft_times,
        f0_times[voiced_mask],
        f0_voiced_vals,
        left=float(f0_voiced_vals[0]),    # hold first voiced value leftward
        right=float(f0_voiced_vals[-1]),  # hold last voiced value rightward
    )
    # f0_interp is now always a plausible F0 (no zeros), so log2 stays in
    # a sane range and the vibrato-separation moving average can't be
    # contaminated by log2(0) = -inf spikes at unvoiced gaps.

    # ── Voiced-frame gate ─────────────────────────────────────────────────
    # A frame is voiced if pYIN has a real detection within ±1.5 hops.
    voiced_frames = np.zeros(n_frames, dtype=bool)
    t_voiced      = f0_times[voiced_mask]
    tol           = 1.5 * hop_size / sr
    for i in range(n_frames):
        voiced_frames[i] = np.any(np.abs(t_voiced - stft_times[i]) <= tol)

    # ── Soft retune: exponential smoothing in log2 space ─────────────────
    hop_s    = hop_size / sr
    target_x = np.log2(max(1e-6, target_freq))
    x        = np.log2(np.maximum(f0_interp, 1e-6))

    new_x            = retune_log2(x, target_x, amount_f, vib_f, hop_s, retune_speed_ms)
    ratio_per_frame  = np.power(2.0, new_x - x)          # shape (n_frames,)
    f0_target_frames = f0_interp * ratio_per_frame        # shape (n_frames,)

    # ── Per-frame spectral resampling pitch shift ─────────────────────────
    # For each voiced frame we RELOCATE the original spectral content to the
    # target pitch rather than generating new cosine excitation.
    #
    # For output bin k (at frequency k*sr/fft_size), we sample the ORIGINAL
    # complex STFT spectrum at input bin k/ratio (where ratio = f0_tgt/f0_orig).
    # This shifts every frequency component — harmonics AND inter-harmonic
    # noise/breath — proportionally to the new pitch.
    #
    # The phase at each output bin comes directly from the original signal,
    # preserving the natural waveform complexity (glottal pulse shape, jitter,
    # shimmer) instead of synthetic cosine phases.
    #
    # The magnitude is replaced by the cepstral spectral envelope E[k] to
    # decouple pitch from formants: harmonics move, formants stay.

    formant_ratio = (2.0 ** (float(formant_shift_cents) / 1200.0)
                     if formant_shift_cents != 0 else 1.0)

    out_bins = np.arange(n_bins, dtype=np.float64)   # [0, 1, ..., n_bins-1]
    Zout     = Zxx.copy()   # unvoiced frames stay exactly as original

    # ── Phase vocoder accumulators ────────────────────────────────────────
    # expected_advance[k]: how much bin k's phase should advance per hop if
    # the signal were a pure tone exactly at that bin's centre frequency.
    # This is 2π * (k * sr/fft_size) * hop_size/sr = 2π * k * hop/fft_size.
    expected_advance = 2.0 * np.pi * out_bins * hop_size / fft_size

    # phase_accum[k]: running output phase per bin, propagated across frames.
    phase_accum    = np.zeros(n_bins, dtype=np.float64)
    # X_shifted_prev: resampled spectrum from the previous voiced frame,
    # needed to measure the frame-to-frame phase advance in the source signal.
    X_shifted_prev = np.zeros(n_bins, dtype=np.complex128)
    first_voiced   = True   # seed the accumulator on the first voiced frame

    for i in range(n_frames):
        ratio = ratio_per_frame[i] if i < len(ratio_per_frame) else 1.0

        if not voiced_frames[i] or ratio <= 0.0 or not np.isfinite(ratio):
            # Unvoiced — pass through; refresh the prev-frame reference so
            # the PV doesn't see a stale phase when voice resumes.
            X_shifted_prev = Zxx[:, i].copy()
            first_voiced   = True   # treat next voiced frame as a fresh start
            continue

        X = Zxx[:, i]   # original complex spectrum, shape (n_bins,)

        # ── 1. Spectral envelope E[k] from original frame ─────────────
        # Cepstral smoothing (order 150) gives a smooth formant envelope that
        # covers every bin — full spectral density, no hollow gaps.
        A    = np.abs(X)
        A_db = 20.0 * np.log10(np.maximum(A, 1e-10))
        E_db = estimate_spectral_envelope(A_db, sr, cepstral_order=150)
        E    = 10.0 ** (E_db / 20.0)

        # Natural HF rolloff: real voice energy drops sharply above ~5-8 kHz
        E = _apply_hf_rolloff(E, sr, fft_size)

        # Normalise so output frame has the same spectral energy as the input
        E_power = float(np.mean(E ** 2))
        A_power = float(np.mean(A ** 2))
        if E_power > 0.0:
            E = E * np.sqrt(A_power / E_power)

        # Optional independent formant shift
        if formant_shift_cents != 0:
            E = np.interp(out_bins / formant_ratio, out_bins, E,
                          left=0.0, right=0.0)

        # ── 2. Resample original complex spectrum to target pitch ──────
        # in_bins[k] = k / ratio  — the input bin whose frequency maps to
        # output frequency k*sr/fft_size after the pitch-ratio scaling.
        in_bins   = out_bins / ratio
        X_re      = np.interp(in_bins, out_bins, np.real(X), left=0.0, right=0.0)
        X_im      = np.interp(in_bins, out_bins, np.imag(X), left=0.0, right=0.0)
        X_shifted = X_re + 1j * X_im

        # ── 3. Phase vocoder phase propagation ────────────────────────
        # Measure how much the resampled spectrum's phase actually advanced
        # since the last frame, subtract the expected advance to get the
        # instantaneous deviation (true frequency offset), then integrate
        # into the output accumulator.  This makes consecutive output frames
        # phase-coherent at each bin's true frequency — no ISTFT smearing.
        if first_voiced:
            # Seed: start accumulator at the resampled signal's own phase so
            # the first output frame is anchored to the real signal.
            phase_accum = np.angle(X_shifted).copy()
            first_voiced = False
        else:
            actual_advance  = np.angle(X_shifted) - np.angle(X_shifted_prev)
            deviation       = np.angle(np.exp(1j * (actual_advance - expected_advance)))
            inst_freq       = expected_advance + deviation
            phase_accum    += inst_freq

        X_shifted_prev = X_shifted.copy()

        # ── 4. Output = envelope magnitude × propagated phase ─────────
        Zout[:, i] = E * np.exp(1j * phase_accum)

    # ── ISTFT synthesis ───────────────────────────────────────────────────
    _, output = istft(
        Zout, sr,
        window='hann', nperseg=fft_size, noverlap=noverlap,
        boundary=True,
    )

    # ── RMS envelope correction ───────────────────────────────────────────
    # Use fixed frame parameters for consistent correction across all sample rates
    output = _apply_rms_envelope(audio_arr, output, frame_len=2048, hop=512,
                                 gain_min=0.0, gain_max=8.0, smooth_sigma=2.0)

    # ── Length guard ──────────────────────────────────────────────────────
    if len(output) >= orig_len:
        output = output[:orig_len]
    else:
        output = np.pad(output, (0, orig_len - len(output)))

    return output


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None) -> np.ndarray:
    return autotune_sine_spectral(
        audio,
        int(sr),
        str(settings["target_note"]),
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        preserve_formants=bool(settings.get("preserve_formants", True)),
        formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
    )
