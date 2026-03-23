from __future__ import annotations

import numpy as np
import warnings
from pathlib import Path

try:
    from spartan_tuner.utils.note_utils import note_name_to_freq
except ImportError:
    from utils.note_utils import note_name_to_freq


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
    output = _repair_world_artifacts(output, sr,
                                     world_f0=new_f0, world_time_axis=time_axis)
    return output


def autotune_world_vt(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    formant_shift_beta: float = 0.1,
    crossover_freq: float = 3000.0,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    voicing_mode: str = "strict",
    dilation_frames: int = 3,
    use_hnm: bool = False,
) -> np.ndarray:
    """
    WORLD vocoder with pitch-adaptive vocal tract modeling.

    Same F0 correction pipeline as autotune_soft_to_note, but adds per-frame
    frequency-dependent spectral envelope warping:

        local_beta(f) = formant_shift_beta * max(0, 1 - f / crossover_freq)
        warp(f)       = (target_f0 / original_f0) ** local_beta(f)

    Warping strength decreases linearly with frequency, reaching zero at
    crossover_freq (default 3000 Hz).  This means:
        - F1/F2 shift partially with pitch (low frequencies, full beta effect)
        - F3 and above stay essentially fixed (above crossover)

    formant_shift_beta:
        0.0 -> formants stay fixed (identical to WORLD Soft)
        0.1 -> natural / anatomically-motivated (default, matches Vovious)
        0.5 -> exaggerated shift
        1.0 -> full shift at low frequencies
    """
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

    # --- F0 correction (same as WORLD Soft) ---
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

    # --- Frequency-dependent spectral envelope warping (NEW vs WORLD Soft) ---
    beta = max(0.0, min(1.0, float(formant_shift_beta)))
    xover = max(1.0, float(crossover_freq))

    if beta > 1e-9:
        new_sp = np.copy(sp)
        for i in range(len(f0)):
            orig_f0_i = float(f0[i])
            if orig_f0_i > 0 and new_f0[i] > 0:
                pitch_ratio = new_f0[i] / orig_f0_i
                # Skip warp when ratio is essentially 1.0 — avoid numerical drift
                if abs(pitch_ratio - 1.0) < 0.01:
                    continue
                # Adaptive floor: never inject energy below the frame's own minimum
                pos_vals = sp[i][sp[i] > 0]
                frame_floor = float(pos_vals.min()) if pos_vals.size > 0 else 1e-10
                new_sp[i] = np.maximum(
                    _warp_spectral_envelope_fdep(sp[i], pitch_ratio, sr, beta, xover),
                    frame_floor,
                )
    else:
        new_sp = sp

    if use_hnm:
        try:
            from spartan_tuner.audio.hnm_synth import hnm_synthesize
        except ImportError:
            from audio.hnm_synth import hnm_synthesize
        output = hnm_synthesize(new_f0, new_sp, ap, sr)
        # Transfer the original's micro-scale amplitude texture (shimmer,
        # glottal breathing, consonant micro-attacks) onto the HNM output.
        # Window ≈ one pitch period at 370 Hz; smoothing just suppresses
        # window-boundary clicks without blurring the texture.
        output = _apply_micro_rms_envelope(audio, output)
    else:
        output = pw.synthesize(new_f0, new_sp, ap, sr)
    output = _repair_world_artifacts(output, sr,
                                     world_f0=new_f0, world_time_axis=time_axis)
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


def _warp_spectral_envelope_fdep(
    sp_frame: np.ndarray,
    pitch_ratio: float,
    sr: int,
    beta: float,
    crossover_freq: float = 3000.0,
) -> np.ndarray:
    """
    Frequency-dependent spectral envelope warp.

    Warping strength decreases linearly from *beta* at 0 Hz to 0 at
    *crossover_freq*, so low formants (F1/F2) shift with pitch while
    high formants (F3 and above) stay fixed -- matching vocal-tract physics.

    For output bin k at frequency f_k:
        local_beta_k = beta * max(0, 1 - f_k / crossover_freq)
        src_index    = k / (pitch_ratio ** local_beta_k)
    """
    sp_arr = np.asarray(sp_frame, dtype=np.float64)
    n = len(sp_arr)
    if n <= 1:
        return sp_arr

    ratio_f = float(pitch_ratio)
    if not np.isfinite(ratio_f) or ratio_f <= 0.0:
        return sp_arr

    beta_f = float(beta)
    if beta_f <= 1e-9:
        return sp_arr

    xover = max(1.0, float(crossover_freq))
    bin_hz = (sr / 2.0) / (n - 1)               # Hz per bin

    k = np.arange(n, dtype=np.float64)
    freq_k = k * bin_hz                          # physical frequency of each bin
    local_beta = beta_f * np.maximum(0.0, 1.0 - freq_k / xover)
    local_warp = np.power(ratio_f, local_beta)   # vectorised; shape (n,)

    src_idx = k / local_warp
    src_idx = np.clip(src_idx, 0.0, n - 1.0)

    floor_idx = np.floor(src_idx).astype(int)
    ceil_idx  = np.minimum(floor_idx + 1, n - 1)
    weights   = src_idx - floor_idx

    warped = sp_arr[floor_idx] * (1.0 - weights) + sp_arr[ceil_idx] * weights
    return warped


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


def _repair_world_artifacts(
    audio: np.ndarray,
    sr: int,
    fft_size: int = 2048,
    hop: int = 512,
    freq_lo: float = 100.0,
    freq_hi: float = 3000.0,
    neighbor_radius: int = 3,
    roughness_threshold: float = 1.5,
    world_f0: "np.ndarray | None" = None,
    world_time_axis: "np.ndarray | None" = None,
) -> np.ndarray:
    """
    Post-process WORLD synthesis output to suppress spectral splotch artifacts.

    Strategy:
      1. STFT the output.
      2. Compute per-frame temporal spectral flux: RMS of how much each frame's
         dB magnitude in [freq_lo, freq_hi] deviates from its local neighborhood
         median (±neighbor_radius frames).  This discriminates splotch frames
         (which look different from their neighbours) from the normally high-
         variance harmonic structure (which is consistent across neighbours).
      3. Flag frames whose flux exceeds roughness_threshold * median_flux.
      4. Cluster filter: only repair if flux_ratio > 2x OR a neighbour is flagged.
      5. Voiced gate: if world_f0 is provided, skip repair on unvoiced STFT frames
         (AP=1 regions have naturally high spectral flux — not synthesis artifacts).
      6. Replace flagged voiced frames' magnitude with interpolation of nearest
         clean neighbours.  Phase is kept unchanged.
      7. ISTFT back.

    Applied conservatively: only the most obvious outliers are repaired.
    """
    from scipy.signal import stft, istft

    audio_in = np.asarray(audio, dtype=np.float64)
    if audio_in.size == 0:
        return audio_in

    # --- STFT ---
    f_ax, t_ax, Z = stft(audio_in, fs=sr,
                          nperseg=fft_size, noverlap=fft_size - hop,
                          window="hann", boundary="zeros", padded=True)
    # Z shape: (n_bins, n_frames)
    mag   = np.abs(Z)                              # (n_bins, n_frames)
    phase = np.angle(Z)                            # (n_bins, n_frames)
    n_frames = mag.shape[1]

    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-10))

    band = (f_ax >= freq_lo) & (f_ax <= freq_hi)
    if not band.any():
        return audio_in
    band_db = mag_db[band, :]                      # (n_band_bins, n_frames)

    # --- Temporal spectral flux: RMS deviation from local neighbourhood median ---
    radius = int(neighbor_radius)
    flux = np.zeros(n_frames, dtype=np.float64)
    for fi in range(n_frames):
        lo = max(0, fi - radius)
        hi = min(n_frames, fi + radius + 1)
        neighbours = [j for j in range(lo, hi) if j != fi]
        if not neighbours:
            flux[fi] = 0.0
            continue
        local_med_spectrum = np.median(band_db[:, neighbours], axis=1)  # (n_band_bins,)
        flux[fi] = float(np.sqrt(np.mean((band_db[:, fi] - local_med_spectrum) ** 2)))

    # --- Flag frames whose flux exceeds threshold * median_flux ---
    median_flux = float(np.median(flux))
    threshold = float(roughness_threshold)
    flagged = flux > threshold * max(median_flux, 1e-12)

    # --- Cluster filter: only repair if clearly anomalous OR part of a cluster ---
    # A flagged frame is repaired if:
    #   (a) flux_ratio > 2.0x median  (unambiguous outlier), OR
    #   (b) at least one immediate neighbour (±1) is also flagged
    # Isolated frames at 1.5–2.0x are likely false positives and are skipped.
    SOLO_PASS_RATIO = 2.0
    repair_mask = np.zeros(n_frames, dtype=bool)
    for fi in np.where(flagged)[0]:
        ratio_fi = flux[fi] / max(median_flux, 1e-12)
        has_neighbour = (
            (fi > 0          and flagged[fi - 1]) or
            (fi < n_frames-1 and flagged[fi + 1])
        )
        if ratio_fi > SOLO_PASS_RATIO or has_neighbour:
            repair_mask[fi] = True

    # --- Voiced gate: skip repair on unvoiced STFT frames ---
    # Diagnostic shows all detected "splotch" frames have AP max > 0.5; most are
    # fully unvoiced (f0=0).  High spectral flux in noise regions is natural texture,
    # not a synthesis artifact.  Only repair frames that WORLD considers voiced.
    if world_f0 is not None and world_time_axis is not None:
        wf0 = np.asarray(world_f0, dtype=np.float64)
        wt  = np.asarray(world_time_axis, dtype=np.float64)
        world_hop_s = float(wt[1] - wt[0]) if len(wt) > 1 else 0.005
        stft_t = np.arange(n_frames, dtype=np.float64) * (hop / float(sr))
        world_idx = np.clip(
            np.round(stft_t / max(world_hop_s, 1e-9)).astype(int),
            0, len(wf0) - 1,
        )
        voiced_stft = wf0[world_idx] > 0
        repair_mask &= voiced_stft

    n_to_repair = int(repair_mask.sum())
    if n_to_repair == 0:
        _, audio_out = istft(Z, fs=sr, nperseg=fft_size, noverlap=fft_size - hop,
                              window="hann", boundary="zeros")
        return audio_out[:len(audio_in)].astype(np.float64)

    # --- Repair: interpolate magnitude from nearest clean neighbors ---
    # "Clean" for interpolation purposes = not in repair_mask
    clean = ~repair_mask
    clean_idx = np.where(clean)[0]

    mag_repaired = mag.copy()
    for fi in np.where(repair_mask)[0]:
        before = clean_idx[clean_idx < fi]
        after  = clean_idx[clean_idx > fi]

        if before.size == 0 and after.size == 0:
            continue  # no clean neighbors at all — leave as-is
        elif before.size == 0:
            mag_repaired[:, fi] = mag[:, after[0]]
        elif after.size == 0:
            mag_repaired[:, fi] = mag[:, before[-1]]
        else:
            b, a = int(before[-1]), int(after[0])
            span = float(a - b)
            w_b  = (float(a) - float(fi)) / span   # weight of before frame
            w_a  = 1.0 - w_b
            mag_repaired[:, fi] = w_b * mag[:, b] + w_a * mag[:, a]

    # --- Reconstruct: repaired magnitude + original phase ---
    Z_repaired = mag_repaired * np.exp(1j * phase)
    _, audio_out = istft(Z_repaired, fs=sr, nperseg=fft_size, noverlap=fft_size - hop,
                          window="hann", boundary="zeros")
    audio_out = audio_out[:len(audio_in)].astype(np.float64)
    return audio_out


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


def _apply_rms_envelope(
    original: np.ndarray,
    synthesized: np.ndarray,
    frame_len: int = 1024,
    hop: int = 128,
    gain_min: float = 0.0,
    gain_max: float = 8.0,
    smooth_sigma: float = 3.0,
) -> np.ndarray:
    """Match the per-frame RMS envelope of *synthesized* to *original*.

    The sinusoidal model drops unvoiced content (fricatives, noise floor,
    weak harmonics below threshold), causing the output's dynamic shape to
    diverge from the input.  This post-processing step computes a smooth
    per-sample gain curve that brings the synthesized energy envelope back
    into alignment with the original.

    Algorithm:
      1. Compute windowed RMS of *original* and *synthesized* at *hop*-spaced
         frames using a Hann window of *frame_len* samples.
      2. Per-frame gain = orig_rms / (synth_rms + 1e-8), clipped to
         [gain_min, gain_max].
      3. Smooth the gain curve with a Gaussian (sigma = smooth_sigma frames).
      4. Reconstruct a per-sample gain via linear interpolation between frame
         centres and multiply into *synthesized*.

    Parameters
    ----------
    original : 1-D float64 array
        Original (pre-shift) audio.
    synthesized : 1-D float64 array
        Output of sine_model_synth (may differ slightly in length).
    frame_len : int
        RMS analysis frame length in samples.
    hop : int
        RMS analysis hop size in samples.
    gain_min, gain_max : float
        Gain clipping bounds (default 0–8×, i.e., 0 to +18 dB).
    smooth_sigma : float
        Gaussian smoothing sigma in frames.

    Returns
    -------
    corrected : 1-D float64 array, same length as *synthesized*.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal.windows import hann

    orig = np.asarray(original, dtype=np.float64)
    synth = np.asarray(synthesized, dtype=np.float64)

    # Work over the shorter of the two to avoid index errors
    n = min(len(orig), len(synth))
    if n < frame_len:
        # Audio too short to apply correction — return as-is
        return synth

    win = hann(frame_len, sym=True).astype(np.float64)
    win_rms = float(np.sqrt(np.mean(win ** 2)))  # normalise RMS by window energy

    # Pad both arrays so the last frame is complete
    n_frames = 1 + (n - frame_len) // hop
    orig_padded = np.pad(orig[:n], (0, frame_len), mode='constant')
    synth_padded = np.pad(synth[:n], (0, frame_len), mode='constant')

    orig_rms = np.zeros(n_frames, dtype=np.float64)
    synth_rms = np.zeros(n_frames, dtype=np.float64)
    centers = np.zeros(n_frames, dtype=np.float64)

    for i in range(n_frames):
        s = i * hop
        e = s + frame_len
        o_seg = orig_padded[s:e] * win
        sy_seg = synth_padded[s:e] * win
        orig_rms[i] = float(np.sqrt(np.mean(o_seg ** 2))) / (win_rms + 1e-12)
        synth_rms[i] = float(np.sqrt(np.mean(sy_seg ** 2))) / (win_rms + 1e-12)
        centers[i] = s + frame_len / 2.0

    gain = orig_rms / (synth_rms + 1e-8)
    gain = np.clip(gain, gain_min, gain_max)

    # Smooth the gain curve to avoid amplitude modulation artefacts
    gain_smooth = gaussian_filter1d(gain.astype(np.float64), sigma=smooth_sigma,
                                    mode='reflect')

    # Per-sample gain via linear interpolation between frame centres
    sample_indices = np.arange(len(synth), dtype=np.float64)
    per_sample_gain = np.interp(sample_indices, centers, gain_smooth,
                                left=gain_smooth[0], right=gain_smooth[-1])

    return synth * per_sample_gain


def _apply_micro_rms_envelope(
    original: np.ndarray,
    synthesized: np.ndarray,
    window_size: int = 128,
    hop: int = 64,
    gain_min: float = 0.0,
    gain_max: float = 4.0,
    smooth_sigma: float = 2.0,
) -> np.ndarray:
    """Transfer the original audio's micro-scale amplitude texture onto the synthesized output.

    The HNM synthesizer generates perfectly steady sinusoids shaped by
    CheapTrick's smoothed spectral envelope, which strips away the natural
    cycle-to-cycle energy fluctuations (shimmer, glottal breathiness, consonant
    micro-attacks) that make voice sound alive.  This function restores that
    texture by matching the RMS envelope at very fine resolution — one window
    per ~pitch period (~2.7 ms at 48 kHz) — so the synthesized output gains the
    original's dynamic "breathing" without affecting pitch or spectral shape.

    Algorithm mirrors _apply_rms_envelope() but at much shorter window/hop:
      1. Hann-windowed RMS of original and synthesized at hop-spaced frames.
      2. Per-frame gain = orig_rms / (synth_rms + eps), clipped to [gain_min, gain_max].
      3. Short Gaussian smooth (sigma=2 windows) to suppress window-boundary clicks.
      4. Per-sample linear interpolation then multiply into synthesized.

    Parameters
    ----------
    original : 1-D float64
        Original (pre-correction) audio.
    synthesized : 1-D float64
        HNM synthesizer output.
    window_size : int
        RMS window in samples (default 128 ≈ 2.7 ms at 48 kHz, ~1 pitch period
        at 370 Hz — keeps gain variation at sub-pitch-period resolution).
    hop : int
        Analysis hop in samples (default 64, 50% overlap).
    gain_min, gain_max : float
        Gain bounds (default 0–4× = 0 to +12 dB, conservative to avoid pumping).
    smooth_sigma : float
        Gaussian smoothing sigma in frames (default 2 ≈ 4 ms — just enough to
        eliminate window-boundary discontinuities without blurring the texture).

    Returns
    -------
    corrected : 1-D float64, same length as synthesized.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal.windows import hann

    orig = np.asarray(original, dtype=np.float64)
    synth = np.asarray(synthesized, dtype=np.float64)

    n = min(len(orig), len(synth))
    if n < window_size:
        return synth

    win = hann(window_size, sym=True).astype(np.float64)
    win_rms = float(np.sqrt(np.mean(win ** 2)))

    n_frames = 1 + (n - window_size) // hop
    orig_padded = np.pad(orig[:n], (0, window_size), mode='constant')
    synth_padded = np.pad(synth[:n], (0, window_size), mode='constant')

    orig_rms = np.zeros(n_frames, dtype=np.float64)
    synth_rms = np.zeros(n_frames, dtype=np.float64)
    centers = np.zeros(n_frames, dtype=np.float64)

    for i in range(n_frames):
        s = i * hop
        e = s + window_size
        orig_rms[i] = float(np.sqrt(np.mean((orig_padded[s:e] * win) ** 2))) / (win_rms + 1e-12)
        synth_rms[i] = float(np.sqrt(np.mean((synth_padded[s:e] * win) ** 2))) / (win_rms + 1e-12)
        centers[i] = s + window_size / 2.0

    gain = orig_rms / (synth_rms + 1e-8)
    gain = np.clip(gain, gain_min, gain_max)
    gain_smooth = gaussian_filter1d(gain, sigma=smooth_sigma, mode='reflect')

    sample_indices = np.arange(len(synth), dtype=np.float64)
    per_sample_gain = np.interp(sample_indices, centers, gain_smooth,
                                left=gain_smooth[0], right=gain_smooth[-1])

    return synth * per_sample_gain


def _apply_hf_rolloff(E: np.ndarray, sr: int, fft_size: int) -> np.ndarray:
    """
    Apply high-frequency rolloff to spectral envelope to match natural voice.

    Below 4kHz: flat (0 dB)
    4-8kHz: linear rolloff (-6 dB/octave)
    Above 8kHz: steep rolloff (-12 dB/octave)

    This prevents synthetic "sparkle" from harmonics extending to Nyquist.
    """
    n_bins = len(E)
    freqs = np.arange(n_bins, dtype=np.float64) * sr / fft_size
    rolloff = np.ones(n_bins, dtype=np.float64)

    # 4-8 kHz: -6 dB/octave rolloff
    mask_4_8 = (freqs >= 4000.0) & (freqs < 8000.0)
    if np.any(mask_4_8):
        octaves_from_4k = np.log2(freqs[mask_4_8] / 4000.0)
        rolloff[mask_4_8] = 10.0 ** (-6.0 * octaves_from_4k / 20.0)

    # Above 8 kHz: -12 dB/octave rolloff
    mask_above_8 = freqs >= 8000.0
    if np.any(mask_above_8):
        octaves_from_8k = np.log2(freqs[mask_above_8] / 8000.0)
        rolloff[mask_above_8] = 10.0 ** (-12.0 * octaves_from_8k / 20.0)

    return E * rolloff


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
    hop_size: int = 256,
    max_sines: int = 80,
    threshold_db: float = -80.0,
) -> np.ndarray:
    """
    Spectral Envelope + Excitation pitch correction.

    For each voiced STFT frame the algorithm is:
      1. Estimate the spectral envelope E[k] via cepstral smoothing of the
         original frame magnitude.  E[k] is a smooth function that covers
         EVERY FFT bin — it represents formants, not individual harmonics.
      2. Generate a Hann-windowed harmonic excitation signal: a sum of
         unit-amplitude cosines at TARGET_F0 * 1, 2, 3 ... up to Nyquist,
         with per-harmonic phase accumulators for continuity across frames.
      3. Take the rfft of the excitation → Exc[k].
      4. Output spectrum = E[k] * exp(j * angle(Exc[k])).
         * E[k] gives FULL spectral density — smooth, non-zero at every bin,
           shaped like the vocal tract formants.  No hollow gaps.
         * angle(Exc[k]) encodes the target pitch via harmonic phase
           structure; the Hann window causes sinc-like spectral spreading
           so the phase is well-defined between harmonics too.
      5. ISTFT overlap-add over all frames.
      6. RMS envelope correction to match the original dynamics.

    Unvoiced frames (no pYIN detection within ±1.5 hops) pass through
    unmodified directly in the STFT domain.
    """
    from audio.sinusoidal import estimate_spectral_envelope
    from audio.pitch_detector import detect_pitch
    from scipy.signal import stft, istft

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
    nyquist     = sr / 2.0

    # ── pYIN F0 detection ─────────────────────────────────────────────────
    det      = detect_pitch(audio_arr, sr=sr, fast=False)
    f0_array = np.asarray(det["f0_array"], dtype=np.float64)
    f0_times = np.asarray(det["times"],    dtype=np.float64)

    if f0_array.size == 0 or not np.any(np.isfinite(f0_array)):
        return audio_arr  # fully unvoiced — pass through

    # ── STFT analysis ─────────────────────────────────────────────────────
    noverlap = fft_size - hop_size
    _, stft_times, Zxx = stft(
        audio_arr, sr,
        window='hann', nperseg=fft_size, noverlap=noverlap,
        boundary='zeros', padded=True,
    )
    # Zxx: complex, shape (n_bins, n_frames);  n_bins = fft_size//2+1
    n_bins, n_frames = Zxx.shape

    # ── Interpolate F0 onto the STFT frame grid ───────────────────────────
    voiced_mask = np.isfinite(f0_array) & (f0_array > 50.0)
    if np.sum(voiced_mask) < 2:
        return audio_arr

    # Extend stft_times to cover all frames (stft may return fewer times
    # than frame columns due to boundary handling)
    if len(stft_times) < n_frames:
        stft_times = np.arange(n_frames) * hop_size / sr

    f0_voiced_vals = f0_array[voiced_mask]
    f0_interp = np.interp(
        stft_times,
        f0_times[voiced_mask],
        f0_voiced_vals,
        left=float(f0_voiced_vals[0]),    # hold first voiced value leftward
        right=float(f0_voiced_vals[-1]),  # hold last voiced value rightward
    )
    # f0_interp is now always a plausible F0 (no zeros), so log2 stays in
    # a sane range and the vibrato-separation moving average can't be
    # contaminated by log2(0) = -inf spikes at unvoiced gaps.

    # ── Voiced-frame gate ─────────────────────────────────────────────────
    # A frame is voiced if pYIN has a real detection within ±1.5 hops.
    voiced_frames = np.zeros(n_frames, dtype=bool)
    t_voiced      = f0_times[voiced_mask]
    tol           = 1.5 * hop_size / sr
    for i in range(n_frames):
        voiced_frames[i] = np.any(np.abs(t_voiced - stft_times[i]) <= tol)

    # ── Soft retune: exponential smoothing in log2 space ─────────────────
    hop_s    = hop_size / sr
    target_x = np.log2(max(1e-6, target_freq))
    x        = np.log2(np.maximum(f0_interp, 1e-6))

    vib_window_frames = max(3, int(round(0.12 / hop_s)))
    x_slow   = _moving_average(x, vib_window_frames)
    x_fast   = x - x_slow
    x_desired = x_slow + amount_f * (target_x - x_slow)

    tau = float(retune_speed_ms) / 1000.0
    if np.isfinite(tau) and tau > 0:
        alpha = float(np.exp(-hop_s / max(1e-6, tau)))
        alpha = max(0.0, min(0.9999, alpha))
    else:
        alpha = 0.0

    y = x_desired.copy()
    for i in range(1, len(y)):
        y[i] = alpha * y[i - 1] + (1.0 - alpha) * y[i]

    new_x            = y + vib_f * x_fast
    ratio_per_frame  = np.power(2.0, new_x - x)          # shape (n_frames,)
    f0_target_frames = f0_interp * ratio_per_frame        # shape (n_frames,)

    # ── Per-frame spectral resampling pitch shift ─────────────────────────
    # For each voiced frame we RELOCATE the original spectral content to the
    # target pitch rather than generating new cosine excitation.
    #
    # For output bin k (at frequency k*sr/fft_size), we sample the ORIGINAL
    # complex STFT spectrum at input bin k/ratio (where ratio = f0_tgt/f0_orig).
    # This shifts every frequency component — harmonics AND inter-harmonic
    # noise/breath — proportionally to the new pitch.
    #
    # The phase at each output bin comes directly from the original signal,
    # preserving the natural waveform complexity (glottal pulse shape, jitter,
    # shimmer) instead of synthetic cosine phases.
    #
    # The magnitude is replaced by the cepstral spectral envelope E[k] to
    # decouple pitch from formants: harmonics move, formants stay.

    formant_ratio = (2.0 ** (float(formant_shift_cents) / 1200.0)
                     if formant_shift_cents != 0 else 1.0)

    out_bins = np.arange(n_bins, dtype=np.float64)   # [0, 1, ..., n_bins-1]
    Zout     = Zxx.copy()   # unvoiced frames stay exactly as original

    # ── Phase vocoder accumulators ────────────────────────────────────────
    # expected_advance[k]: how much bin k's phase should advance per hop if
    # the signal were a pure tone exactly at that bin's centre frequency.
    # This is 2π * (k * sr/fft_size) * hop_size/sr = 2π * k * hop/fft_size.
    expected_advance = 2.0 * np.pi * out_bins * hop_size / fft_size

    # phase_accum[k]: running output phase per bin, propagated across frames.
    phase_accum    = np.zeros(n_bins, dtype=np.float64)
    # X_shifted_prev: resampled spectrum from the previous voiced frame,
    # needed to measure the frame-to-frame phase advance in the source signal.
    X_shifted_prev = np.zeros(n_bins, dtype=np.complex128)
    first_voiced   = True   # seed the accumulator on the first voiced frame

    for i in range(n_frames):
        ratio = ratio_per_frame[i] if i < len(ratio_per_frame) else 1.0

        if not voiced_frames[i] or ratio <= 0.0 or not np.isfinite(ratio):
            # Unvoiced — pass through; refresh the prev-frame reference so
            # the PV doesn't see a stale phase when voice resumes.
            X_shifted_prev = Zxx[:, i].copy()
            first_voiced   = True   # treat next voiced frame as a fresh start
            continue

        X = Zxx[:, i]   # original complex spectrum, shape (n_bins,)

        # ── 1. Spectral envelope E[k] from original frame ─────────────
        # Cepstral smoothing (order 150) gives a smooth formant envelope that
        # covers every bin — full spectral density, no hollow gaps.
        A    = np.abs(X)
        A_db = 20.0 * np.log10(np.maximum(A, 1e-10))
        E_db = estimate_spectral_envelope(A_db, sr, cepstral_order=150)
        E    = 10.0 ** (E_db / 20.0)

        # Natural HF rolloff: real voice energy drops sharply above ~5-8 kHz
        E = _apply_hf_rolloff(E, sr, fft_size)

        # Normalise so output frame has the same spectral energy as the input
        E_power = float(np.mean(E ** 2))
        A_power = float(np.mean(A ** 2))
        if E_power > 0.0:
            E = E * np.sqrt(A_power / E_power)

        # Optional independent formant shift
        if formant_shift_cents != 0:
            E = np.interp(out_bins / formant_ratio, out_bins, E,
                          left=0.0, right=0.0)

        # ── 2. Resample original complex spectrum to target pitch ──────
        # in_bins[k] = k / ratio  — the input bin whose frequency maps to
        # output frequency k*sr/fft_size after the pitch-ratio scaling.
        in_bins   = out_bins / ratio
        X_re      = np.interp(in_bins, out_bins, np.real(X), left=0.0, right=0.0)
        X_im      = np.interp(in_bins, out_bins, np.imag(X), left=0.0, right=0.0)
        X_shifted = X_re + 1j * X_im

        # ── 3. Phase vocoder phase propagation ────────────────────────
        # Measure how much the resampled spectrum's phase actually advanced
        # since the last frame, subtract the expected advance to get the
        # instantaneous deviation (true frequency offset), then integrate
        # into the output accumulator.  This makes consecutive output frames
        # phase-coherent at each bin's true frequency — no ISTFT smearing.
        if first_voiced:
            # Seed: start accumulator at the resampled signal's own phase so
            # the first output frame is anchored to the real signal.
            phase_accum = np.angle(X_shifted).copy()
            first_voiced = False
        else:
            actual_advance  = np.angle(X_shifted) - np.angle(X_shifted_prev)
            deviation       = np.angle(np.exp(1j * (actual_advance - expected_advance)))
            inst_freq       = expected_advance + deviation
            phase_accum    += inst_freq

        X_shifted_prev = X_shifted.copy()

        # ── 4. Output = envelope magnitude × propagated phase ─────────
        Zout[:, i] = E * np.exp(1j * phase_accum)

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

    # ── Debug: log RMS ratio ──────────────────────────────────────────────
    orig_rms = float(np.sqrt(np.mean(audio_arr ** 2)))
    out_rms  = float(np.sqrt(np.mean(output ** 2)))
    rms_ratio = out_rms / (orig_rms + 1e-10)
    print(f"[sine_spectral] Output RMS: {out_rms:.5f} | Input RMS: {orig_rms:.5f} | Ratio: {rms_ratio:.4f}")

    return output


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for autotune_stft_pitchshift (v12: zero-padded FFT, Lanczos-3,
# improved cepstral envelope, V/UV blending)
# ──────────────────────────────────────────────────────────────────────────────

def _zp_stft(audio: np.ndarray, window_size: int, fft_size: int,
             hop_size: int) -> np.ndarray:
    """Zero-padded STFT.  Uses a *window_size*-sample Hann window but
    computes an *fft_size*-point FFT (zero-padded), giving 4x frequency
    oversampling when fft_size == 4 * window_size."""
    from numpy.lib.stride_tricks import sliding_window_view
    window = 0.5 - 0.5 * np.cos(
        2.0 * np.pi * np.arange(window_size) / window_size)
    chunks = sliding_window_view(audio, window_size)[::hop_size]  # (F, W)
    windowed = chunks * window[np.newaxis, :]
    return np.fft.rfft(windowed, n=fft_size, axis=-1, norm='forward')


def _zp_istft(frames: np.ndarray, window_size: int, fft_size: int,
              hop_size: int) -> np.ndarray:
    """Inverse of :func:`_zp_stft`.  IRFFT to *fft_size* samples, keep only
    the first *window_size*, apply synthesis window, overlap-add."""
    n_frames = len(frames)
    # Zero DC and Nyquist (same as library)
    frames = frames.copy()
    frames[:, 0] = 0
    frames[:, -1] = 0

    time_frames = np.fft.irfft(frames, n=fft_size, axis=-1, norm='forward')
    time_frames = time_frames[:, :window_size]          # discard zero-pad tail

    window = 0.5 - 0.5 * np.cos(
        2.0 * np.pi * np.arange(window_size) / window_size)
    W = window * hop_size / np.sum(window * window)
    time_frames *= W[np.newaxis, :]

    out_len = n_frames * hop_size + window_size
    output = np.zeros(out_len, dtype=np.float64)
    for i in range(n_frames):
        s = i * hop_size
        output[s:s + window_size] += time_frames[i]
    return output


def _lanczos3_resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Lanczos-3 (6-tap windowed sinc) spectral resampling.

    Given an input spectrum *x* of length *n*, produces an output of the same
    length where the first ``min(n, int(n*factor))`` bins are filled via
    Lanczos-3 interpolation and the rest are zero.
    """
    if factor == 1.0:
        return x.copy()

    n = len(x)
    m = int(n * factor)
    valid = min(n, m)
    q = n / m                               # step through input per output bin

    y = np.zeros(n, dtype=x.dtype)
    positions = np.arange(valid, dtype=np.float64) * q   # (valid,)

    base = np.floor(positions).astype(np.intp)           # (valid,)
    offsets = np.arange(-2, 4)                           # 6 taps

    # tap_indices (valid, 6) — clamped to [0, n-1]
    tap_idx = base[:, None] + offsets[None, :]
    tap_idx = np.clip(tap_idx, 0, n - 1)

    # distances from each tap to the ideal position
    d = positions[:, None] - (base[:, None] + offsets[None, :].astype(np.float64))

    # Lanczos-3 kernel
    weights = np.zeros_like(d)
    near_zero = np.abs(d) < 1e-7
    in_range = (~near_zero) & (np.abs(d) < 3.0)

    weights[near_zero] = 1.0
    pi_d = np.pi * d[in_range]
    pi_d3 = np.pi * d[in_range] / 3.0
    weights[in_range] = (
        3.0 * np.sin(pi_d) * np.sin(pi_d3) / (np.pi * np.pi * d[in_range] ** 2)
    )

    values = x[tap_idx]                    # (valid, 6)
    y[:valid] = np.sum(values * weights, axis=1)
    return y


def _improved_lifter(mag: np.ndarray, f0_per_frame: np.ndarray | None,
                     sr: int) -> np.ndarray:
    """Cepstral envelope estimation with three improvements over the library:

    a) Magnitude floor before log (prevents cepstral corruption from tiny bins).
    b) Hamming-windowed lifter instead of hard rectangular cutoff (removes Gibbs
       ringing in the envelope).
    c) Adaptive cepstral order: ``quefrency = round(sr / (2.5 * f0))`` so the
       lifter tracks the harmonic spacing; fall back to ``round(0.001 * sr)``
       when f0 is unknown.

    Args:
        mag:            (n_frames, n_bins) magnitude array (linear, positive).
        f0_per_frame:   (n_frames,) detected F0 in Hz; NaN/0 for unvoiced.
        sr:             Sample rate.

    Returns:
        envelopes:      (n_frames, n_bins) smooth spectral envelopes (linear).
    """
    n_frames, n_bins = mag.shape
    envelopes = np.zeros_like(mag)
    default_q = int(round(0.001 * sr))     # 1 ms fallback

    for i in range(n_frames):
        frame_mag = mag[i]

        # (a) floor before log — at least -80 dB below peak
        peak = np.max(np.abs(frame_mag))
        floor_val = max(peak * 1e-4, 1e-30)
        log_mag = np.log(np.maximum(np.abs(frame_mag), floor_val))

        # (c) adaptive quefrency
        f0_i = 0.0 if f0_per_frame is None else float(f0_per_frame[i])
        if np.isfinite(f0_i) and f0_i > 50.0:
            q = int(round(sr / (2.5 * f0_i)))
        else:
            q = default_q
        q = max(4, min(q, n_bins // 2))

        # cepstrum
        cepstrum = np.fft.irfft(log_mag, norm='forward')

        # (b) Hamming-windowed lifter (instead of rectangular)
        hamming = np.hamming(2 * q + 1)
        lifter_win = np.zeros(len(cepstrum))
        apply_len = min(q + 1, len(cepstrum))
        # right half of Hamming (indices q..2q mapped to cepstrum 0..q)
        lifter_win[:apply_len] = hamming[q:q + apply_len]
        envelopes[i] = np.exp(np.real(np.fft.rfft(
            cepstrum * lifter_win, norm='forward')))

    return envelopes


def autotune_stft_pitchshift(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    amount: float = 1.0,
    retune_speed_ms: float = 40.0,
    preserve_vibrato: float = 1.0,
    preserve_formants: bool = True,
    formant_shift_cents: int = 0,
    window_size: int = 1024,
    fft_size: int = 4096,
    hop_size: int = 256,
) -> np.ndarray:
    """Per-frame STFT phase vocoder pitch correction (v12).

    v12 improvements over v11:
      - Zero-padded FFT: 1024-sample Hann window, 4096-point FFT gives 4x
        frequency oversampling so harmonics span 8-16 bins and interpolation
        preserves valley depth.
      - Lanczos-3 resampler (6-tap windowed sinc) instead of 2-tap linear.
      - Improved cepstral formant preservation: magnitude floor, Hamming-
        windowed lifter, adaptive quefrency based on per-frame F0.
      - Voiced/unvoiced transition blending using pYIN voicing probability
        with sigmoid crossfade (eliminates clicks at word boundaries).
    """
    from stftpitchshift.vocoder import encode, decode
    from audio.pitch_detector import detect_pitch

    audio_arr = np.asarray(audio, dtype=np.float64)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono 1D array")
    if len(audio_arr) < int(0.1 * sr):
        raise ValueError("Audio is too short (min 0.1 s)")
    if sr <= 0:
        raise ValueError("sr must be positive")

    orig_len    = len(audio_arr)
    target_freq = float(note_name_to_freq(target_note))
    amount_f    = float(np.clip(amount, 0.0, 1.0))
    vib_f       = float(np.clip(preserve_vibrato, 0.0, 1.0))

    # ── pYIN F0 detection ─────────────────────────────────────────────────
    det           = detect_pitch(audio_arr.astype(np.float32), sr=sr, fast=False)
    f0_array      = np.asarray(det["f0_array"], dtype=np.float64)
    f0_times      = np.asarray(det["times"],    dtype=np.float64)
    voiced_probs  = np.asarray(det.get("voiced_probs",
                               np.zeros_like(f0_array)), dtype=np.float64)

    voiced_mask = np.isfinite(f0_array) & (f0_array > 50.0)
    if np.sum(voiced_mask) < 2:
        return audio_arr

    # ── Zero-padded STFT ──────────────────────────────────────────────────
    audio_f32 = audio_arr.astype(np.float32)
    frames = _zp_stft(audio_f32, window_size, fft_size, hop_size)
    n_frames, n_bins = frames.shape

    stft_times = (np.arange(n_frames) * hop_size + window_size / 2.0) / sr

    # ── Interpolate F0 + voicing probability onto STFT frame grid ─────────
    f0_voiced_vals = f0_array[voiced_mask]
    f0_interp = np.interp(
        stft_times,
        f0_times[voiced_mask], f0_voiced_vals,
        left=float(f0_voiced_vals[0]),
        right=float(f0_voiced_vals[-1]),
    )

    # Voicing confidence per STFT frame (Fix 4)
    vp_interp = np.interp(stft_times, f0_times, voiced_probs,
                           left=0.0, right=0.0)

    # Smooth voicing probability with exponential filter (~10 ms)
    vp_alpha = max(0.0, min(0.999, float(np.exp(
        -(hop_size / sr) / max(1e-6, 0.010)))))
    vp_smooth = vp_interp.copy()
    for i in range(1, len(vp_smooth)):
        vp_smooth[i] = vp_alpha * vp_smooth[i - 1] + (1.0 - vp_alpha) * vp_smooth[i]
    # Sigmoid gate: sharp transition around 0.5
    blend = 1.0 / (1.0 + np.exp(-15.0 * (vp_smooth - 0.5)))  # (n_frames,)

    # ── Per-frame ratio computation (mirrors autotune_soft_to_note) ───────
    hop_s    = hop_size / sr
    target_x = np.log2(max(1e-6, target_freq))
    x        = np.log2(np.maximum(f0_interp, 1e-6))

    vib_window_frames = max(3, int(round(0.12 / hop_s)))
    x_slow    = _moving_average(x, vib_window_frames)
    x_fast    = x - x_slow
    x_desired = x_slow + amount_f * (target_x - x_slow)

    tau = float(retune_speed_ms) / 1000.0
    if np.isfinite(tau) and tau > 0:
        alpha = max(0.0, min(0.9999, float(np.exp(-hop_s / max(1e-6, tau)))))
    else:
        alpha = 0.0

    y = x_desired.copy()
    for i in range(1, len(y)):
        y[i] = alpha * y[i - 1] + (1.0 - alpha) * y[i]

    new_x           = y + vib_f * x_fast
    ratio_per_frame = np.power(2.0, new_x - x)

    # ── Encode: complex STFT -> (magnitude, instantaneous frequency) ──────
    frames = encode(frames, fft_size, hop_size, sr)

    # ── Improved cepstral formant preservation (Fix 3) ────────────────────
    envelopes: np.ndarray | None = None
    env_bad:   np.ndarray | None = None

    if preserve_formants:
        envelopes = _improved_lifter(frames.real, f0_interp, sr)
        env_bad = np.isinf(envelopes) | np.isnan(envelopes) | (
            np.abs(envelopes) < np.finfo(np.float32).tiny)
        frames.real /= np.where(env_bad, 1.0, envelopes)
        frames.real[env_bad] = 0.0

        if formant_shift_cents != 0:
            distortion = 2.0 ** (float(formant_shift_cents) / 1200.0)
            for i in range(n_frames):
                env_frame = envelopes[i].copy()
                env_frame[env_bad[i]] = 0.0
                envelopes[i] = _lanczos3_resample(env_frame, distortion)
            env_bad = np.isinf(envelopes) | np.isnan(envelopes) | (
                np.abs(envelopes) < np.finfo(np.float32).tiny)

    # ── Per-frame pitch shift (Lanczos-3 resampling, V/UV blending) ───────
    nyquist    = sr / 2.0
    mags_orig  = frames.real.copy()     # keep originals for V/UV blend
    freqs_orig = frames.imag.copy()
    mags_out   = mags_orig.copy()
    freqs_out  = freqs_orig.copy()

    for i in range(n_frames):
        b = blend[i]
        if b < 1e-4:
            continue                     # fully unvoiced — passthrough

        ratio = ratio_per_frame[i] if i < len(ratio_per_frame) else 1.0
        if not np.isfinite(ratio) or ratio <= 0.0 or abs(ratio - 1.0) < 1e-7:
            continue

        mag  = frames[i].real
        freq = frames[i].imag

        mag_s  = _lanczos3_resample(mag,  ratio)
        freq_s = _lanczos3_resample(freq, ratio) * ratio

        # Clamp (not zero) bins with invalid shifted frequency
        invalid = (freq_s <= 0.0) | (freq_s >= nyquist)
        mag_s[invalid]  = 0.0

        # V/UV blend (Fix 4): smooth crossfade instead of binary gate
        mags_out[i]  = b * mag_s  + (1.0 - b) * mags_orig[i]
        freqs_out[i] = b * freq_s + (1.0 - b) * freqs_orig[i]

    # ── Restore formant envelope ──────────────────────────────────────────
    if envelopes is not None and env_bad is not None:
        mags_out *= np.where(env_bad, 0.0, envelopes)

    frames_out = mags_out + 1j * freqs_out

    # ── Decode + ISTFT ────────────────────────────────────────────────────
    frames_out = decode(frames_out, fft_size, hop_size, sr)
    output     = _zp_istft(frames_out, window_size, fft_size, hop_size)

    # ── RMS correction ────────────────────────────────────────────────────
    output = _apply_rms_envelope(audio_arr, output,
                                 frame_len=2048, hop=512,
                                 gain_min=0.0, gain_max=8.0, smooth_sigma=2.0)

    orig_rms = float(np.sqrt(np.mean(audio_arr ** 2)))
    out_rms  = float(np.sqrt(np.mean(output  ** 2)))
    print(f"[stft_pitchshift v12] ZP-FFT {window_size}/{fft_size} Lanczos-3 | "
          f"RMS {orig_rms:.5f} -> {out_rms:.5f}  "
          f"(ratio {out_rms/(orig_rms+1e-10):.4f})")

    if len(output) >= orig_len:
        output = output[:orig_len]
    else:
        output = np.pad(output, (0, orig_len - len(output)))

    return output


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
