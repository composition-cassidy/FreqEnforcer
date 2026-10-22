"""WORLD analysis and voicing helpers shared by the world_* pitch modes."""

from __future__ import annotations

import numpy as np

VOICING_MODES = ("strict", "force", "dilate")


def validate_world_input(audio: np.ndarray, sr: int) -> np.ndarray:
    """Check mono / length constraints and return a float64 view for pyworld."""
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    duration_s = float(audio_arr.shape[0]) / float(sr)
    if duration_s < 0.1:
        raise ValueError("Audio is too short for pyworld processing (min 0.1s)")

    # pyworld requires float64
    return audio_arr.astype(np.float64, copy=False)


def world_f0(audio_arr: np.ndarray, sr: int, world_cache: dict | None = None):
    """DIO + StoneMask F0 and time axis, reusing the pipeline's cache when present."""
    import pyworld as pw

    if world_cache and world_cache.get('f0') is not None:
        f0 = world_cache['f0'].copy()
        time_axis = world_cache['timeaxis']
    else:
        f0, time_axis = pw.dio(audio_arr, sr, f0_floor=50.0, f0_ceil=500.0)
        f0 = pw.stonemask(audio_arr, f0, time_axis, sr)
    return f0, time_axis


def world_envelopes(audio_arr: np.ndarray, analysis_f0: np.ndarray, time_axis: np.ndarray,
                    sr: int):
    """CheapTrick spectral envelope and D4C aperiodicity for *analysis_f0*."""
    import pyworld as pw

    sp = pw.cheaptrick(audio_arr, analysis_f0, time_axis, sr)
    ap = pw.d4c(audio_arr, analysis_f0, time_axis, sr)
    return sp, ap


def dilate_voiced_mask(voiced_mask: np.ndarray, dilation_frames: int) -> np.ndarray:
    mask = np.asarray(voiced_mask, dtype=bool)
    n = mask.size
    if n == 0:
        return mask

    d = int(dilation_frames)
    if d <= 0:
        return mask

    out = np.copy(mask)
    voiced_idx = np.flatnonzero(mask)
    if voiced_idx.size == 0:
        return out

    for i in voiced_idx:
        start = 0 if i - d < 0 else i - d
        end = n if i + d + 1 > n else i + d + 1
        out[start:end] = True

    return out


def voiced_masks(f0: np.ndarray, voicing_mode: str, dilation_frames: int):
    """Return (analysis voiced mask, synthesis voiced mask) for *voicing_mode*.

    strict: synthesise only frames WORLD found voiced
    force:  synthesise every frame as voiced
    dilate: grow the voiced region by *dilation_frames* on each side
    """
    voiced_mask = np.asarray(f0) > 0
    if voicing_mode == "strict":
        new_voiced_mask = voiced_mask
    elif voicing_mode == "force":
        new_voiced_mask = np.ones_like(voiced_mask, dtype=bool)
    elif voicing_mode == "dilate":
        new_voiced_mask = dilate_voiced_mask(voiced_mask, int(dilation_frames))
    else:
        raise ValueError("voicing_mode must be one of: strict, force, dilate")
    return voiced_mask, new_voiced_mask


_EFFECTIVE_FLOOR = 1e-6


def shape_aperiodicity(ap: np.ndarray, sr: int, amount: float = 1.0, hf_bias: float = 0.0,
                       hf_crossover: float = 1500.0, hf_width: float = 3000.0) -> np.ndarray:
    """Breathiness: reshape a D4C aperiodicity matrix before synthesis.

    amount:  0 = fully periodic, 1 = unchanged, 5 = very breathy
    hf_bias: 0 = uniform, 1 = only above hf_crossover (ramping over hf_width)

    Per bin the exponent is 1 / effective with
    effective = 1 + (amount - 1) * bias, so ap ** (1 / effective) rises
    toward 1 (noise) for amount > 1 and falls toward 0 for amount < 1.  Where
    effective reaches 0 (amount 0, fully biased bins) the limit ap -> 0 is
    used directly instead of dividing by zero.  amount == 1 returns *ap*
    itself, so default settings leave the synthesis bit-identical.
    """
    amount_f = float(amount)
    if not np.isfinite(amount_f):
        amount_f = 1.0
    amount_f = float(np.clip(amount_f, 0.0, 5.0))
    if amount_f == 1.0:
        return ap
    bias_f = float(hf_bias)
    if not np.isfinite(bias_f):
        bias_f = 0.0
    bias_f = float(np.clip(bias_f, 0.0, 1.0))

    ap = np.asarray(ap, dtype=np.float64)
    freq_axis = np.linspace(0.0, float(sr) / 2.0, ap.shape[1], dtype=np.float64)
    ramp = np.clip((freq_axis - float(hf_crossover)) / max(1.0, float(hf_width)), 0.0, 1.0)
    bias = (1.0 - bias_f) + ramp * bias_f
    effective = 1.0 + (amount_f - 1.0) * bias
    periodic = effective < _EFFECTIVE_FLOOR
    exponent = 1.0 / np.where(periodic, 1.0, effective)
    shaped = np.power(np.clip(ap, 0.0, 1.0), exponent[np.newaxis, :])
    shaped[:, periodic] = 0.0
    return np.clip(shaped, 0.0, 1.0)


def fill_unvoiced_f0(f0: np.ndarray, voiced_mask: np.ndarray, target_freq: float) -> np.ndarray:
    """Interpolate F0 across unvoiced gaps; all-unvoiced input becomes *target_freq*."""
    if np.any(voiced_mask):
        idx = np.arange(len(f0), dtype=np.float64)
        voiced_idx = idx[voiced_mask]
        voiced_f0 = np.asarray(f0, dtype=np.float64)[voiced_mask]
        filled = np.interp(idx, voiced_idx, voiced_f0)
        return filled.astype(np.float64, copy=False)
    return np.full_like(f0, target_freq, dtype=np.float64)
