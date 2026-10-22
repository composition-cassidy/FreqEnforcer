"""Pitch-correction modes.

Each mode lives in its own module with the same interface:

    NAME: str               the ``pitch_mode`` value accepted by /api/process
    USES_WORLD_CACHE: bool  whether render() reuses the pipeline's WORLD F0 cache
    render(audio, sr, settings, world_cache=None) -> (audio, f0, times)
                            maps the /api/process settings dict onto the mode's
                            DSP function (which is also exported for direct use)
                            and returns the output's F0 contour: the target
                            contour for hard modes, the corrected contour for
                            soft modes, in Hz with 0 on unvoiced frames, on the
                            input timeline (times in s).  f0/times are None
                            when the mode passed the audio through.

Shared helpers: _world (WORLD analysis + voicing strict/force/dilate),
_retune (soft-retune F0 trajectory), _dsp (spectral helpers).
"""

from __future__ import annotations

import numpy as np

from server.audio.modes import (
    praat_soft,
    sine_spectral,
    stft_pitchshift,
    world_hard,
    world_hnm,
    world_soft,
    world_vt,
)

MODES = {m.NAME: m for m in (world_hard, world_soft, world_vt, world_hnm,
                              praat_soft, sine_spectral, stft_pitchshift)}
DEFAULT_MODE = world_hard.NAME


def get_mode(pitch_mode: str):
    """Mode module for *pitch_mode*; unknown values fall back to world_hard."""
    return MODES.get(str(pitch_mode), MODES[DEFAULT_MODE])


def render_pitch_mode(pitch_mode: str, audio: np.ndarray, sr: int, settings: dict,
                      world_cache: dict | None = None):
    """(audio, output F0 contour or None, its times in s or None)."""
    out, f0, times = get_mode(pitch_mode).render(audio, sr, settings, world_cache=world_cache)
    if f0 is not None:
        f0 = np.asarray(f0, dtype=np.float64)
        times = np.asarray(times, dtype=np.float64)
    return out, f0, times
