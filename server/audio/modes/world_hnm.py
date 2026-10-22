"""world_hnm: world_vt analysis/warp with Harmonic+Noise Model synthesis
(server/audio/hnm_synth.py) instead of WORLD's synthesizer."""

from __future__ import annotations

import numpy as np

from server.audio.modes.world_vt import autotune_world_vt

NAME = "world_hnm"
USES_WORLD_CACHE = True


def render(audio: np.ndarray, sr: int, settings: dict, world_cache: dict = None) -> np.ndarray:
    return autotune_world_vt(
        audio,
        int(sr),
        str(settings["target_note"]),
        use_hnm=True,
        formant_shift_beta=0.2,
        crossover_freq=3000.0,
        amount=float(settings.get("pitch_amount", 1.0)),
        retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
        preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        voicing_mode=settings.get("voicing_mode") or "strict",
        world_cache=world_cache,
    )
