"""Golden render matrix for FreqEnforcer DSP regression tests.

Single source of truth shared by ``render_golden.py`` (writes references) and
``tests/test_regression.py`` (re-renders and compares).  DSP functions are
called directly, never via HTTP, with the same defaults ``_run_pipeline`` in
``server/routes/audio.py`` uses.

Nothing here changes DSP behaviour.  The only harness-side intervention is
seeding ``np.random`` before every render, because ``hnm_synth.py`` draws
unseeded random phases/noise.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"

# Same import roots the app has at runtime: repo root for ``server.*`` and
# ``server/`` for the bare ``audio.*`` imports used by sine_spectral/stft.
for _p in (str(ROOT / "server"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=r"pkg_resources is deprecated")

FIXTURES = ["test_2s_C4.wav", "test_10s_C4.wav", "test_10s_C4_Fs4_tuned.wav"]
SEMITONES = [-7, 5, 12]
VOICINGS = ["strict", "force", "dilate"]
RNG_SEED = 0

# Pitch-mode id -> (function name, fixed kwargs, takes voicing_mode)
PITCH_MODES: dict[str, tuple[str, dict, bool]] = {
    "world_hard": ("autotune_to_note", {"preserve_formants": True}, True),
    "world_formant": ("autotune_with_formant_shift", {"formant_shift_cents": 200}, True),
    "world_soft": ("autotune_soft_to_note", {
        "preserve_formants": True, "formant_shift_cents": 0, "amount": 1.0,
        "retune_speed_ms": 40.0, "preserve_vibrato": 1.0}, True),
    "world_vt": ("autotune_world_vt", {
        "formant_shift_beta": 0.1, "crossover_freq": 3000.0, "amount": 1.0,
        "retune_speed_ms": 40.0, "preserve_vibrato": 1.0}, True),
    "world_hnm": ("autotune_world_vt", {
        "use_hnm": True, "formant_shift_beta": 0.2, "crossover_freq": 3000.0,
        "amount": 1.0, "retune_speed_ms": 40.0, "preserve_vibrato": 1.0}, True),
    "praat_soft": ("autotune_praat_soft_to_note", {
        "amount": 1.0, "retune_speed_ms": 40.0, "preserve_vibrato": 1.0}, False),
    "sine_spectral": ("autotune_sine_spectral", {
        "amount": 1.0, "retune_speed_ms": 40.0, "preserve_vibrato": 1.0,
        "preserve_formants": True, "formant_shift_cents": 0}, False),
    "stft_pitchshift": ("autotune_stft_pitchshift", {
        "amount": 1.0, "retune_speed_ms": 40.0, "preserve_vibrato": 1.0,
        "preserve_formants": True, "formant_shift_cents": 0}, False),
}

# Full-pipeline cases (run through _run_pipeline) on the short fixture only.
PIPELINE_FIXTURE = "test_2s_C4.wav"
PIPELINE_SEMITONES = 5
PIPELINE_CASES: dict[str, dict] = {
    "pipe_clean": {"clean_lowcut_percent": 50.0, "cleanliness_percent": 50.0,
                   "clean_hf_rollback_percent": 50.0},
    "pipe_breath": {"breathiness": 2.0, "hf_bias": 0.5},
    "pipe_harmlim": {"harmonic_limiter_enabled": True,
                     "harmonic_ceiling_offsets_db": {2: -6.0, 3: -6.0, 5: -12.0}},
    "pipe_stretch_rb": {"stretch_factor": 1.5,
                        "stretch_method": "rubberband_default_engine_finer"},
    "pipe_stretch_tdpsola": {"stretch_factor": 1.5, "stretch_method": "tdpsola"},
    "pipe_normalize": {"normalize": True},
    "pipe_loop": {"_loop": True},
    # Route dispatch for every pitch_mode, plus branches the direct-call
    # matrix does not reach (formant shifts, preserve_formants=False, beta).
    "pipe_mode_world_hard_noformant": {"preserve_formants": False, "formant_shift_cents": 200},
    "pipe_mode_world_soft": {"pitch_mode": "world_soft"},
    "pipe_mode_world_soft_shift": {"pitch_mode": "world_soft", "formant_shift_cents": -150},
    "pipe_mode_world_vt": {"pitch_mode": "world_vt"},
    "pipe_mode_world_vt_beta": {"pitch_mode": "world_vt", "formant_shift_beta": 0.3,
                                "pitch_amount": 0.7, "retune_speed_ms": 80.0,
                                "preserve_vibrato": 0.5},
    "pipe_mode_world_hnm": {"pitch_mode": "world_hnm"},
    "pipe_mode_praat_soft": {"pitch_mode": "praat_soft"},
    "pipe_mode_sine_spectral": {"pitch_mode": "sine_spectral"},
    "pipe_mode_sine_spectral_shift": {"pitch_mode": "sine_spectral", "formant_shift_cents": 150},
    "pipe_mode_stft_pitchshift": {"pitch_mode": "stft_pitchshift"},
    "pipe_mode_stft_pitchshift_shift": {"pitch_mode": "stft_pitchshift", "formant_shift_cents": 150},
    "pipe_mode_stft_pitchshift_nopf": {"pitch_mode": "stft_pitchshift", "preserve_formants": False},
}

# ProcessRequest defaults from server/routes/audio.py
PIPELINE_DEFAULTS = {
    "pitch_mode": "world_hard", "pitch_amount": 1.0, "retune_speed_ms": 40.0,
    "preserve_vibrato": 1.0, "preserve_formants": True, "formant_shift_cents": 0,
    "formant_shift_beta": 0.1, "stretch_factor": 1.0, "stretch_method": "audiotsm_wsola",
    "clean_lowcut_percent": 0.0, "cleanliness_percent": 0.0,
    "clean_hf_rollback_percent": 0.0, "breathiness": 1.0, "hf_bias": 0.0,
    "harmonic_limiter_enabled": False, "harmonic_ceiling_offsets_db": {},
    "harmonic_knee_db": 6.0, "harmonic_release_ms": 50.0, "normalize": False,
}


@dataclass
class Case:
    id: str
    fixture: str
    mode: str
    voicing: str
    semitones: int
    target_note: str
    function: str
    params: dict = field(default_factory=dict)

    @property
    def rel_path(self) -> str:
        safe = self.target_note.replace("#", "s")
        return f"{Path(self.fixture).stem}/{self.mode}__{self.voicing}__{safe}.wav"


_audio_cache: dict[str, tuple[np.ndarray, int]] = {}
_pitch_cache: dict[str, tuple] = {}


def load_fixture(name: str) -> tuple[np.ndarray, int]:
    if name not in _audio_cache:
        from server.audio.loader import load_audio
        audio, sr, _ = load_audio(str(ROOT / name))
        _audio_cache[name] = (audio, sr)
    audio, sr = _audio_cache[name]
    return audio.copy(), sr


def detect_source(name: str) -> tuple:
    """(freq_hz, note_name, cents) as /api/load-audio would report it."""
    if name not in _pitch_cache:
        from server.audio.pitch_detector import get_predominant_pitch
        audio, sr = load_fixture(name)
        _pitch_cache[name] = get_predominant_pitch(audio, sr, fast=False)
    return _pitch_cache[name]


def transpose(note: str, semitones: int) -> str:
    from server.utils.note_utils import midi_to_note_name, note_name_to_midi
    return midi_to_note_name(note_name_to_midi(note) + int(semitones))


def build_cases() -> list[Case]:
    """Enumerate the full matrix from scratch (uses pitch detection)."""
    cases: list[Case] = []
    for fx in FIXTURES:
        src_note = detect_source(fx)[1]
        stem = Path(fx).stem
        for st in SEMITONES:
            tgt = transpose(src_note, st)
            for mode, (fn, kw, has_voicing) in PITCH_MODES.items():
                for v in (VOICINGS if has_voicing else ["na"]):
                    params = dict(kw)
                    if has_voicing:
                        params["voicing_mode"] = v
                    cases.append(Case(f"{stem}-{mode}-{v}-{tgt}", fx, mode, v, st, tgt, fn, params))
    src_note = detect_source(PIPELINE_FIXTURE)[1]
    tgt = transpose(src_note, PIPELINE_SEMITONES)
    stem = Path(PIPELINE_FIXTURE).stem
    for name, overrides in PIPELINE_CASES.items():
        params = {k: v for k, v in overrides.items()}
        cases.append(Case(f"{stem}-{name}-na-{tgt}", PIPELINE_FIXTURE, name, "na",
                          PIPELINE_SEMITONES, tgt, "_run_pipeline", params))
    return cases


def case_from_manifest(entry: dict) -> Case:
    params = dict(entry["params"])
    if "harmonic_ceiling_offsets_db" in params:
        params["harmonic_ceiling_offsets_db"] = {
            int(k): float(v) for k, v in params["harmonic_ceiling_offsets_db"].items()}
    return Case(entry["id"], entry["fixture"], entry["mode"], entry["voicing"],
                entry["semitones"], entry["target_note"], entry["function"], params)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_loop: asyncio.AbstractEventLoop | None = None


def _progress_loop() -> asyncio.AbstractEventLoop:
    """Background event loop that swallows _run_pipeline progress messages."""
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _render_pipeline(case: Case, audio: np.ndarray, sr: int) -> tuple[np.ndarray, dict]:
    from server.routes.audio import _run_pipeline
    from server.state import state

    params = dict(case.params)
    do_loop = params.pop("_loop", False)
    settings = dict(PIPELINE_DEFAULTS)
    settings.update(params)
    settings["target_note"] = case.target_note

    freq, note, cents = detect_source(case.fixture)
    state.detected_pitch = {"freq_hz": freq, "note_name": note, "cents": cents}
    state.world_cache = {"audio_hash": None}
    token = state.increment_token()

    result, _harm, _timings = _run_pipeline(audio, sr, settings, token, _progress_loop())
    extra: dict = {}
    if do_loop:
        from server.audio.loop_crossfade import process_with_loop
        from server.utils.note_utils import note_name_to_freq
        result, ls, le = process_with_loop(
            result, sr, f0_hz=float(note_name_to_freq(case.target_note)),
            template_periods=6, min_loop_periods=10, crossfade_periods=2)
        extra = {"loop_start": ls, "loop_end": le}
    return np.asarray(result), extra


def render(case: Case) -> tuple[np.ndarray, int, dict]:
    """Render one case. Returns (float64 audio, sr, extra metadata)."""
    from server.audio import autotuner

    audio, sr = load_fixture(case.fixture)
    np.random.seed(RNG_SEED)
    if case.function == "_run_pipeline":
        out, extra = _render_pipeline(case, audio, sr)
    else:
        fn: Callable = getattr(autotuner, case.function)
        out, extra = fn(audio, sr, case.target_note, **case.params), {}
    return np.asarray(out, dtype=np.float64).reshape(-1), sr, extra


def sha256_f32(audio: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(audio, dtype="<f4").tobytes()).hexdigest()


def measure(audio: np.ndarray, sr: int) -> dict:
    from server.audio.pitch_detector import get_predominant_pitch
    a32 = np.asarray(audio, dtype=np.float32)
    f0, note, cents = get_predominant_pitch(a32, sr, fast=False)
    return {
        "rms": float(np.sqrt(np.mean(np.square(a32, dtype=np.float64)))),
        "peak": float(np.max(np.abs(a32))) if a32.size else 0.0,
        "detected_f0": None if f0 is None else round(float(f0), 3),
        "detected_note": note,
        "detected_cents": cents,
    }
