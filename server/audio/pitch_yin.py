"""
YIN and pYIN pitch detection -- pure numpy/scipy implementation.
Replaces librosa.yin() and librosa.pyin().

References:
  - YIN: de Cheveigne & Kawahara, "YIN, a fundamental frequency estimator
    for speech and music", JASA 2002.
  - pYIN: Mauch & Dixon, "pYIN: A fundamental frequency estimator using
    probabilistic threshold distributions", ICASSP 2014.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter


# ---------------------------------------------------------------------------
# Pre-computed Beta(2, 18) weights for pYIN (50 thresholds in [0.01, 1.0])
# Avoids importing scipy.stats at runtime.
# ---------------------------------------------------------------------------
_PYIN_BETA_WEIGHTS = np.array([
    5.79109909e-02, 1.23195347e-01, 1.43744784e-01, 1.39698195e-01,
    1.23652899e-01, 1.03163473e-01, 8.24909440e-02, 6.38077452e-02,
    4.80123669e-02, 3.52678725e-02, 2.53481007e-02, 1.78523322e-02,
    1.23319162e-02, 8.35950433e-03, 5.56211816e-03, 3.63244047e-03,
    2.32784853e-03, 1.46328552e-03, 9.01713757e-04, 5.44314865e-04,
    3.21572993e-04, 1.85733273e-04, 1.04745594e-04, 5.75954508e-05,
    3.08264452e-05, 1.60292062e-05, 8.07984554e-06, 3.93826786e-06,
    1.85081347e-06, 8.35842276e-07, 3.61331551e-07, 1.48847057e-07,
    5.81184844e-08, 2.13739989e-08, 7.34807648e-09, 2.33996801e-09,
    6.82553199e-10, 1.79854251e-10, 4.20674466e-11, 8.53902556e-12,
    1.46012579e-12, 2.02018792e-13, 2.13732590e-14, 1.59175725e-15,
    7.33951804e-17, 1.68985636e-18, 1.29817685e-20, 1.34593506e-23,
    1.04848751e-28, 0.00000000e+00,
])

_PYIN_THRESHOLDS = np.linspace(0.01, 1.0, 50)


def yin(
    audio: np.ndarray,
    sr: int,
    fmin: float = 50.0,
    fmax: float = 2000.0,
    frame_length: int = 2048,
    hop_length: int = 512,
    threshold: float = 0.8,
) -> np.ndarray:
    """YIN fundamental frequency estimator.  Replaces ``librosa.yin``.

    Returns an array of f0 values per frame (Hz).  Unvoiced frames are 0.0.
    """
    tau_min = max(2, int(sr / fmax))
    tau_max = min(frame_length // 2, int(sr / fmin))
    n_frames = 1 + (len(audio) - frame_length) // hop_length

    f0 = np.zeros(n_frames, dtype=np.float32)

    for i in range(n_frames):
        start = i * hop_length
        frame = audio[start : start + frame_length].astype(np.float64)
        if len(frame) < frame_length:
            break

        d = _difference_function(frame, tau_max)
        d_prime = _cmnd(d, tau_max)
        tau = _absolute_threshold(d_prime, tau_min, tau_max, threshold)

        if tau > 0:
            f0[i] = sr / _parabolic_interpolation(d_prime, tau)

    return f0


def pyin(
    audio: np.ndarray,
    sr: int,
    fmin: float = 50.0,
    fmax: float = 2000.0,
    frame_length: int = 2048,
    hop_length: int = 512,
    threshold: float = 0.3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Probabilistic YIN.  Replaces ``librosa.pyin``.

    Returns ``(f0, voiced_flag, voiced_probs)`` per frame.
    Unvoiced frames have ``f0 = NaN``.
    """
    tau_min = max(2, int(sr / fmax))
    tau_max = min(frame_length // 2, int(sr / fmin))
    n_frames = 1 + (len(audio) - frame_length) // hop_length

    f0 = np.full(n_frames, np.nan, dtype=np.float64)
    voiced_probs = np.zeros(n_frames, dtype=np.float64)

    weights = _PYIN_BETA_WEIGHTS
    thresholds = _PYIN_THRESHOLDS

    for i in range(n_frames):
        start = i * hop_length
        frame = audio[start : start + frame_length].astype(np.float64)
        if len(frame) < frame_length:
            break

        d = _difference_function(frame, tau_max)
        d_prime = _cmnd(d, tau_max)

        freqs = []
        probs = []
        for t_idx, thresh in enumerate(thresholds):
            tau = _absolute_threshold(d_prime, tau_min, tau_max, thresh)
            if tau > 0:
                freq = sr / _parabolic_interpolation(d_prime, tau)
                if fmin <= freq <= fmax:
                    freqs.append(freq)
                    probs.append(weights[t_idx])

        if freqs:
            freqs_a = np.asarray(freqs)
            probs_a = np.asarray(probs)
            voiced_probs[i] = np.sum(probs_a)
            f0[i] = np.average(freqs_a, weights=probs_a)

    # Median-smooth the pitch track
    f0 = _median_smooth_pitch(f0, kernel_size=5)
    voiced_flag = ~np.isnan(f0) & (voiced_probs > 0.3)
    f0[~voiced_flag] = np.nan

    return f0, voiced_flag, voiced_probs


# ------------------------------------------------------------------
# YIN internals
# ------------------------------------------------------------------

def _difference_function(frame: np.ndarray, tau_max: int) -> np.ndarray:
    """Autocorrelation-based difference function."""
    n = len(frame)
    d = np.zeros(tau_max + 1)
    x_cumsum = np.concatenate(([0.0], np.cumsum(frame ** 2)))

    for tau in range(1, tau_max + 1):
        d[tau] = (
            x_cumsum[n - tau] - x_cumsum[0]
            + x_cumsum[n] - x_cumsum[tau]
            - 2.0 * np.dot(frame[: n - tau], frame[tau : n])
        )
    return d


def _cmnd(d: np.ndarray, tau_max: int) -> np.ndarray:
    """Cumulative mean normalised difference."""
    d_prime = np.ones(tau_max + 1)
    running = 0.0
    for tau in range(1, tau_max + 1):
        running += d[tau]
        d_prime[tau] = d[tau] * tau / running if running != 0.0 else 1.0
    return d_prime


def _absolute_threshold(
    d_prime: np.ndarray, tau_min: int, tau_max: int, threshold: float
) -> int:
    """Find the first lag below *threshold* that is a local minimum."""
    for tau in range(tau_min, tau_max):
        if d_prime[tau] < threshold:
            if tau + 1 < tau_max and d_prime[tau] <= d_prime[tau + 1]:
                return tau
    # Fallback: global minimum
    if tau_max > tau_min:
        best = tau_min + int(np.argmin(d_prime[tau_min:tau_max]))
        if d_prime[best] < 1.0:
            return best
    return 0


def _parabolic_interpolation(d_prime: np.ndarray, tau: int) -> float:
    if tau <= 0 or tau >= len(d_prime) - 1:
        return float(tau)
    s0, s1, s2 = d_prime[tau - 1], d_prime[tau], d_prime[tau + 1]
    denom = 2.0 * (2.0 * s1 - s2 - s0)
    if abs(denom) < 1e-10:
        return float(tau)
    return tau + (s2 - s0) / denom


def _median_smooth_pitch(f0: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    result = f0.copy()
    valid = ~np.isnan(f0)
    if np.sum(valid) < kernel_size:
        return result
    vals = f0[valid]
    result[valid] = median_filter(vals, size=kernel_size)
    return result
