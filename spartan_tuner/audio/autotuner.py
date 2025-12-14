from __future__ import annotations

import numpy as np
import warnings

try:
    from spartan_tuner.utils.note_utils import note_name_to_freq
except ImportError:
    from utils.note_utils import note_name_to_freq


warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
)


def autotune_to_note(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    preserve_formants: bool = True,
    voicing_mode: str = "force",
    dilation_frames: int = 3,
) -> np.ndarray:
    import pyworld as pw

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


def _moving_average(x: np.ndarray, n: int) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if n <= 1 or arr.size == 0:
        return arr
    w = int(n)
    pad_left = w // 2
    pad_right = w - 1 - pad_left
    padded = np.pad(arr, (pad_left, pad_right), mode="edge")
    kernel = np.ones((w,), dtype=np.float64) / float(w)
    return np.convolve(padded, kernel, mode="valid")


def autotune_soft_to_note(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    preserve_formants: bool = True,
    formant_shift_cents: int = 0,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    voicing_mode: str = "strict",
    dilation_frames: int = 3,
) -> np.ndarray:
    import pyworld as pw

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

    f0, time_axis = pw.dio(audio_arr, sr, f0_floor=50.0, f0_ceil=500.0)
    f0 = pw.stonemask(audio_arr, f0, time_axis, sr)

    voiced_mask = np.asarray(f0) > 0
    if voicing_mode == "strict":
        new_voiced_mask = voiced_mask
    elif voicing_mode == "force":
        new_voiced_mask = np.ones_like(voiced_mask, dtype=bool)
    elif voicing_mode == "dilate":
        new_voiced_mask = _dilate_voiced_mask(voiced_mask, int(dilation_frames))
    else:
        raise ValueError("voicing_mode must be one of: strict, force, dilate")

    analysis_f0 = f0
    if np.any(voiced_mask):
        idx = np.arange(len(f0), dtype=np.float64)
        voiced_idx = idx[voiced_mask]
        voiced_f0 = np.asarray(f0, dtype=np.float64)[voiced_mask]
        filled = np.interp(idx, voiced_idx, voiced_f0)
        analysis_f0 = filled.astype(np.float64, copy=False)
    else:
        analysis_f0 = np.full_like(f0, target_freq, dtype=np.float64)

    sp = pw.cheaptrick(audio_arr, analysis_f0, time_axis, sr)
    ap = pw.d4c(audio_arr, analysis_f0, time_axis, sr)

    amount_f = float(amount)
    if not np.isfinite(amount_f):
        amount_f = 1.0
    amount_f = max(0.0, min(1.0, amount_f))

    vib_f = float(preserve_vibrato)
    if not np.isfinite(vib_f):
        vib_f = 1.0
    vib_f = max(0.0, min(1.0, vib_f))

    try:
        hop_s = float(np.median(np.diff(np.asarray(time_axis, dtype=np.float64))))
        if not np.isfinite(hop_s) or hop_s <= 0:
            hop_s = 0.005
    except Exception:
        hop_s = 0.005

    x = np.full_like(analysis_f0, np.nan, dtype=np.float64)
    valid = np.asarray(analysis_f0) > 0
    x[valid] = np.log2(np.asarray(analysis_f0, dtype=np.float64)[valid])

    if not np.any(np.isfinite(x)):
        return audio_arr

    target_x = float(np.log2(max(1e-6, target_freq)))

    vib_window_s = 0.12
    vib_window_frames = max(3, int(round(vib_window_s / hop_s)))
    x_slow = _moving_average(np.asarray(x, dtype=np.float64), vib_window_frames)
    x_fast = np.asarray(x, dtype=np.float64) - x_slow

    x_desired = x_slow + amount_f * (target_x - x_slow)

    tau = float(retune_speed_ms) / 1000.0
    if not np.isfinite(tau) or tau <= 0:
        alpha = 0.0
    else:
        alpha = float(np.exp(-hop_s / max(1e-6, tau)))
        alpha = max(0.0, min(0.9999, alpha))

    y = np.asarray(x_desired, dtype=np.float64).copy()
    for i in range(1, int(y.size)):
        y[i] = alpha * y[i - 1] + (1.0 - alpha) * y[i]

    new_x = y + vib_f * x_fast
    new_f0 = np.power(2.0, new_x)

    new_f0 = np.where(np.asarray(new_voiced_mask, dtype=bool), new_f0, 0.0).astype(np.float64, copy=False)

    new_sp = sp

    if int(formant_shift_cents) != 0:
        formant_ratio = 2 ** (float(int(formant_shift_cents)) / 1200.0)
        new_sp = np.array([_shift_spectral_envelope(frame, formant_ratio) for frame in new_sp])

    output = pw.synthesize(new_f0, new_sp, ap, sr)
    return output


def autotune_praat_soft_to_note(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    time_step_s: float = 0.01,
    pitch_floor: float = 75.0,
    pitch_ceiling: float = 600.0,
) -> np.ndarray:
    import numpy as np
    import sys

    try:
        import parselmouth
        from parselmouth.praat import call
    except Exception as e:  # pragma: no cover
        py = sys.executable or "python"
        raise RuntimeError(
            "PSOLA (Praat) mode requires parselmouth. "
            f"Install into this Python: {py} -m pip install praat-parselmouth"
        ) from e

    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    audio_arr = np.asarray(audio_arr, dtype=np.float64)
    if audio_arr.size == 0:
        return audio_arr

    snd = parselmouth.Sound(audio_arr, sampling_frequency=float(sr))

    ts = float(time_step_s)
    ts = 0.01 if (not np.isfinite(ts) or ts <= 0.0) else ts

    pf = float(pitch_floor)
    pc = float(pitch_ceiling)
    if not np.isfinite(pf) or pf <= 0.0:
        pf = 75.0
    if not np.isfinite(pc) or pc <= pf:
        pc = max(pf + 50.0, 600.0)

    manip = call(snd, "To Manipulation", float(ts), float(pf), float(pc))
    tier = call(manip, "Extract pitch tier")

    xmin = float(snd.xmin)
    xmax = float(snd.xmax)
    if not np.isfinite(xmax) or not np.isfinite(xmin) or xmax <= xmin:
        return audio_arr

    hop_s = float(ts)
    times = np.arange(xmin, xmax, hop_s, dtype=np.float64)
    if times.size < 3:
        return audio_arr

    f0 = np.zeros_like(times, dtype=np.float64)
    voiced = np.zeros_like(times, dtype=bool)
    for i, t in enumerate(times.tolist()):
        try:
            v = float(call(tier, "Get value at time", float(t)))
        except Exception:
            v = 0.0
        if np.isfinite(v) and v > 0.0:
            f0[i] = v
            voiced[i] = True

    if not np.any(voiced):
        return audio_arr

    amount_f = float(amount)
    if not np.isfinite(amount_f):
        amount_f = 1.0
    amount_f = max(0.0, min(1.0, amount_f))

    vib_f = float(preserve_vibrato)
    if not np.isfinite(vib_f):
        vib_f = 1.0
    vib_f = max(0.0, min(1.0, vib_f))

    target_freq = float(note_name_to_freq(target_note))
    target_x = float(np.log2(max(1e-6, target_freq)))

    x = np.full_like(f0, np.nan, dtype=np.float64)
    x[voiced] = np.log2(f0[voiced])

    vib_window_s = 0.12
    vib_window_frames = max(3, int(round(vib_window_s / hop_s)))
    x_slow = _moving_average(np.where(np.isfinite(x), x, np.nanmedian(x[voiced])), vib_window_frames)
    x_fast = x - x_slow

    x_desired = x_slow + amount_f * (target_x - x_slow)

    tau = float(retune_speed_ms) / 1000.0
    if not np.isfinite(tau) or tau <= 0:
        alpha = 0.0
    else:
        alpha = float(np.exp(-hop_s / max(1e-6, tau)))
        alpha = max(0.0, min(0.9999, alpha))

    y = np.asarray(x_desired, dtype=np.float64).copy()
    for i in range(1, int(y.size)):
        y[i] = alpha * y[i - 1] + (1.0 - alpha) * y[i]

    new_x = y + vib_f * x_fast
    new_f0 = np.where(voiced, np.power(2.0, new_x), np.nan)

    new_tier = call("Create PitchTier", "corrected", float(xmin), float(xmax))
    for t, v in zip(times.tolist(), new_f0.tolist(), strict=False):
        if not np.isfinite(v) or v <= 0.0:
            continue
        try:
            call(new_tier, "Add point", float(t), float(v))
        except Exception:
            continue

    try:
        call([new_tier, manip], "Replace pitch tier")
    except Exception:
        call([new_tier, manip], "Replace pitch tier")

    out = call(manip, "Get resynthesis (overlap-add)")
    values = np.asarray(out.values, dtype=np.float64)
    if values.ndim == 2 and values.shape[0] >= 1:
        return values[0]
    return np.asarray(values).reshape(-1)


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
    import pyworld as pw

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
