from __future__ import annotations

import re

import numpy as np

_NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NAME_TO_PC = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}


def freq_to_midi(freq: float) -> float:
    freq_f = float(freq)
    if not np.isfinite(freq_f) or freq_f <= 0.0:
        raise ValueError("freq must be a positive finite number")
    return 69.0 + 12.0 * float(np.log2(freq_f / 440.0))


def midi_to_freq(midi: float) -> float:
    midi_f = float(midi)
    if not np.isfinite(midi_f):
        raise ValueError("midi must be a finite number")
    return 440.0 * float(2.0 ** ((midi_f - 69.0) / 12.0))


def midi_to_note_name(midi: int) -> str:
    m = int(midi)
    note = _NOTE_NAMES_SHARP[m % 12]
    octave = (m // 12) - 1
    return f"{note}{octave}"


_NOTE_RE = re.compile(r"^\s*([A-Ga-g])\s*([#bB]?)\s*(-?\d+)\s*$")


def note_name_to_midi(name: str) -> int:
    if not isinstance(name, str):
        raise ValueError("name must be a string")

    match = _NOTE_RE.match(name)
    if not match:
        raise ValueError(f"Invalid note name: {name}")

    letter, accidental, octave_str = match.groups()
    pitch = letter.upper() + accidental.upper()

    if pitch not in _NAME_TO_PC:
        raise ValueError(f"Invalid pitch class: {pitch}")

    octave = int(octave_str)
    pc = _NAME_TO_PC[pitch]

    return (octave + 1) * 12 + pc


def note_name_to_freq(name: str) -> float:
    return midi_to_freq(float(note_name_to_midi(name)))


def _round_half_away_from_zero(x: float) -> int:
    xf = float(x)
    if xf >= 0.0:
        return int(np.floor(xf + 0.5))
    return -int(np.floor(-xf + 0.5))


def get_pitch_difference(detected_freq: float, target_freq: float) -> tuple[int, int]:
    det = float(detected_freq)
    tgt = float(target_freq)

    if not np.isfinite(det) or not np.isfinite(tgt) or det <= 0.0 or tgt <= 0.0:
        raise ValueError("detected_freq and target_freq must be positive finite numbers")

    diff_semitones = 12.0 * float(np.log2(det / tgt))

    semitones = _round_half_away_from_zero(diff_semitones)
    cents_f = (diff_semitones - float(semitones)) * 100.0
    cents = _round_half_away_from_zero(cents_f)

    if cents < -50:
        semitones -= 1
        cents += 100
    elif cents > 50:
        semitones += 1
        cents -= 100

    return semitones, cents
