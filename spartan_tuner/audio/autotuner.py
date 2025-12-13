from __future__ import annotations

import numpy as np
import pyworld as pw

try:
    from spartan_tuner.utils.note_utils import note_name_to_freq
except ImportError:
    from utils.note_utils import note_name_to_freq


def autotune_to_note(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    preserve_formants: bool = True,
    voicing_mode: str = "force",
    dilation_frames: int = 3,
) -> np.ndarray:
    """
    Flatten all pitched content in audio to a single target note.

    Args:
        audio: Input audio as float64 numpy array (IMPORTANT: pyworld needs float64)
        sr: Sample rate
        target_note: Target note name like "C4", "F#3", etc.
        preserve_formants: If True, keeps original voice character. If False, formants shift with pitch.

    Returns:
        Autotuned audio as float64 numpy array
    """
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    duration_s = float(audio_arr.shape[0]) / float(sr)
    if duration_s < 0.1:
        raise ValueError("Audio is too short for pyworld processing (min 0.1s)")

    # pyworld requires float64
    audio_arr = audio_arr.astype(np.float64, copy=False)

    # Get target frequency
    target_freq = float(note_name_to_freq(target_note))

    # Extract f0, spectral envelope, and aperiodicity
    # dio is the pitch extractor, stonemask refines it
    f0, time_axis = pw.dio(audio_arr, sr, f0_floor=50.0, f0_ceil=500.0)
    f0 = pw.stonemask(audio_arr, f0, time_axis, sr)  # refine f0

    voiced_mask = f0 > 0
    if voicing_mode == "strict":
        new_voiced_mask = voiced_mask
    elif voicing_mode == "force":
        new_voiced_mask = np.ones_like(voiced_mask, dtype=bool)
    elif voicing_mode == "dilate":
        new_voiced_mask = _dilate_voiced_mask(voiced_mask, int(dilation_frames))
    else:
        raise ValueError("voicing_mode must be one of: strict, force, dilate")

    analysis_f0 = f0
    if voicing_mode in ("force", "dilate"):
        if np.any(voiced_mask):
            idx = np.arange(len(f0), dtype=np.float64)
            voiced_idx = idx[voiced_mask]
            voiced_f0 = f0[voiced_mask]
            filled = np.interp(idx, voiced_idx, voiced_f0)
            analysis_f0 = filled.astype(np.float64, copy=False)
        else:
            analysis_f0 = np.full_like(f0, target_freq, dtype=np.float64)

    sp = pw.cheaptrick(audio_arr, analysis_f0, time_axis, sr)  # spectral envelope
    ap = pw.d4c(audio_arr, analysis_f0, time_axis, sr)  # aperiodicity

    # Create new f0 contour - flat line at target frequency
    # But only for voiced frames (where original f0 > 0)
    new_f0 = np.where(new_voiced_mask, target_freq, 0.0)

    if preserve_formants:
        # Keep spectral envelope as-is, voice character preserved
        new_sp = sp
    else:
        # Shift spectral envelope to match pitch change
        # This makes it sound more like pitch shifting than autotuning
        # Calculate ratio and shift formants
        # For each frame, if there was pitch, calculate the shift ratio
        new_sp = np.copy(sp)
        for i in range(len(f0)):
            if f0[i] > 0:
                ratio = target_freq / f0[i]
                # Interpolate spectral envelope to shift formants
                new_sp[i] = _shift_spectral_envelope(sp[i], float(ratio))

    # Resynthesize audio with new f0
    output = pw.synthesize(new_f0, new_sp, ap, sr)

    return output


def _shift_spectral_envelope(sp_frame: np.ndarray, ratio: float) -> np.ndarray:
    """
    Shift a single frame's spectral envelope by ratio.
    Used when preserve_formants is False.
    """
    ratio_f = float(ratio)
    if not np.isfinite(ratio_f) or ratio_f <= 0.0:
        return np.asarray(sp_frame)

    sp_arr = np.asarray(sp_frame)
    length = len(sp_arr)
    indices = np.arange(length) / ratio_f
    indices = np.clip(indices, 0, length - 1)

    # Linear interpolation
    floor_indices = np.floor(indices).astype(int)
    ceil_indices = np.minimum(floor_indices + 1, length - 1)
    weights = indices - floor_indices

    shifted = sp_arr[floor_indices] * (1 - weights) + sp_arr[ceil_indices] * weights
    return shifted


def _dilate_voiced_mask(voiced_mask: np.ndarray, dilation_frames: int) -> np.ndarray:
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


def autotune_with_formant_shift(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    formant_shift_cents: int = 0,
    voicing_mode: str = "force",
    dilation_frames: int = 3,
) -> np.ndarray:
    """
    Autotune to target note with optional formant shifting.

    Args:
        audio: Input audio as float64 numpy array
        sr: Sample rate
        target_note: Target note name like "C4"
        formant_shift_cents: Shift formants by this many cents (-500 to +500)
                            0 = no shift (preserve original formants)
                            Positive = brighter/smaller vocal tract
                            Negative = darker/larger vocal tract

    Returns:
        Autotuned audio as float64 numpy array
    """
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    duration_s = float(audio_arr.shape[0]) / float(sr)
    if duration_s < 0.1:
        raise ValueError("Audio is too short for pyworld processing (min 0.1s)")

    audio_arr = audio_arr.astype(np.float64, copy=False)
    target_freq = float(note_name_to_freq(target_note))

    # Extract components
    f0, time_axis = pw.dio(audio_arr, sr, f0_floor=50.0, f0_ceil=500.0)
    f0 = pw.stonemask(audio_arr, f0, time_axis, sr)

    voiced_mask = f0 > 0
    if voicing_mode == "strict":
        new_voiced_mask = voiced_mask
    elif voicing_mode == "force":
        new_voiced_mask = np.ones_like(voiced_mask, dtype=bool)
    elif voicing_mode == "dilate":
        new_voiced_mask = _dilate_voiced_mask(voiced_mask, int(dilation_frames))
    else:
        raise ValueError("voicing_mode must be one of: strict, force, dilate")

    analysis_f0 = f0
    if voicing_mode in ("force", "dilate"):
        if np.any(voiced_mask):
            idx = np.arange(len(f0), dtype=np.float64)
            voiced_idx = idx[voiced_mask]
            voiced_f0 = f0[voiced_mask]
            filled = np.interp(idx, voiced_idx, voiced_f0)
            analysis_f0 = filled.astype(np.float64, copy=False)
        else:
            analysis_f0 = np.full_like(f0, target_freq, dtype=np.float64)

    sp = pw.cheaptrick(audio_arr, analysis_f0, time_axis, sr)
    ap = pw.d4c(audio_arr, analysis_f0, time_axis, sr)

    # Flatten f0 to target
    new_f0 = np.where(new_voiced_mask, target_freq, 0.0)

    # Apply formant shift if requested
    if formant_shift_cents != 0:
        formant_ratio = 2 ** (float(formant_shift_cents) / 1200.0)
        new_sp = np.array([_shift_spectral_envelope(frame, formant_ratio) for frame in sp])
    else:
        new_sp = sp

    # Resynthesize
    output = pw.synthesize(new_f0, new_sp, ap, sr)

    return output
