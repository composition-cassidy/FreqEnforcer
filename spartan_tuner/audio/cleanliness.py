from __future__ import annotations

import numpy as np

import librosa
from scipy.ndimage import gaussian_filter1d


def apply_cleanliness(
    audio: np.ndarray,
    sr: int,
    cleanliness_percent: float,
    f0_floor: float = 50.0,
    f0_ceil: float = 500.0,
    hf_bypass_hz: float = 6500.0,
    n_harmonics: int = 30,
    preserve_unvoiced: bool = True,
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

    max_isolation_freq = float(min(float(hf_bypass_hz), float(sr) / 2.0))
    if max_isolation_freq <= 0.0:
        return audio_arr

    n_fft = 2048
    hop_length = 512

    S = librosa.stft(audio_arr.astype(np.float32, copy=False), n_fft=n_fft, hop_length=hop_length)
    magnitude = np.abs(S)
    phase = np.angle(S)

    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    f0, voiced_flag, _voiced_prob = librosa.pyin(
        audio_arr.astype(np.float32, copy=False),
        fmin=f0_floor,
        fmax=f0_ceil,
        sr=sr,
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

        max_harmonics_for_cutoff = int(max_isolation_freq / frame_f0)
        harmonic_limit = min(int(n_harmonics), max_harmonics_for_cutoff)

        for h in range(1, harmonic_limit + 1):
            harmonic_freq = frame_f0 * float(h)
            if harmonic_freq >= max_isolation_freq:
                break

            gaussian = np.exp(-0.5 * ((freqs - harmonic_freq) / sigma_hz) ** 2)
            mask[:, t] += gaussian.astype(np.float32, copy=False)

    mask = np.clip(mask, 0.0, 1.0)

    mask = gaussian_filter1d(mask, sigma=2, axis=1)
    mask = np.clip(mask, 0.0, 1.0)

    if preserve_unvoiced and np.any(unvoiced_frames):
        mask[:, unvoiced_frames] = 1.0

    mask[freqs >= max_isolation_freq, :] = 1.0

    filtered_magnitude = magnitude * mask

    S_filtered = filtered_magnitude * np.exp(1j * phase)

    output = librosa.istft(S_filtered, hop_length=hop_length, length=int(audio_arr.shape[0]))

    return output.astype(audio_arr.dtype, copy=False)


def preview_cleanliness_mask(
    audio: np.ndarray,
    sr: int,
    cleanliness_percent: float,
    f0_floor: float = 50.0,
    f0_ceil: float = 500.0,
    hf_bypass_hz: float = 6500.0,
    n_harmonics: int = 30,
    preserve_unvoiced: bool = True,
) -> tuple:
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

    S = librosa.stft(audio_arr.astype(np.float32, copy=False), n_fft=n_fft, hop_length=hop_length)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times = librosa.times_like(S, sr=sr, hop_length=hop_length)

    f0, voiced_flag, _ = librosa.pyin(
        audio_arr.astype(np.float32, copy=False),
        fmin=f0_floor,
        fmax=f0_ceil,
        sr=sr,
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

    max_isolation_freq = float(min(float(hf_bypass_hz), float(sr) / 2.0))
    if max_isolation_freq <= 0.0:
        return np.ones((len(freqs), n_frames), dtype=np.float32), freqs, times

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
        max_harmonics_for_cutoff = int(max_isolation_freq / frame_f0) if frame_f0 > 0 else 0
        harmonic_limit = min(int(n_harmonics), max_harmonics_for_cutoff)

        for h in range(1, harmonic_limit + 1):
            harmonic_freq = frame_f0 * float(h)
            if harmonic_freq >= max_isolation_freq:
                break
            gaussian = np.exp(-0.5 * ((freqs - harmonic_freq) / sigma_hz) ** 2)
            mask[:, t] += gaussian.astype(np.float32, copy=False)

    mask = np.clip(mask, 0.0, 1.0)

    mask[freqs >= max_isolation_freq, :] = 1.0

    return mask, freqs, times
