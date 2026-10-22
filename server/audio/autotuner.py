"""Pitch correction entry points.

The pitch modes live in server/audio/modes/ (one module per mode behind a
common render() interface).  Their DSP functions are re-exported here so
existing callers keep working.  Breathiness lives in the WORLD modes
(server/audio/modes/_world.shape_aperiodicity).
"""

from __future__ import annotations

import warnings

from server.audio.modes._retune import moving_average as _moving_average  # noqa: F401
from server.audio.modes._world import dilate_voiced_mask as _dilate_voiced_mask  # noqa: F401
from server.audio.modes.praat_soft import autotune_praat_soft_to_note  # noqa: F401
from server.audio.modes.sine_spectral import autotune_sine_spectral  # noqa: F401
from server.audio.modes.stft_pitchshift import autotune_stft_pitchshift  # noqa: F401
from server.audio.modes.world_hard import autotune_to_note, autotune_with_formant_shift  # noqa: F401
from server.audio.modes.world_soft import autotune_soft_to_note  # noqa: F401
from server.audio.modes.world_vt import autotune_world_vt  # noqa: F401

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
)
