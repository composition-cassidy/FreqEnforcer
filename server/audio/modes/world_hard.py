"""world_hard: WORLD vocoder, F0 flattened to the target note.

preserve_formants=True  -> autotune_to_note (envelope kept)
preserve_formants=False -> autotune_with_formant_shift (optional envelope shift)
"""

from __future__ import annotations

import numpy as np

from server.audio.modes._dsp import _shift_spectral_envelope
from server.audio.modes._world import (
    fill_unvoiced_f0,
    validate_world_input,
    voiced_masks,
    world_envelopes,
    world_f0,
)
from server.utils.note_utils import note_name_to_freq

NAME = "world_hard"
USES_WORLD_CACHE = True


def autotune_to_note(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    preserve_formants: bool = True,
    voicing_mode: str = "force",
    dilation_frames: int = 3,
    world_cache: dict = None,
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
    import pyworld as pw

    audio_arr = validate_world_input(audio, sr)
    target_freq = float(note_name_to_freq(target_note))

    f0, time_axis = world_f0(audio_arr, sr, world_cache)
    voiced_mask, new_voiced_mask = voiced_masks(f0, voicing_mode, dilation_frames)

    analysis_f0 = f0
    if voicing_mode in ("force", "dilate"):
        analysis_f0 = fill_unvoiced_f0(f0, voiced_mask, target_freq)

    sp, ap = world_envelopes(audio_arr, analysis_f0, time_axis, sr)

    # Flat F0 at the target, only on frames the voicing mode keeps voiced
    new_f0 = np.where(new_voiced_mask, target_freq, 0.0)

    if preserve_formants:
        # Keep spectral envelope as-is, voice character preserved
        new_sp = sp
    else:
        # Shift each voiced frame's envelope with the pitch change (sounds
        # more like a pitch shift than autotune)
        new_sp = np.copy(sp)
        for i in range(len(f0)):
            if f0[i] > 0:
                ratio = target_freq / f0[i]
                new_sp[i] = _shift_spectral_envelope(sp[i], float(ratio))

    return pw.synthesize(new_f0, new_sp, ap, sr)


def autotune_with_formant_shift(
    audio: np.ndarray,
    sr: int,
    target_note: str,
    formant_shift_cents: int = 0,
    voicing_mode: str = "force",
    dilation_frames: int = 3,
    world_cache: dict = None,
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
    import pyworld as pw

    audio_arr = validate_world_input(audio, sr)
    target_freq = float(note_name_to_freq(target_note))

    f0, time_axis = world_f0(audio_arr, sr, world_cache)
    voiced_mask, new_voiced_mask = voiced_masks(f0, voicing_mode, dilation_frames)

    analysis_f0 = f0
    if voicing_mode in ("force", "dilate"):
        analysis_f0 = fill_unvoiced_f0(f0, voiced_mask, target_freq)

    sp, ap = world_envelopes(audio_arr, analysis_f0, time_axis, sr)

    # Flatten f0 to target
    new_f0 = np.where(new_voiced_mask, target_freq, 0.0)

    if formant_shift_cents != 0:
        formant_ratio = 2 ** (float(formant_shift_cents) / 1200.0)
        new_sp = np.array([_shift_spectral_envelope(frame, formant_ratio) for frame in sp])
    else:
        new_sp = sp

    return pw.synthesize(new_f0, new_sp, ap, sr)


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None) -> np.ndarray:
    voicing = settings.get("voicing_mode") or "force"
    if settings.get("preserve_formants", True):
        return autotune_to_note(audio, sr, settings["target_note"],
                                preserve_formants=True, voicing_mode=voicing,
                                world_cache=world_cache)
    return autotune_with_formant_shift(
        audio, sr,
        settings["target_note"],
        settings.get("formant_shift_cents", 0),
        voicing_mode=voicing,
        world_cache=world_cache,
    )
