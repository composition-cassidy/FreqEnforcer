"""Sweep fixtures: deterministic synthetic signals with known ground truth,
plus the real WAVs in tests/fixtures/.

Every synthetic fixture is generated in memory (float32, 44.1 kHz, the
loader's internal rate) from a seed derived from its name, so worker
processes rebuild bit-identical copies without passing audio around.

Ground truth per fixture: true f0 / note, note onset and offset (seconds,
offset = end of the release fade), and whether a digital-silence tail follows
the note (needed for the ringing metric).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

import sweep_config as cfg

FADE_S = 0.010
NOTE_S = 1.0
TAIL_S = 0.5
NOISE_DB = -45.0          # "light noise", re tone RMS, gated with the note
HARM_FMAX = 16000.0


@dataclass
class Fixture:
    name: str
    audio: np.ndarray
    sr: int
    truth_f0: float
    truth_note: str
    onset_s: float
    offset_s: float
    has_tail: bool
    kind: str          # "synthetic" | "real"
    description: str


def _rng(name: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(name.encode()) & 0xFFFFFFFF)


def _note_freq(note: str) -> float:
    from server.utils.note_utils import note_name_to_freq
    return float(note_name_to_freq(note))


def _envelope(n: int, sr: int, fade_s: float = FADE_S) -> np.ndarray:
    env = np.ones(n, dtype=np.float64)
    nf = min(int(round(fade_s * sr)), n // 2)
    if nf > 0:
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
        env[:nf] = ramp
        env[n - nf:] = ramp[::-1]
    return env


def _additive(f0: float, n: int, sr: int, amp_fn, rng: np.random.Generator,
              cosine_phase: bool = False) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    out = np.zeros(n, dtype=np.float64)
    k_max = int(min(HARM_FMAX, 0.45 * sr) // f0)
    for k in range(1, k_max + 1):
        ph = 0.0 if cosine_phase else rng.uniform(0.0, 2.0 * np.pi)
        out += amp_fn(k) * np.cos(2.0 * np.pi * k * f0 * t + ph)
    return out


def _add_light_noise(x: np.ndarray, rng: np.random.Generator, db: float = NOISE_DB) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2)))
    return x + rng.standard_normal(x.size) * rms * 10.0 ** (db / 20.0)


def _place(note: np.ndarray, sr: int, lead_s: float, tail_s: float, peak: float = 0.5) -> np.ndarray:
    note = note / max(1e-12, float(np.max(np.abs(note)))) * peak
    parts = [np.zeros(int(round(lead_s * sr))), note, np.zeros(int(round(tail_s * sr)))]
    return np.concatenate(parts).astype(np.float32)


def _harmonic(name: str, note: str, lead_s: float = 0.0, note_s: float = NOTE_S,
              tail_s: float = TAIL_S, fade_s: float = FADE_S, desc: str = "",
              noise: bool = True) -> Fixture:
    sr = cfg.SR
    rng = _rng(name)
    f0 = _note_freq(note)
    n = int(round(note_s * sr))
    x = _additive(f0, n, sr, lambda k: 1.0 / k, rng)
    if noise:
        x = _add_light_noise(x, rng)
    x = x * _envelope(n, sr, fade_s)
    audio = _place(x, sr, lead_s, tail_s)
    return Fixture(name, audio, sr, f0, note, lead_s, lead_s + note_s, tail_s > 0.0,
                   "synthetic", desc or f"1/k harmonic tone at {note} ({f0:.2f} Hz), noise {NOISE_DB:.0f} dB")


def _resonator(x: np.ndarray, sr: int, freq: float, bw: float) -> np.ndarray:
    from scipy.signal import lfilter
    r = np.exp(-np.pi * bw / sr)
    theta = 2.0 * np.pi * freq / sr
    a = [1.0, -2.0 * r * np.cos(theta), r * r]
    return lfilter([1.0 - r], a, x)


def _vowel(name: str = "vowel_D3", note: str = "D3") -> Fixture:
    sr = cfg.SR
    rng = _rng(name)
    f0 = _note_freq(note)
    pre = int(0.1 * sr)                      # let the resonators settle before the note
    n = int(round(NOTE_S * sr))
    pulse = _additive(f0, n + pre, sr, lambda k: 1.0 / k, rng, cosine_phase=True)
    y = pulse
    for freq, bw in ((700.0, 80.0), (1220.0, 90.0), (2600.0, 120.0)):
        y = _resonator(y, sr, freq, bw)
    y = y[pre:]
    y = _add_light_noise(y, rng) * _envelope(n, sr)
    audio = _place(y, sr, 0.0, TAIL_S)
    return Fixture(name, audio, sr, f0, note, 0.0, NOTE_S, True, "synthetic",
                   f"band-limited pulse train at {note} ({f0:.2f} Hz) through /a/ formants 700/1220/2600 Hz")


def _breathy(name: str = "breathy_A3", note: str = "A3") -> Fixture:
    from scipy.signal import butter, lfilter
    sr = cfg.SR
    rng = _rng(name)
    f0 = _note_freq(note)
    n = int(round(NOTE_S * sr))
    t = np.arange(n, dtype=np.float64) / sr
    harm = _additive(f0, n, sr, lambda k: 1.0 / (k * k), rng)
    b, a = butter(2, 1000.0 / (sr / 2.0), btype="highpass")
    noise = lfilter(b, a, rng.standard_normal(n))
    # Aspiration bursts locked to the glottal period (real, periodic-in-envelope aperiodicity)
    mod = 0.3 + 0.7 * (0.5 + 0.5 * np.cos(2.0 * np.pi * f0 * t)) ** 4
    noise = noise * mod
    h_rms = float(np.sqrt(np.mean(harm ** 2)))
    n_rms = float(np.sqrt(np.mean(noise ** 2)))
    x = (harm + noise * (h_rms / n_rms) * 10.0 ** (-12.0 / 20.0)) * _envelope(n, sr)
    audio = _place(x, sr, 0.0, TAIL_S)
    return Fixture(name, audio, sr, f0, note, 0.0, NOTE_S, True, "synthetic",
                   f"1/k^2 harmonics at {note} ({f0:.2f} Hz) + pitch-synchronous aspiration noise (HP 1 kHz, -12 dB)")


def _real(fname: str) -> Fixture:
    from server.audio.loader import load_audio
    audio, sr, _ = load_audio(str(cfg.REAL_FIXTURE_DIR / fname))
    det = detected_pitch_for(fname, audio, sr)
    note = det["note_name"]
    f0 = _note_freq(note) if note else float("nan")
    dur = len(audio) / sr
    return Fixture(fname.rsplit(".", 1)[0], np.asarray(audio, dtype=np.float32), sr, f0, note,
                   0.0, dur, False, "real", f"tests/fixtures/{fname} (truth = detected note {note})")


REAL_FILES = ["test_2s_C4.wav", "test_10s_C4.wav", "test_10s_C4_Fs4_tuned.wav"]

_BUILDERS = {
    "harm_C2": lambda: _harmonic("harm_C2", "C2"),
    "harm_G3": lambda: _harmonic("harm_G3", "G3"),
    "harm_A4": lambda: _harmonic("harm_A4", "A4"),
    "harm_A5": lambda: _harmonic("harm_A5", "A5"),
    "vowel_D3": _vowel,
    "breathy_A3": _breathy,
    "short_C4": lambda: _harmonic("short_C4", "C4", note_s=0.15, tail_s=0.0, fade_s=0.005,
                                  desc="0.15 s 1/k harmonic tone at C4, no tail"),
    "lead_G3": lambda: _harmonic("lead_G3", "G3", lead_s=0.3,
                                 desc="300 ms digital silence + 1/k tone at G3 + tail"),
    # Cache-collision partners (not in the main sweep)
    "lead_A4": lambda: _harmonic("lead_A4", "A4", lead_s=0.3, note_s=0.7,
                                 desc="300 ms digital silence + 0.7 s tone at A4 (collision partner)"),
    "nolead_A4": lambda: _harmonic("nolead_A4", "A4", lead_s=0.0, note_s=0.7,
                                   desc="0.7 s tone at A4, no leading silence (collision control)"),
}
# Noise-free tones for the cleanliness-mask probe (bug 2)
for _n in ("C2", "G3", "A4"):
    _BUILDERS[f"pure_{_n}"] = (lambda n=_n: _harmonic(f"pure_{n}", n, noise=False,
                                                      desc=f"noise-free 1/k tone at {n}"))
for _f in REAL_FILES:
    _BUILDERS[_f.rsplit(".", 1)[0]] = (lambda f=_f: _real(f))

SWEEP_FIXTURES = ["harm_C2", "harm_G3", "harm_A4", "harm_A5", "vowel_D3", "breathy_A3",
                  "short_C4", "lead_G3"] + [f.rsplit(".", 1)[0] for f in REAL_FILES]
QUICK_FIXTURES = ["harm_G3", "lead_G3"]


@lru_cache(maxsize=None)
def get(name: str) -> Fixture:
    return _BUILDERS[name]()


_DETECTED: dict[str, dict] = {}


def detected_pitch_for(name: str, audio: np.ndarray, sr: int) -> dict:
    """state.detected_pitch exactly as /api/load-audio would set it."""
    if name not in _DETECTED:
        from server.audio.pitch_detector import get_pitch_summary
        from server.routes.audio import _detected_pitch_state
        _DETECTED[name] = _detected_pitch_state(get_pitch_summary(audio, sr, fast=False))
    return _DETECTED[name]


def detected(name: str) -> dict:
    fx = get(name)
    return detected_pitch_for(name if fx.kind == "synthetic" else name + ".wav", fx.audio, fx.sr)


def target_note(fx: Fixture, shift: int) -> str:
    from server.utils.note_utils import midi_to_note_name, note_name_to_midi
    return midi_to_note_name(note_name_to_midi(fx.truth_note) + int(shift))


def save_all(out_dir, names) -> None:
    import soundfile as sf
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        fx = get(name)
        if fx.kind == "synthetic":
            sf.write(str(out_dir / f"{name}.wav"), fx.audio, fx.sr, subtype="FLOAT")
