"""Soft-retune F0 trajectory shared by the world_soft/vt/hnm, praat, sine and
stft modes: log2-domain vibrato split, amount blend, one-pole glide."""

from __future__ import annotations

import numpy as np

VIBRATO_WINDOW_S = 0.12


def moving_average(x: np.ndarray, n: int) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if n <= 1 or arr.size == 0:
        return arr
    w = int(n)
    pad_left = w // 2
    pad_right = w - 1 - pad_left
    padded = np.pad(arr, (pad_left, pad_right), mode="edge")
    kernel = np.ones((w,), dtype=np.float64) / float(w)
    return np.convolve(padded, kernel, mode="valid")


def clamp_unit(value: float) -> float:
    """Clamp to [0, 1]; non-finite values mean 'full effect' (1.0)."""
    v = float(value)
    if not np.isfinite(v):
        v = 1.0
    return max(0.0, min(1.0, v))


def one_pole_alpha(hop_s: float, retune_speed_ms: float) -> float:
    """Smoothing coefficient for a glide with time constant *retune_speed_ms*."""
    tau = float(retune_speed_ms) / 1000.0
    if not np.isfinite(tau) or tau <= 0:
        return 0.0
    alpha = float(np.exp(-hop_s / max(1e-6, tau)))
    return max(0.0, min(0.9999, alpha))


def retune_log2(
    x: np.ndarray,
    target_x: float,
    amount: float,
    preserve_vibrato: float,
    hop_s: float,
    retune_speed_ms: float,
    slow_source: np.ndarray | None = None,
) -> np.ndarray:
    """Corrected log2-F0 trajectory.

    The slow component (a VIBRATO_WINDOW_S moving average of *slow_source*,
    default *x*) is pulled towards *target_x* by *amount*, glided with a
    one-pole filter, and the fast (vibrato) residual ``x - slow`` is added
    back scaled by *preserve_vibrato*.
    """
    vib_window_frames = max(3, int(round(VIBRATO_WINDOW_S / hop_s)))
    src = x if slow_source is None else slow_source
    x_slow = moving_average(np.asarray(src, dtype=np.float64), vib_window_frames)
    x_fast = np.asarray(x, dtype=np.float64) - x_slow

    x_desired = x_slow + amount * (target_x - x_slow)

    alpha = one_pole_alpha(hop_s, retune_speed_ms)
    y = np.asarray(x_desired, dtype=np.float64).copy()
    for i in range(1, int(y.size)):
        y[i] = alpha * y[i - 1] + (1.0 - alpha) * y[i]

    return y + preserve_vibrato * x_fast
