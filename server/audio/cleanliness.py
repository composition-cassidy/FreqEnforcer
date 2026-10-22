from __future__ import annotations

import warnings

import numpy as np

# ---------------------------------------------------------------------------
# Smart low-cut helpers
# ---------------------------------------------------------------------------

_LC_X = [0.0, 10.0, 25.0, 75.0, 100.0]
_LC_Y = [0.0, 70.0, 90.0, 98.0, 100.0]


def lowcut_curve(amount_percent: float) -> float:
    """
    Map Cleanliness knob (0-100) to low-cut engagement (0-100%).
    Piecewise-linear breakpoints: 0→0, 10→70, 25→90, 75→98, 100→100.
    """
    return float(np.interp(float(amount_percent), _LC_X, _LC_Y))


def lowcut_reference_f0(f0_contour) -> float | None:
    """Lowest sustained fundamental of an output F0 contour (5th percentile of
    its voiced frames), the f0 the smart low cut must stay below. None when
    the contour has no voiced frame."""
    if f0_contour is None:
        return None
    f0 = np.asarray(f0_contour, dtype=np.float64)
    voiced = f0[np.isfinite(f0) & (f0 > 0)]
    if voiced.size == 0:
        return None
    return float(np.percentile(voiced, 5))


def compute_smart_lowcut(f0_hz: float, amount_percent: float) -> float:
    """
    Fundamental-aware high-pass cutoff.
    Cutoff never exceeds f0 * 0.85, preserving the fundamental's lower skirt.
    Falls back to f0 = 50 Hz when no pitch detected.
    """
    if not np.isfinite(float(f0_hz)) or float(f0_hz) <= 0.0:
        f0_hz = 50.0

    max_cutoff = float(f0_hz) * 0.85
    min_cutoff = 20.0

    if max_cutoff <= min_cutoff:
        return 0.0

    cutoff = min_cutoff + (float(amount_percent) / 100.0) * (max_cutoff - min_cutoff)
    return float(np.clip(cutoff, 0.0, max_cutoff))


def apply_hf_rollback(
    mask: np.ndarray,
    freqs: np.ndarray,
    rollback_percent: float,
    sr: int,
) -> np.ndarray:
    """
    Fade the harmonic mask toward 1.0 (bypass) in the high frequencies.
    start_hz maps logarithmically: 0% → Nyquist, 100% → 2 kHz.
    """
    if rollback_percent <= 0.0:
        return mask

    nyq = float(sr) / 2.0
    t = float(rollback_percent) / 100.0
    start_hz = nyq * ((2000.0 / nyq) ** t)
    start_hz = float(np.clip(start_hz, 2000.0, nyq))

    fade = np.ones(len(freqs), dtype=np.float32)
    above = freqs > start_hz
    if np.any(above):
        span = max(nyq - start_hz, 1.0)
        fade[above] = 1.0 - np.clip((freqs[above] - start_hz) / span, 0.0, 1.0)

    fade2d = fade[:, np.newaxis]
    return (mask * fade2d + (1.0 - fade2d)).astype(np.float32)


def contour_on_frames(f0_contour, f0_times, frame_times) -> tuple[np.ndarray, np.ndarray]:
    """Sample an F0 contour (Hz, 0 = unvoiced; times in s) at STFT frame
    centres.  Voicing comes from the nearest contour point; the value is
    interpolated over voiced points only, so unvoiced zeros never drag a
    voiced frame's F0 down.  Frames outside the contour are unvoiced."""
    ft = np.asarray(frame_times, dtype=np.float64)
    f0 = np.asarray(f0_contour, dtype=np.float64)
    tc = np.asarray(f0_times, dtype=np.float64)
    n = min(f0.size, tc.size)
    out = np.zeros(ft.size, dtype=np.float64)
    if n == 0:
        return out, out > 0
    f0, tc = f0[:n], tc[:n]
    good = np.isfinite(f0) & (f0 > 0)
    if not np.any(good):
        return out, out > 0
    idx = np.clip(np.searchsorted(tc, ft), 0, n - 1)
    prev = np.clip(idx - 1, 0, n - 1)
    idx = np.where(np.abs(tc[prev] - ft) < np.abs(tc[idx] - ft), prev, idx)
    step = float(np.median(np.diff(tc))) if n > 1 else 0.0
    inside = (ft >= tc[0] - step) & (ft <= tc[-1] + step)
    voiced = good[idx] & inside
    out[voiced] = np.interp(ft[voiced], tc[good], f0[good])
    return out, voiced


# Mask design (cleanliness).  Values chosen on the post-pitch sweep
# (tests/sweep/), see the commit that introduced them for the numbers.
CLEAN_BINS_PER_HARMONIC = 4.0   # n_fft so the lowest harmonic spacing spans >= 4 bins,
                                # the full width of a Hann main lobe
CLEAN_NFFT_MIN = 2048           # 46 ms; a 1024 floor widens the 2-bin mask to 86 Hz
                                # and removes ~2 dB less noise on high notes
CLEAN_NFFT_MAX = 8192           # 186 ms at 44.1 kHz; separates harmonics down to ~22 Hz
CLEAN_MIN_FWHM_BINS = 2.0       # mask never narrower than 2 STFT bins
CLEAN_TIME_SIGMA_S = 0.020      # mask smoothing across time, inside voiced runs
CLEAN_GUARD_S = 0.005           # output envelope never above the input's (5 ms RMS)


def cleanliness_n_fft(f0_low_hz: float, sr: int) -> int:
    """STFT size that separates harmonics of *f0_low_hz*: the smallest power
    of two giving CLEAN_BINS_PER_HARMONIC bins per harmonic spacing, clamped
    to [CLEAN_NFFT_MIN, CLEAN_NFFT_MAX]."""
    if not np.isfinite(f0_low_hz) or f0_low_hz <= 0:
        return 2048
    n = 2 ** int(np.ceil(np.log2(CLEAN_BINS_PER_HARMONIC * float(sr) / float(f0_low_hz))))
    return int(min(CLEAN_NFFT_MAX, max(CLEAN_NFFT_MIN, n)))


def _envelope_guard(x: np.ndarray, y: np.ndarray, sr: int) -> np.ndarray:
    """Scale *y* so its short-term RMS never exceeds *x*'s.

    The mask only removes energy, but an STFT frame that straddles a note
    on/offset spreads what is left over the whole window, into silence.  The
    gain is min(1, rms_in / rms_out) over CLEAN_GUARD_S, eroded then smoothed
    over the same width (a moving average of a running minimum never exceeds
    the pointwise limit), so it only acts where the output has more energy
    than the input had: at transients, never inside a sustained note."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    w = max(8, int(round(CLEAN_GUARD_S * sr)))
    e_in = np.sqrt(np.maximum(uniform_filter1d(x * x, w), 0.0))
    e_out = np.sqrt(np.maximum(uniform_filter1d(y * y, w), 0.0))
    g = np.minimum(1.0, (e_in + 1e-12) / (e_out + 1e-12))
    g = uniform_filter1d(minimum_filter1d(g, w), w)
    return y * g


def apply_cleanliness(
    audio: np.ndarray,
    sr: int,
    cleanliness_percent: float,
    f0_floor: float = 50.0,
    f0_ceil: float = 500.0,
    hf_bypass_hz: float = 0.0,
    n_harmonics: int = 30,
    preserve_unvoiced: bool = True,
    hf_rollback_percent: float = 0.0,
    f0_contour: np.ndarray = None,
    f0_times: np.ndarray = None,
) -> np.ndarray:
    """
    Apply harmonic isolation to remove frequencies between harmonics.

    This creates a "cleaner" sample by keeping only the fundamental frequency
    and its harmonics, removing mud, room noise, and non-harmonic content.

    WARNING: High cleanliness values (80-100%) will make speech sound robotic/vocoder-like.
    Best used on sustained vowels. Consonants need noise to be intelligible.

    Args:
        audio: Input audio as numpy array
        sr: Sample rate
        cleanliness_percent: 0 = no effect, 100 = tight harmonic isolation
                            Recommended range: 20-60% for speech
        f0_floor: Minimum f0 to detect (Hz)
        f0_ceil: Maximum f0 to detect (Hz)
        n_harmonics: unused, kept for API compatibility
        f0_contour, f0_times: F0 of THIS audio (Hz, 0 = unvoiced) and its
            times in s, e.g. the pitch mode's output contour.  When omitted,
            F0 is estimated with pyin (f0_floor..f0_ceil).

    The STFT size follows the lowest voiced F0 (cleanliness_n_fft), the
    Gaussian mask around each harmonic is never narrower than
    CLEAN_MIN_FWHM_BINS bins, it is smoothed across time inside voiced runs
    and cross-faded to 1 (bypass) at voicing edges, the signal is padded on
    both ends so every output sample sits under full overlap-add, and the
    result is held under the input's envelope (_envelope_guard).

    Returns:
        Processed audio as numpy array
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import stft as scipy_stft, istft as scipy_istft

    audio_arr = np.asarray(audio)

    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    if cleanliness_percent <= 0:
        return audio_arr

    duration_s = float(audio_arr.shape[0]) / float(sr)
    if duration_s < 0.2:
        return audio_arr

    cleanliness_percent = min(100.0, max(0.0, float(cleanliness_percent)))

    bypass_start_hz = float(hf_bypass_hz)
    if not np.isfinite(bypass_start_hz) or bypass_start_hz <= 0.0:
        bypass_start_hz = float(sr) / 2.0
    bypass_start_hz = float(min(bypass_start_hz, float(sr) / 2.0))

    x = audio_arr.astype(np.float64, copy=False)

    if f0_contour is None:
        from server.audio.pitch_yin import pyin
        frame, hop_est = 2048, 512
        est, _voiced, _prob = pyin(x.astype(np.float32), sr, fmin=f0_floor, fmax=f0_ceil,
                                   frame_length=frame, hop_length=hop_est)
        f0_contour = np.where(np.isfinite(est), est, 0.0)
        f0_times = (np.arange(f0_contour.size) * hop_est + frame / 2.0) / float(sr)

    f0_contour = np.asarray(f0_contour, dtype=np.float64)
    voiced_f0 = f0_contour[np.isfinite(f0_contour) & (f0_contour > 0)]
    if voiced_f0.size == 0:
        return audio_arr

    n_fft = cleanliness_n_fft(float(np.percentile(voiced_f0, 5)), sr)
    hop_length = n_fft // 4

    # Pad n_fft on BOTH ends: every real sample is then covered by full
    # overlap-add.  (Padding only the end left the first samples divided by a
    # ~0 window sum in the ISTFT - scipy's "NOLA" warning - which spiked the
    # first milliseconds by up to +80 dBFS.)
    xp = np.pad(x, (n_fft, n_fft))
    freqs, frame_t, S = scipy_stft(xp, fs=sr, nperseg=n_fft, noverlap=n_fft - hop_length,
                                   boundary=None, padded=False)
    frame_t = frame_t - n_fft / float(sr)
    f0, voiced_flag = contour_on_frames(f0_contour, f0_times, frame_t)
    if not np.any(voiced_flag):
        return audio_arr

    min_bandwidth = 10.0
    max_bandwidth = 200.0
    bandwidth_hz = max_bandwidth - (cleanliness_percent / 100.0) * (max_bandwidth - min_bandwidth)
    bandwidth_hz = max(bandwidth_hz, CLEAN_MIN_FWHM_BINS * float(sr) / n_fft)
    sigma_hz = float(bandwidth_hz) / 2.355

    mask = np.ones(S.shape, dtype=np.float64)
    for t in np.flatnonzero(voiced_flag):
        harmonic_freqs = np.rint(freqs / f0[t]) * f0[t]
        mask[:, t] = np.exp(-0.5 * ((freqs - harmonic_freqs) / sigma_hz) ** 2)

    # Smooth across time inside voiced runs only (unvoiced frames don't pull
    # the comb toward 1), then cross-fade to bypass with a smoothed voicing
    # weight instead of switching hard at voicing edges.
    sigma_frames = CLEAN_TIME_SIGMA_S * float(sr) / hop_length
    v = voiced_flag.astype(np.float64)
    num = gaussian_filter1d(mask * v[np.newaxis, :], sigma=sigma_frames, axis=1)
    den = gaussian_filter1d(v, sigma=sigma_frames)
    mask = np.where(den[np.newaxis, :] > 1e-6, num / np.maximum(den, 1e-6)[np.newaxis, :], 1.0)
    mask = den[np.newaxis, :] * mask + (1.0 - den[np.newaxis, :])
    mask = np.clip(mask, 0.0, 1.0)

    mask[freqs >= bypass_start_hz, :] = 1.0

    if hf_rollback_percent > 0.0:
        mask = apply_hf_rollback(mask, freqs, float(hf_rollback_percent), int(sr))

    # scipy checks NOLA over the whole padded signal; it only fails inside the
    # n_fft margins, which are cut off below.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="NOLA condition failed")
        _, output = scipy_istft(S * mask, fs=sr, nperseg=n_fft,
                                noverlap=n_fft - hop_length, boundary=False)
    output = output[n_fft:n_fft + x.size]
    if output.size < x.size:
        output = np.pad(output, (0, x.size - output.size))

    output = _envelope_guard(x, output, int(sr))
    return output.astype(audio_arr.dtype, copy=False)


def _apply_iir_filter(audio: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    from scipy.signal import filtfilt, lfilter

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")
    if audio_arr.size == 0:
        return audio_arr

    x = np.asarray(audio_arr, dtype=np.float64)

    try:
        padlen = int(3 * (max(len(a), len(b)) - 1))
    except Exception:
        padlen = 0

    try:
        if padlen > 0 and int(x.size) > int(padlen):
            y = filtfilt(b, a, x)
        else:
            y = lfilter(b, a, x)
    except Exception:
        y = lfilter(b, a, x)

    return np.asarray(y, dtype=audio_arr.dtype)


def apply_low_cut(audio: np.ndarray, sr: int, cutoff_hz: float, order: int = 2) -> np.ndarray:
    from scipy.signal import butter

    audio_arr = np.asarray(audio)
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    cutoff = float(cutoff_hz)
    if not np.isfinite(cutoff) or cutoff <= 0.0:
        return audio_arr

    nyq = float(sr) / 2.0
    if cutoff >= nyq:
        return audio_arr

    w = float(cutoff) / float(nyq)
    b, a = butter(int(order), w, btype="highpass")
    return _apply_iir_filter(audio_arr, b=b, a=a)


def apply_high_shelf(
    audio: np.ndarray,
    sr: int,
    freq_hz: float,
    gain_db: float,
    slope: float = 1.0,
) -> np.ndarray:
    audio_arr = np.asarray(audio)
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    f0 = float(freq_hz)
    g = float(gain_db)
    if (not np.isfinite(f0)) or (not np.isfinite(g)):
        return audio_arr
    if abs(g) < 1e-9:
        return audio_arr

    nyq = float(sr) / 2.0
    if f0 <= 0.0 or f0 >= nyq:
        return audio_arr

    S = float(slope)
    if (not np.isfinite(S)) or S <= 0.0:
        S = 1.0

    A = float(10.0 ** (g / 40.0))
    w0 = float(2.0 * np.pi * f0 / float(sr))
    cosw0 = float(np.cos(w0))
    sinw0 = float(np.sin(w0))

    alpha = float(sinw0 / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / S - 1.0) + 2.0))
    sqrtA = float(np.sqrt(A))

    b0 = A * ((A + 1.0) + (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha)
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cosw0)
    b2 = A * ((A + 1.0) + (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha)
    a0 = (A + 1.0) - (A - 1.0) * cosw0 + 2.0 * sqrtA * alpha
    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cosw0)
    a2 = (A + 1.0) - (A - 1.0) * cosw0 - 2.0 * sqrtA * alpha

    if a0 == 0.0:
        return audio_arr

    b = np.asarray([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a = np.asarray([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return _apply_iir_filter(audio_arr, b=b, a=a)


def preview_cleanliness_mask(
    audio: np.ndarray,
    sr: int,
    cleanliness_percent: float,
    f0_floor: float = 50.0,
    f0_ceil: float = 500.0,
    hf_bypass_hz: float = 0.0,
    n_harmonics: int = 30,
    preserve_unvoiced: bool = True,
) -> tuple:
    from scipy.signal import stft as scipy_stft
    from server.audio.pitch_yin import pyin

    """
    Generate the cleanliness mask for visualization without applying it.
    Useful for showing the user what will be filtered.

    Args:
        audio: Input audio
        sr: Sample rate
        cleanliness_percent: 0-100
        f0_floor: Min f0
        f0_ceil: Max f0

    Returns:
        Tuple of (mask, frequencies, times) for plotting
    """
    audio_arr = np.asarray(audio)

    n_fft = 2048
    hop_length = 512

    audio_padded = np.pad(audio_arr.astype(np.float32, copy=False), (0, n_fft))
    _f, _t, S = scipy_stft(audio_padded, fs=sr, nperseg=n_fft,
                            noverlap=n_fft - hop_length,
                            boundary=None, padded=False)
    freqs = _f
    times = _t

    f0, voiced_flag, _ = pyin(
        audio_arr.astype(np.float32, copy=False),
        sr,
        fmin=f0_floor,
        fmax=f0_ceil,
        frame_length=n_fft,
        hop_length=hop_length,
    )

    if f0 is None:
        f0 = np.array([], dtype=np.float32)
    if voiced_flag is None:
        voiced_flag = np.array([], dtype=bool)

    n_frames = S.shape[1]
    if len(f0) == 0 and n_frames > 0:
        f0 = np.full((n_frames,), np.nan, dtype=np.float32)
    if len(voiced_flag) == 0 and n_frames > 0:
        voiced_flag = np.full((n_frames,), False, dtype=bool)
    if len(f0) > n_frames:
        f0 = f0[:n_frames]
        voiced_flag = voiced_flag[:n_frames]
    elif len(f0) < n_frames:
        f0 = np.pad(f0, (0, n_frames - len(f0)), mode="edge")
        voiced_flag = np.pad(voiced_flag, (0, n_frames - len(voiced_flag)), mode="edge")

    bypass_start_hz = float(hf_bypass_hz)
    if not np.isfinite(bypass_start_hz) or bypass_start_hz <= 0.0:
        bypass_start_hz = float(sr) / 2.0
    bypass_start_hz = float(min(bypass_start_hz, float(sr) / 2.0))

    cleanliness_percent_f = min(100.0, max(0.0, float(cleanliness_percent)))

    min_bandwidth = 10.0
    max_bandwidth = 200.0
    bandwidth_hz = max_bandwidth - (cleanliness_percent_f / 100.0) * (max_bandwidth - min_bandwidth)

    mask = np.zeros((len(freqs), n_frames), dtype=np.float32)

    for t in range(n_frames):
        if preserve_unvoiced and (not bool(voiced_flag[t])):
            mask[:, t] = 1.0
            continue

        if t >= len(f0) or np.isnan(f0[t]) or f0[t] <= 0:
            mask[:, t] = 1.0
            continue

        sigma_hz = float(bandwidth_hz) / 2.355
        if sigma_hz <= 0:
            mask[:, t] = 1.0
            continue

        frame_f0 = float(f0[t])

        k = np.rint(freqs / frame_f0)
        harmonic_freqs = k * frame_f0
        dist = np.abs(freqs - harmonic_freqs)
        frame_mask = np.exp(-0.5 * (dist / sigma_hz) ** 2)
        mask[:, t] = frame_mask.astype(np.float32, copy=False)

    mask = np.clip(mask, 0.0, 1.0)

    mask[freqs >= bypass_start_hz, :] = 1.0

    return mask, freqs, times
