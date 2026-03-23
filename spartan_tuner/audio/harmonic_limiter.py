from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class HarmonicAnalysis:
    f0_hz: float
    harmonic_numbers: list[int]
    harmonic_freqs_hz: list[float]
    peak_db: list[float]
    rms_db: list[float]
    avg_spectrum_freq_hz: np.ndarray
    avg_spectrum_db: np.ndarray

    def to_dict(self) -> dict:
        return {
            "f0_hz": float(self.f0_hz),
            "harmonic_numbers": [int(v) for v in self.harmonic_numbers],
            "harmonic_freqs_hz": [float(v) for v in self.harmonic_freqs_hz],
            "peak_db": [float(v) for v in self.peak_db],
            "rms_db": [float(v) for v in self.rms_db],
            "avg_spectrum_freq_hz": self.avg_spectrum_freq_hz.astype(float).tolist(),
            "avg_spectrum_db": self.avg_spectrum_db.astype(float).tolist(),
        }


def _safe_db(x: np.ndarray, floor_db: float = -120.0) -> np.ndarray:
    floor_amp = float(10.0 ** (floor_db / 20.0))
    return 20.0 * np.log10(np.maximum(np.asarray(x, dtype=np.float64), floor_amp))


def _target_f0_from_note(target_note: str) -> float:
    note_names = {
        "C": 0,
        "C#": 1,
        "DB": 1,
        "D": 2,
        "D#": 3,
        "EB": 3,
        "E": 4,
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
    }
    s = str(target_note or "").strip().upper()
    if len(s) < 2:
        return 440.0
    octave = 4
    name = s[:-1]
    if s[-2:] and (s[-2] in "#B"):
        try:
            octave = int(s[-1])
            name = s[:-1]
        except Exception:
            try:
                octave = int(s[-2:])
                name = s[:-2]
            except Exception:
                octave = 4
    else:
        try:
            octave = int(s[-1])
            name = s[:-1]
        except Exception:
            octave = 4
    pc = int(note_names.get(name, 9))
    midi = (int(octave) + 1) * 12 + pc
    return float(440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0)))


def analyze_harmonics(
    audio: np.ndarray,
    sr: int,
    f0_hz: float,
    n_fft: int = 4096,
    hop_length: int = 1024,
    max_harmonics: int = 20,
    relative_floor_db: float = -60.0,
) -> HarmonicAnalysis:
    import librosa

    x = np.asarray(audio)
    if x.ndim != 1:
        raise ValueError("audio must be 1D mono")
    if x.size == 0:
        return HarmonicAnalysis(float(f0_hz), [], [], [], [], np.array([]), np.array([]))

    f0 = float(f0_hz)
    if (not np.isfinite(f0)) or f0 <= 0.0:
        f0 = 440.0

    stft = librosa.stft(
        np.asarray(x, dtype=np.float32, order="C"),
        n_fft=int(n_fft),
        hop_length=int(hop_length),
        window="hann",
        center=True,
    )
    mag = np.abs(stft)
    avg_mag = np.mean(mag, axis=1) if mag.size else np.zeros((int(n_fft // 2) + 1,), dtype=np.float64)
    avg_db = _safe_db(avg_mag)
    freqs = librosa.fft_frequencies(sr=int(sr), n_fft=int(n_fft))

    nyquist = float(sr) * 0.5
    max_by_nyquist = int(max(1, math.floor(nyquist / max(f0, 1e-6))))
    n_cap = int(max(1, min(int(max_harmonics), int(max_by_nyquist))))

    harmonic_numbers: list[int] = []
    harmonic_freqs_hz: list[float] = []
    peaks_db: list[float] = []
    rms_db: list[float] = []

    for k in range(1, n_cap + 1):
        fk = float(f0 * k)
        if fk >= nyquist:
            break
        center_bin = int(np.argmin(np.abs(freqs - fk)))
        lo = max(0, center_bin - 1)
        hi = min(mag.shape[0] - 1, center_bin + 1)
        local = mag[lo : hi + 1, :]
        if local.size == 0:
            continue
        per_frame_peak = np.max(local, axis=0)
        peak_lin = float(np.max(per_frame_peak))
        rms_lin = float(np.sqrt(np.mean(np.square(per_frame_peak))))
        harmonic_numbers.append(int(k))
        harmonic_freqs_hz.append(float(fk))
        peaks_db.append(float(_safe_db(np.asarray([peak_lin]))[0]))
        rms_db.append(float(_safe_db(np.asarray([rms_lin]))[0]))

    if harmonic_numbers:
        h1 = float(peaks_db[0])
        keep = 1
        for i, pk in enumerate(peaks_db):
            if float(pk) >= (h1 + float(relative_floor_db)):
                keep = i + 1
        keep = int(min(keep, int(max_harmonics)))
        harmonic_numbers = harmonic_numbers[:keep]
        harmonic_freqs_hz = harmonic_freqs_hz[:keep]
        peaks_db = peaks_db[:keep]
        rms_db = rms_db[:keep]

    return HarmonicAnalysis(
        f0_hz=float(f0),
        harmonic_numbers=harmonic_numbers,
        harmonic_freqs_hz=harmonic_freqs_hz,
        peak_db=peaks_db,
        rms_db=rms_db,
        avg_spectrum_freq_hz=np.asarray(freqs, dtype=np.float64),
        avg_spectrum_db=np.asarray(avg_db, dtype=np.float64),
    )


def apply_harmonic_limiting(
    audio: np.ndarray,
    sr: int,
    f0_hz: float,
    ceilings_db: dict[int, float],
    knee_db: float = 6.0,
    attack_ms: float = 1.0,
    release_ms: float = 50.0,
    n_fft: int = 4096,
    hop_length: int = 1024,
) -> np.ndarray:
    import librosa

    x = np.asarray(audio)
    if x.ndim != 1:
        raise ValueError("audio must be 1D mono")
    if x.size == 0:
        return x
    if not isinstance(ceilings_db, dict) or not ceilings_db:
        return x

    f0 = float(f0_hz)
    if (not np.isfinite(f0)) or f0 <= 0.0:
        return x

    stft = librosa.stft(
        np.asarray(x, dtype=np.float32, order="C"),
        n_fft=int(n_fft),
        hop_length=int(hop_length),
        window="hann",
        center=True,
    )
    mag = np.abs(stft).astype(np.float64, copy=False)
    phase = np.angle(stft)
    freqs = librosa.fft_frequencies(sr=int(sr), n_fft=int(n_fft))

    knee = float(max(0.0, knee_db))
    attack_frames = max(1e-6, (float(attack_ms) * 0.001 * float(sr)) / float(hop_length))
    release_frames = max(1e-6, (float(release_ms) * 0.001 * float(sr)) / float(hop_length))
    attack_coeff = float(np.exp(-1.0 / attack_frames))
    release_coeff = float(np.exp(-1.0 / release_frames))

    floor_amp = float(10.0 ** (-120.0 / 20.0))
    n_frames = int(mag.shape[1])
    state_db = {int(k): 0.0 for k in ceilings_db.keys()}

    for t in range(n_frames):
        for k_raw, ceiling_raw in ceilings_db.items():
            k = int(k_raw)
            if k <= 0:
                continue
            fk = float(f0 * k)
            if fk <= 0.0 or fk >= float(sr) * 0.5:
                continue
            center_bin = int(np.argmin(np.abs(freqs - fk)))
            lo = max(0, center_bin - 1)
            hi = min(mag.shape[0] - 1, center_bin + 1)
            bins = mag[lo : hi + 1, t]
            cur_db = float(_safe_db(np.asarray([float(np.max(bins))], dtype=np.float64))[0])
            ceiling_db = float(ceiling_raw)
            overshoot = float(cur_db - ceiling_db)

            if overshoot < -knee * 0.5:
                target_gr = 0.0
            elif overshoot < knee * 0.5:
                target_gr = float(((overshoot + knee * 0.5) ** 2) / max(1e-6, (2.0 * knee)))
            else:
                target_gr = float(max(0.0, overshoot))

            prev_gr = float(state_db.get(int(k), 0.0))
            if target_gr > prev_gr:
                smoothed = attack_coeff * prev_gr + (1.0 - attack_coeff) * target_gr
            else:
                smoothed = release_coeff * prev_gr + (1.0 - release_coeff) * target_gr
            state_db[int(k)] = float(smoothed)

            if smoothed <= 0.0:
                continue
            gain = float(10.0 ** (-smoothed / 20.0))
            mag[lo : hi + 1, t] *= gain

    mag = np.maximum(mag, floor_amp)
    out_stft = mag * np.exp(1j * phase)
    y = librosa.istft(out_stft, hop_length=int(hop_length), window="hann", center=True, length=int(x.shape[0]))
    return np.asarray(y, dtype=x.dtype)


def harmonic_f0_from_settings(settings: dict) -> float:
    if isinstance(settings, dict):
        target_note = settings.get("target_note")
        if target_note:
            try:
                return _target_f0_from_note(str(target_note))
            except Exception:
                pass
    return 440.0
