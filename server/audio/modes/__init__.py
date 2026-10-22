"""Pitch-correction modes.

Each mode lives in its own module with the same interface:

    NAME: str               the ``pitch_mode`` value accepted by /api/process
    USES_WORLD_CACHE: bool  whether render() reuses the pipeline's WORLD F0 cache
    render(audio, sr, settings, world_cache=None) -> np.ndarray
                            maps the /api/process settings dict onto the mode's
                            DSP function (which is also exported for direct use)

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
                      world_cache: dict | None = None) -> np.ndarray:
    return get_mode(pitch_mode).render(audio, sr, settings, world_cache=world_cache)
