"""Pitch correction entry points and WORLD breathiness shaping.

The pitch modes live in server/audio/modes/ (one module per mode behind a
common render() interface).  Their DSP functions are re-exported here so
existing callers keep working.
"""

from __future__ import annotations

import warnings

import numpy as np

from server.audio.modes._retune import moving_average as _moving_average  # noqa: F401
from server.audio.modes._world import dilate_voiced_mask as _dilate_voiced_mask  # noqa: F401
from server.audio.modes.praat_soft import autotune_praat_soft_to_note  # noqa: F401
from server.audio.modes.sine_spectral import autotune_sine_spectral  # noqa: F401
from server.audio.modes.stft_pitchshift import autotune_stft_pitchshift  # noqa: F401
from server.audio.modes.world_hard import autotune_to_note, autotune_with_formant_shift  # noqa: F401
from server.audio.modes.world_soft import autotune_soft_to_note  # noqa: F401
from server.audio.modes.world_vt import autotune_world_vt  # noqa: F401

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
)


def apply_breathiness(
    audio: np.ndarray,
    sr: int,
    amount: float = 1.0,
    hf_bias: float = 0.0,
    hf_crossover: float = 1500.0,
    hf_width: float = 3000.0,
    world_cache: dict = None,
) -> np.ndarray:
    """Apply WORLD aperiodicity shaping for breathiness control.

    amount:
      0.0 = cleaner than original, 1.0 = original, 5.0 = very breathy
    hf_bias:
      0.0 = uniform shaping, 1.0 = mainly high-frequency shaping
    """
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")
    if audio_arr.size == 0:
        return audio_arr

    amount_f = float(amount)
    if not np.isfinite(amount_f):
        amount_f = 1.0
    amount_f = float(np.clip(amount_f, 0.0, 5.0))

    # Exact no-op: skip WORLD analysis/synthesis entirely.
    if amount_f == 1.0:
        return audio_arr

    hf_bias_f = float(hf_bias)
    if not np.isfinite(hf_bias_f):
        hf_bias_f = 0.0
    hf_bias_f = float(np.clip(hf_bias_f, 0.0, 1.0))

    x64 = np.ascontiguousarray(audio_arr, dtype=np.float64)
    duration_s = float(x64.shape[0]) / float(sr)
    if duration_s < 0.1:
        return x64

    import pyworld as pw

    if world_cache and world_cache.get('sp') is not None:
        f0 = world_cache['f0'].copy()
        t = world_cache['timeaxis'].copy()
        sp = world_cache['sp'].copy()
        ap = world_cache['ap'].copy()
    else:
        f0, t = pw.harvest(x64, sr)
        sp = pw.cheaptrick(x64, f0, t, sr)
        ap = pw.d4c(x64, f0, t, sr)

    freq_bins = int(sp.shape[1])
    freq_axis = np.linspace(0.0, float(sr) / 2.0, freq_bins, dtype=np.float64)

    uniform = np.ones(freq_bins, dtype=np.float64)
    width = max(1.0, float(hf_width))
    ramp = np.clip((freq_axis - float(hf_crossover)) / width, 0.0, 1.0)
    bias = uniform * (1.0 - hf_bias_f) + ramp * hf_bias_f
    effective_amount = 1.0 + (amount_f - 1.0) * bias[np.newaxis, :]

    ap_modified = np.clip(ap ** (1.0 / effective_amount), 0.0, 1.0)
    y = pw.synthesize(f0, sp, ap_modified, sr)
    out = np.asarray(y[: len(audio_arr)], dtype=np.float64)

    return out
