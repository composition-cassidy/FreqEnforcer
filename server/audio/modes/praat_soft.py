"""praat_soft: Praat PSOLA (parselmouth) with the shared soft-retune trajectory."""

from __future__ import annotations

import numpy as np

from server.audio.modes._retune import clamp_unit, retune_log2
from server.utils.note_utils import note_name_to_freq

NAME = "praat_soft"
USES_WORLD_CACHE = False


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
    return_f0: bool = False,
):
    """Praat PSOLA soft retune. With return_f0, returns (audio, corrected F0
    on Praat's time grid, times in s); F0 is None when the audio is passed
    through (no voiced frame)."""
    import sys

    def done(out, f0=None, times=None):
        return (out, f0, times) if return_f0 else out

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
        return done(audio_arr)

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
        return done(audio_arr)

    hop_s = float(ts)
    times = np.arange(xmin, xmax, hop_s, dtype=np.float64)
    if times.size < 3:
        return done(audio_arr)

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
        return done(audio_arr)

    amount_f = clamp_unit(amount)
    vib_f = clamp_unit(preserve_vibrato)

    target_freq = float(note_name_to_freq(target_note))
    target_x = float(np.log2(max(1e-6, target_freq)))

    x = np.full_like(f0, np.nan, dtype=np.float64)
    x[voiced] = np.log2(f0[voiced])

    # Unvoiced gaps are filled with the median so they don't poison the
    # vibrato-separating moving average.
    new_x = retune_log2(x, target_x, amount_f, vib_f, hop_s, retune_speed_ms,
                        slow_source=np.where(np.isfinite(x), x, np.nanmedian(x[voiced])))
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
    out_f0 = np.where(np.isfinite(new_f0) & (new_f0 > 0), new_f0, 0.0)
    if values.ndim == 2 and values.shape[0] >= 1:
        return done(values[0], out_f0, times)
    return done(np.asarray(values).reshape(-1), out_f0, times)


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None):
    return autotune_praat_soft_to_note(
        audio,
        int(sr),
        str(settings["target_note"]),
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        return_f0=True,
    )
