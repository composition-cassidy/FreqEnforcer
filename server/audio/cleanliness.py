from __future__ import annotations

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
    cached_f0: np.ndarray = None,
    cached_voiced: np.ndarray = None,
) -> np.ndarray:
    from scipy.ndimage import gaussian_filter1d

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
        n_harmonics: Number of harmonics to preserve (including fundamental)

    Returns:
        Processed audio as numpy array
    """
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

    n_fft = 2048
    hop_length = 512

    from scipy.signal import stft as scipy_stft, istft as scipy_istft

    # Pre-pad by n_fft zeros so the last real samples are always covered by a
    # full STFT window. Without this, padded=False drops the final partial
    # window and the ISTFT output is short, forcing zero-padding that creates
    # an abrupt click at the end of sustained notes.
    audio_padded = np.pad(audio_arr.astype(np.float32, copy=False), (0, n_fft))
    _f, _t, S = scipy_stft(audio_padded,
                            fs=sr, nperseg=n_fft, noverlap=n_fft - hop_length,
                            boundary=None, padded=False)
    magnitude = np.abs(S)
    phase = np.angle(S)

    freqs = _f

    if cached_f0 is not None:
        # Use cached f0 from WORLD analysis — resample to STFT frame rate
        n_frames = S.shape[1]
        stft_hop_s = float(hop_length) / float(sr)
        stft_times = np.arange(n_frames) * stft_hop_s

        cached_hop_s = stft_times[-1] / max(1, len(cached_f0) - 1) if len(cached_f0) > 1 else stft_hop_s
        cached_times = np.arange(len(cached_f0)) * cached_hop_s

        from scipy.interpolate import interp1d
        f0_interp = interp1d(cached_times, cached_f0, kind='nearest',
                             fill_value='extrapolate', bounds_error=False)
        f0 = f0_interp(stft_times)
        f0 = np.where(np.isfinite(f0) & (f0 > 0), f0, 0.0)

        if cached_voiced is not None:
            voiced_interp = interp1d(cached_times[:len(cached_voiced)],
                                     cached_voiced.astype(np.float64),
                                     kind='nearest', fill_value=0, bounds_error=False)
            voiced_flag = voiced_interp(stft_times) > 0.5
        else:
            voiced_flag = f0 > 0
    else:
        from server.audio.pitch_yin import pyin
        f0, voiced_flag, _voiced_prob = pyin(
            audio_arr.astype(np.float32, copy=False),
            sr,
            fmin=f0_floor,
            fmax=f0_ceil,
            frame_length=n_fft,
            hop_length=hop_length,
        )

    if f0 is None or len(f0) == 0:
        return audio_arr

    n_frames = S.shape[1]
    if len(f0) > n_frames:
        f0 = f0[:n_frames]
        voiced_flag = voiced_flag[:n_frames]
    elif len(f0) < n_frames:
        pad_length = n_frames - len(f0)
        f0 = np.pad(f0, (0, pad_length), mode="edge")
        voiced_flag = np.pad(voiced_flag, (0, pad_length), mode="edge")

    min_bandwidth = 10.0
    max_bandwidth = 200.0
    bandwidth_hz = max_bandwidth - (cleanliness_percent / 100.0) * (max_bandwidth - min_bandwidth)

    mask = np.zeros_like(magnitude, dtype=np.float32)
    unvoiced_frames = np.zeros((n_frames,), dtype=bool)

    for t in range(n_frames):
        if preserve_unvoiced and (not bool(voiced_flag[t])):
            unvoiced_frames[t] = True
            mask[:, t] = 1.0
            continue

        if np.isnan(f0[t]) or f0[t] <= 0:
            unvoiced_frames[t] = True
            mask[:, t] = 1.0
            continue

        frame_f0 = float(f0[t])

        sigma_hz = float(bandwidth_hz) / 2.355
        if sigma_hz <= 0:
            mask[:, t] = 1.0
            continue

        k = np.rint(freqs / frame_f0)
        harmonic_freqs = k * frame_f0
        dist = np.abs(freqs - harmonic_freqs)
        frame_mask = np.exp(-0.5 * (dist / sigma_hz) ** 2)
        mask[:, t] = frame_mask.astype(np.float32, copy=False)

    mask = np.clip(mask, 0.0, 1.0)

    mask = gaussian_filter1d(mask, sigma=2, axis=1)
    mask = np.clip(mask, 0.0, 1.0)

    if preserve_unvoiced and np.any(unvoiced_frames):
        mask[:, unvoiced_frames] = 1.0

    mask[freqs >= bypass_start_hz, :] = 1.0

    if hf_rollback_percent > 0.0:
        mask = apply_hf_rollback(mask, freqs, float(hf_rollback_percent), int(sr))

    filtered_magnitude = magnitude * mask

    S_filtered = filtered_magnitude * np.exp(1j * phase)

    _, output = scipy_istft(S_filtered, fs=sr, nperseg=n_fft,
                            noverlap=n_fft - hop_length, boundary=False)

    # Trim or pad to match input length
    target_len = int(audio_arr.shape[0])
    if len(output) > target_len:
        output = output[:target_len]
    elif len(output) < target_len:
        output = np.pad(output, (0, target_len - len(output)), mode='constant')

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
