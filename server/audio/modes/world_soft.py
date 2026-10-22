"""world_soft: WORLD vocoder with a soft retune (glide, amount, vibrato)."""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import _repair_world_artifacts, _shift_spectral_envelope
from server.audio.modes._retune import clamp_unit, retune_log2
from server.audio.modes._world import (
    fill_unvoiced_f0,
    shape_aperiodicity,
    validate_world_input,
    voiced_masks,
    world_envelopes,
    world_f0,
)
from server.utils.note_utils import note_name_to_freq

NAME = "world_soft"
USES_WORLD_CACHE = True


def world_hop_seconds(time_axis: np.ndarray) -> float:
    """Frame period of a WORLD time axis (5 ms if it cannot be determined)."""
    try:
        hop_s = float(np.median(np.diff(np.asarray(time_axis, dtype=np.float64))))
        if not np.isfinite(hop_s) or hop_s <= 0:
            hop_s = 0.005
    except Exception:
        hop_s = 0.005
    return hop_s


def soft_target_f0(analysis_f0, time_axis, new_voiced_mask, target_freq,
                   amount, retune_speed_ms, preserve_vibrato):
    """Soft-retuned F0 contour for WORLD synthesis (0 on unvoiced frames).

    Returns None when no frame has a usable F0 (caller passes audio through).
    """
    amount_f = clamp_unit(amount)
    vib_f = clamp_unit(preserve_vibrato)
    hop_s = world_hop_seconds(time_axis)

    x = np.full_like(analysis_f0, np.nan, dtype=np.float64)
    valid = np.asarray(analysis_f0) > 0
    x[valid] = np.log2(np.asarray(analysis_f0, dtype=np.float64)[valid])

    if not np.any(np.isfinite(x)):
        return None

    target_x = float(np.log2(max(1e-6, target_freq)))
    new_x = retune_log2(x, target_x, amount_f, vib_f, hop_s, retune_speed_ms)
    new_f0 = np.power(2.0, new_x)
    return np.where(np.asarray(new_voiced_mask, dtype=bool), new_f0, 0.0).astype(np.float64, copy=False)


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
    world_cache: dict = None,
    return_f0: bool = False,
    breathiness: float = 1.0,
    hf_bias: float = 0.0,
):
    """Soft-retuned WORLD resynthesis. With return_f0, returns
    (audio, synthesised F0, time axis in s); F0 is None when no frame had a
    usable F0 and the audio is passed through.  breathiness / hf_bias shape
    the aperiodicity before synthesis (shape_aperiodicity)."""
    import pyworld as pw

    audio_arr = validate_world_input(audio, sr)
    target_freq = float(note_name_to_freq(target_note))

    f0, time_axis = world_f0(audio_arr, sr, world_cache)
    voiced_mask, new_voiced_mask = voiced_masks(f0, voicing_mode, dilation_frames)
    analysis_f0 = fill_unvoiced_f0(f0, voiced_mask, target_freq)

    sp, ap = world_envelopes(audio_arr, analysis_f0, time_axis, sr)

    new_f0 = soft_target_f0(analysis_f0, time_axis, new_voiced_mask, target_freq,
                            amount, retune_speed_ms, preserve_vibrato)
    if new_f0 is None:
        return (audio_arr, None, None) if return_f0 else audio_arr

    new_sp = sp

    if int(formant_shift_cents) != 0:
        formant_ratio = 2 ** (float(int(formant_shift_cents)) / 1200.0)
        new_sp = np.array([_shift_spectral_envelope(frame, formant_ratio) for frame in new_sp])

    ap = shape_aperiodicity(ap, sr, breathiness, hf_bias)
    output = pw.synthesize(new_f0, new_sp, ap, sr)
    output = _repair_world_artifacts(output, sr,
                                     world_f0=new_f0, world_time_axis=time_axis)
    return (output, new_f0, time_axis) if return_f0 else output


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None):
    return autotune_soft_to_note(
        audio,
        int(sr),
        str(settings["target_note"]),
        preserve_formants=bool(settings.get("preserve_formants", True)),
        formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        voicing_mode=settings.get("voicing_mode") or "strict",
        world_cache=world_cache,
        return_f0=True,
        breathiness=float(settings.get("breathiness", 1.0)),
        hf_bias=float(settings.get("hf_bias", 0.0)),
    )
