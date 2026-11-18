"""sine_spectral: per-peak spectral relocation (phase-locked vocoder) with a
cepstral formant correction, and the shared soft-retune trajectory (YIN F0)."""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import _apply_rms_envelope, _improved_lifter
from server.audio.modes._retune import retune_log2
from server.utils.note_utils import note_name_to_freq

NAME = "sine_spectral"
USES_WORLD_CACHE = False

F0_MIN = 50.0
F0_MAX = 2000.0
YIN_THRESHOLD = 0.15
VOICED_APERIODICITY = 0.3    # CMND at the chosen lag; above this a frame is unvoiced
MAX_VOICING_GAP_S = 0.025    # unvoiced runs this short inside a note count as voiced
REFINE_HARMONICS = 8         # harmonics used to refine the YIN F0
REFINE_TOL = 0.03            # ... when within 3 % (~50 cents) of h * F0
FORMANT_GAIN_DB = (-60.0, 24.0)


def _fill_short_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    """Set runs of False no longer than *max_gap* that lie between two True runs."""
    out = mask.copy()
    idx = np.flatnonzero(mask)
    if idx.size < 2:
        return out
    gaps = np.diff(idx) - 1
    for start, gap in zip(idx[:-1], gaps):
        if 0 < gap <= max_gap:
            out[start + 1:start + 1 + gap] = True
    return out


def _refine_f0(Zxx: np.ndarray, f0: np.ndarray, frames: np.ndarray, sr: int,
               hop_size: int, n_harmonics: int = REFINE_HARMONICS) -> np.ndarray:
    """Refine YIN F0 on *frames* from the phase-vocoder frequencies of the
    first harmonics: least-squares fit f_h = h * f0 over the harmonic peaks
    found within REFINE_TOL of h * f0, weighted by peak power.  YIN's lag
    interpolation is biased by aperiodic energy; the harmonics' phase
    advance is not.  Frames without a usable harmonic keep their YIN value.
    """
    n_bins, n_frames = Zxx.shape
    fft_size = 2 * (n_bins - 1)
    omega_bin = 2.0 * np.pi * hop_size / fft_size
    frames = frames[frames > 0]
    if frames.size == 0:
        return f0
    mag = np.abs(Zxx)
    h = np.arange(1, n_harmonics + 1, dtype=np.float64)
    centre = np.rint(np.outer(f0[frames], h) * fft_size / sr).astype(np.int64)   # (F, H)
    valid = (centre >= 2) & (centre < n_bins - 2)
    centre = np.clip(centre, 2, n_bins - 3)
    cols = frames[:, None]
    # Loudest of the three bins around each expected harmonic, if it is a local maximum
    cand = centre[..., None] + np.arange(-1, 2)                                 # (F, H, 3)
    peak = np.take_along_axis(cand, mag[cand, cols[..., None]].argmax(axis=-1)[..., None], -1)[..., 0]
    a = mag[peak, cols]
    valid &= (a > mag[peak - 1, cols]) & (a >= mag[peak + 1, cols])
    dphi = np.angle(Zxx[peak, cols]) - np.angle(Zxx[peak, cols - 1]) - omega_bin * peak
    dphi = np.mod(dphi + np.pi, 2.0 * np.pi) - np.pi
    f_h = (peak + dphi / omega_bin) * sr / fft_size                             # Hz
    valid &= np.abs(f_h / h - f0[frames, None]) <= REFINE_TOL * f0[frames, None]
    w = np.where(valid, a * a, 0.0)
    num = np.sum(w * h * f_h, axis=1)
    den = np.sum(w * h * h, axis=1)
    out = f0.copy()
    ok = den > 0
    out[frames[ok]] = num[ok] / den[ok]
    return out


def _peak_regions(mag: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split one frame's bins into peak regions.

    A region runs from one spectral valley to the next, so it holds exactly
    one local maximum.  Returns (region id per bin, peak bin per region);
    region ids and peak bins are both ascending.
    """
    n = mag.size
    valley = np.zeros(n, dtype=bool)
    valley[1:-1] = (mag[1:-1] <= mag[:-2]) & (mag[1:-1] < mag[2:])
    region = np.cumsum(valley)
    order = np.lexsort((-mag, region))          # by region, loudest bin first
    first = np.ones(n, dtype=bool)
    first[1:] = region[order][1:] != region[order][:-1]
    return region, order[first]


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
    hop_size: int = 128,
    return_f0: bool = False,
):
    """
    Harmonic relocation with spectral envelope preservation.

    For each voiced STFT frame:
      1. Split the spectrum into peak regions (each spectral peak plus the
         bins down to the neighbouring valleys).  Every harmonic, and every
         noise peak between harmonics, is one region.
      2. Measure each peak's true frequency from its phase advance since the
         previous frame (phase vocoder), and move the whole region by the
         whole number of bins nearest to (ratio - 1) * that frequency.  The
         region keeps its complex shape, so the window's main lobe and the
         time envelope inside the frame survive the move.
      3. Rotate the region's phase by an accumulator that advances by
         (ratio - 1) * omega_peak * hop per frame (Laroche & Dolson's
         phase-locked pitch shift), so across frames the peak advances at
         ratio * omega_peak: the target frequency.  Peaks inherit the
         accumulator of the nearest peak in the previous frame.
      4. Scale every moved bin by E(destination) / E(source), E being the
         cepstral envelope of the source frame (lifter below the harmonic
         spacing), so harmonics move and formants stay.  formant_shift_cents
         shifts the destination envelope.
      5. ISTFT overlap-add, then an RMS envelope match to the input.

    The source F0 comes from YIN on the same frame grid (frames centred on
    the STFT frames, search range 50-2000 Hz), refined from the phase
    advance of the first harmonics.  Frames whose CMND at the chosen lag
    exceeds VOICED_APERIODICITY are unvoiced and pass through unmodified in
    the STFT domain.  The hop is fft_size / 16: with 8x overlap the frame
    rate (172 Hz) aliases region-boundary leakage next to the harmonics of
    low notes.

    With return_f0, returns (audio, target F0 per STFT frame with 0 on
    unvoiced frames, frame times in s); F0 is None when the audio is passed
    through.
    """
    from scipy.ndimage import median_filter
    from scipy.signal import istft, stft
    from server.audio.pitch_yin import yin_track

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

    # ── STFT analysis ─────────────────────────────────────────────────────
    noverlap = fft_size - hop_size
    _, _, Zxx = stft(
        audio_arr, sr,
        window='hann', nperseg=fft_size, noverlap=noverlap,
        boundary='zeros', padded=True,
    )
    # Zxx: complex, shape (n_bins, n_frames);  n_bins = fft_size//2+1
    n_bins, n_frames = Zxx.shape
    # Frame i is centred on sample i*hop (boundary='zeros' pads fft_size/2)
    stft_times = np.arange(n_frames) * hop_size / sr

    # ── Source F0 on the STFT frame grid (YIN) ────────────────────────────
    f0_max = min(F0_MAX, 0.25 * sr)
    yin_len = 1 << int(np.ceil(np.log2(2.0 * sr / F0_MIN)))
    f0_raw, aperiodicity = yin_track(audio_arr, sr, hop_size, n_frames=n_frames,
                                     fmin=F0_MIN, fmax=f0_max, frame_length=yin_len,
                                     threshold=YIN_THRESHOLD)
    voiced_frames = ((f0_raw >= F0_MIN) & (f0_raw <= f0_max)
                     & (aperiodicity < VOICED_APERIODICITY))
    if np.sum(voiced_frames) < 2:
        return (audio_arr, None, None) if return_f0 else audio_arr

    # Refine from the harmonics' phase advance, median-smooth the voiced
    # values (kills isolated octave slips), then fill short unvoiced gaps
    # inside a note so they don't pass through
    voiced_idx = np.flatnonzero(voiced_frames)
    f0_raw = _refine_f0(Zxx, f0_raw, voiced_idx, sr, hop_size)
    f0_voiced = 2.0 ** median_filter(np.log2(f0_raw[voiced_idx]), size=5, mode='nearest')
    voiced_frames = _fill_short_gaps(voiced_frames, int(round(MAX_VOICING_GAP_S * sr / hop_size)))

    # Interpolate across unvoiced frames, holding the end values, so log2
    # stays sane and the vibrato split isn't contaminated by gaps
    f0_interp = np.interp(np.arange(n_frames), voiced_idx, f0_voiced)

    # ── Soft retune: exponential smoothing in log2 space ─────────────────
    hop_s    = hop_size / sr
    target_x = np.log2(max(1e-6, target_freq))
    x        = np.log2(np.maximum(f0_interp, 1e-6))

    new_x            = retune_log2(x, target_x, amount_f, vib_f, hop_s, retune_speed_ms)
    ratio_per_frame  = np.power(2.0, new_x - x)          # shape (n_frames,)
    f0_target_frames = f0_interp * ratio_per_frame        # shape (n_frames,)

    # ── Formant envelopes (cepstral lifter below the harmonic spacing) ────
    envelopes = np.ones((n_frames, n_bins))
    envelopes[voiced_frames] = _improved_lifter(np.abs(Zxx[:, voiced_frames]).T,
                                                f0_interp[voiced_frames], sr)

    formant_ratio = (2.0 ** (float(formant_shift_cents) / 1200.0)
                     if formant_shift_cents != 0 else 1.0)
    gain_lo, gain_hi = (10.0 ** (g / 20.0) for g in FORMANT_GAIN_DB)

    # ── Per-peak relocation ───────────────────────────────────────────────
    bins      = np.arange(n_bins)
    omega_bin = 2.0 * np.pi * hop_size / fft_size    # phase advance per hop of one bin
    Zout      = Zxx.copy()   # unvoiced frames stay exactly as original

    prev_peaks = None        # peak bins of the previous shifted frame
    prev_theta = None        # their phase-rotation accumulators

    for i in range(n_frames):
        ratio = ratio_per_frame[i]
        if not voiced_frames[i] or not np.isfinite(ratio) or ratio <= 0.0:
            prev_peaks = None    # next voiced frame starts fresh
            continue

        X = Zxx[:, i]
        region, peaks = _peak_regions(np.abs(X))

        # True peak frequency (in bins) from the phase advance since the
        # previous input frame
        if i > 0:
            dphi = np.angle(X[peaks]) - np.angle(Zxx[peaks, i - 1]) - omega_bin * peaks
            dphi = np.mod(dphi + np.pi, 2.0 * np.pi) - np.pi
            peak_freq = peaks + dphi / omega_bin
        else:
            peak_freq = peaks.astype(np.float64)

        shift = np.rint((ratio - 1.0) * peak_freq).astype(np.int64)
        advance = (ratio - 1.0) * omega_bin * peak_freq

        if prev_peaks is None:
            theta = np.zeros(peaks.size)
        else:
            j = np.searchsorted(prev_peaks, peaks)
            lo = np.clip(j - 1, 0, prev_peaks.size - 1)
            hi = np.clip(j, 0, prev_peaks.size - 1)
            nearest = np.where(np.abs(peaks - prev_peaks[lo]) <= np.abs(prev_peaks[hi] - peaks), lo, hi)
            theta = prev_theta[nearest] + advance

        dest = bins + shift[region]
        inside = (dest >= 0) & (dest < n_bins)
        dest_c = np.clip(dest, 0, n_bins - 1)

        env = envelopes[i]
        if formant_ratio != 1.0:
            env_dest = np.interp(dest_c / formant_ratio, bins, env)
        else:
            env_dest = env[dest_c]
        gain = np.clip(env_dest / np.maximum(env, 1e-30), gain_lo, gain_hi)

        moved = X * gain * np.exp(1j * theta[region])
        Zout[:, i] = (np.bincount(dest[inside], weights=moved.real[inside], minlength=n_bins)
                      + 1j * np.bincount(dest[inside], weights=moved.imag[inside], minlength=n_bins))

        prev_peaks, prev_theta = peaks, np.mod(theta, 2.0 * np.pi)

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

    if return_f0:
        return output, np.where(voiced_frames, f0_target_frames, 0.0), np.asarray(stft_times, dtype=np.float64)
    return output


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None):
    return autotune_sine_spectral(
        audio,
        int(sr),
        str(settings["target_note"]),
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        preserve_formants=bool(settings.get("preserve_formants", True)),
        formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
        return_f0=True,
    )
