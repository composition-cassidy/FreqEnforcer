from __future__ import annotations

import numpy as np

import librosa

try:
    from spartan_tuner.utils.note_utils import (
        freq_to_midi,
        get_pitch_difference,
        midi_to_note_name,
        note_name_to_freq,
    )
except ImportError:
    from utils.note_utils import (
        freq_to_midi,
        get_pitch_difference,
        midi_to_note_name,
        note_name_to_freq,
    )


def detect_pitch(audio: np.ndarray, sr: int = 44100) -> dict:
    audio_arr = np.asarray(audio, dtype=np.float32)

    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")

    duration_s = float(audio_arr.shape[0]) / float(sr)
    if duration_s < 0.1:
        return {
            "f0_array": np.array([], dtype=np.float32),
            "times": np.array([], dtype=np.float32),
            "median_f0": None,
            "mean_f0": None,
            "voiced_ratio": 0.0,
        }

    f0, voiced_flag, voiced_probs = librosa.pyin(
        audio_arr,
        fmin=50.0,
        fmax=500.0,
        sr=sr,
        frame_length=2048,
    )

    times = librosa.times_like(f0, sr=sr)

    f0_arr = np.asarray(f0, dtype=np.float32)
    times_arr = np.asarray(times, dtype=np.float32)

    voiced_mask = np.isfinite(f0_arr)

    if f0_arr.size == 0:
        voiced_ratio = 0.0
    else:
        voiced_ratio = float(np.sum(voiced_mask)) / float(f0_arr.size)

    if np.any(voiced_mask):
        median_f0 = float(np.nanmedian(f0_arr))
        mean_f0 = float(np.nanmean(f0_arr))
    else:
        median_f0 = None
        mean_f0 = None

    return {
        "f0_array": f0_arr,
        "times": times_arr,
        "median_f0": median_f0,
        "mean_f0": mean_f0,
        "voiced_ratio": voiced_ratio,
    }


def get_predominant_pitch(audio: np.ndarray, sr: int = 44100) -> tuple[float | None, str | None, int | None]:
    result = detect_pitch(audio, sr=sr)

    freq_hz = result.get("median_f0")
    if freq_hz is None:
        return None, None, None

    midi = freq_to_midi(float(freq_hz))
    midi_rounded = int(round(midi))

    note_name = midi_to_note_name(midi_rounded)
    ref_freq = note_name_to_freq(note_name)

    _, cents = get_pitch_difference(float(freq_hz), float(ref_freq))

    return float(freq_hz), note_name, int(cents)


def get_target_frequency(note_name: str) -> float:
    return float(note_name_to_freq(note_name))
