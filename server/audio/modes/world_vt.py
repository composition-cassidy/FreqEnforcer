"""world_vt: WORLD soft retune plus pitch-adaptive vocal-tract envelope warp.

Also hosts the HNM synthesis path used by world_hnm (use_hnm=True).
"""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import (
    _apply_micro_rms_envelope,
    _repair_world_artifacts,
    _warp_spectral_envelope_fdep,
)
from server.audio.modes._world import (
    fill_unvoiced_f0,
    validate_world_input,
    voiced_masks,
    world_envelopes,
    world_f0,
)
from server.audio.modes.world_soft import soft_target_f0
from server.utils.note_utils import note_name_to_freq

NAME = "world_vt"
USES_WORLD_CACHE = True


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
    world_cache: dict = None,
    dilation_frames: int = 3,
    use_hnm: bool = False,
    return_f0: bool = False,
):
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

    return_f0: also return the synthesised F0 contour and its time axis (s);
        F0 is None when the audio is passed through.
    """
    import pyworld as pw

    audio_arr = validate_world_input(audio, sr)
    target_freq = float(note_name_to_freq(target_note))

    f0, time_axis = world_f0(audio_arr, sr, world_cache)
    voiced_mask, new_voiced_mask = voiced_masks(f0, voicing_mode, dilation_frames)
    analysis_f0 = fill_unvoiced_f0(f0, voiced_mask, target_freq)

    sp, ap = world_envelopes(audio_arr, analysis_f0, time_axis, sr)

    # --- F0 correction (same as WORLD Soft) ---
    new_f0 = soft_target_f0(analysis_f0, time_axis, new_voiced_mask, target_freq,
                            amount, retune_speed_ms, preserve_vibrato)
    if new_f0 is None:
        return (audio_arr, None, None) if return_f0 else audio_arr

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
        from server.audio.hnm_synth import hnm_synthesize
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
    return (output, new_f0, time_axis) if return_f0 else output


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None):
    return autotune_world_vt(
        audio,
        int(sr),
        str(settings["target_note"]),
        formant_shift_beta=float(settings.get("formant_shift_beta", 0.1)),
        crossover_freq=3000.0,
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        voicing_mode=settings.get("voicing_mode") or "strict",
        world_cache=world_cache,
        return_f0=True,
    )
