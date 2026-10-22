"""Server-side singleton state for FreqEnforcer."""

from __future__ import annotations

import threading
from typing import Optional
import numpy as np


class AppState:
    def __init__(self):
        self._lock = threading.Lock()

        self.original_audio: Optional[np.ndarray] = None   # float32 mono
        self.processed_audio: Optional[np.ndarray] = None  # float32 mono
        self.sample_rate: int = 44100
        self.detected_pitch: Optional[dict] = None          # freq_hz, note_name, cents
        self.harmonic_analysis: Optional[dict] = None
        self.source_path: str = ""
        self.processing_token: int = 0

        # Temp file cleanup: path of last written temp WAV
        self._last_temp_path: Optional[str] = None

        # Loop points for the current processed audio (None = no loop)
        self.loop_start: Optional[int] = None
        self.loop_end:   Optional[int] = None

        # Cached WORLD analysis of the loaded audio, reused by the WORLD
        # pitch modes across /process calls.
        self.world_cache: dict = {
            'audio_hash': None,
            'f0': None,
            'timeaxis': None,
            'sp': None,
            'ap': None,
            'sr': None,
        }

    def increment_token(self) -> int:
        with self._lock:
            self.processing_token += 1
            return self.processing_token

    def is_current_token(self, token: int) -> bool:
        with self._lock:
            return self.processing_token == token


# Module-level singleton
state = AppState()
