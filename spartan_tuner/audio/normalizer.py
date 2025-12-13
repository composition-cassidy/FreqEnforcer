from __future__ import annotations

import numpy as np


def normalize_audio(audio: np.ndarray, target_db: float = -0.1) -> np.ndarray:
    """
    Peak normalize audio to target dB level.

    Args:
        audio: Input audio as numpy array
        target_db: Target peak level in dB. Default -0.1 to avoid clipping.
                   0.0 = absolute maximum, -3.0 = 3dB below max, etc.

    Returns:
        Normalized audio as numpy array (same dtype as input)
    """
    audio_arr = np.asarray(audio)

    current_peak = float(np.max(np.abs(audio_arr)))

    if current_peak < 1e-10:
        return audio_arr

    target_amplitude = 10 ** (float(target_db) / 20.0)

    gain = target_amplitude / current_peak

    normalized = audio_arr * gain

    return normalized.astype(audio_arr.dtype, copy=False)


def get_peak_db(audio: np.ndarray) -> float:
    """
    Get the peak level of audio in dB.

    Args:
        audio: Input audio as numpy array

    Returns:
        Peak level in dB (0.0 = maximum, negative values = below max)
    """
    peak = float(np.max(np.abs(np.asarray(audio))))
    if peak < 1e-10:
        return -np.inf
    return float(20.0 * np.log10(peak))


def get_rms_db(audio: np.ndarray) -> float:
    """
    Get the RMS (average) level of audio in dB.

    Args:
        audio: Input audio as numpy array

    Returns:
        RMS level in dB
    """
    audio_arr = np.asarray(audio)
    rms = float(np.sqrt(np.mean(audio_arr ** 2)))
    if rms < 1e-10:
        return -np.inf
    return float(20.0 * np.log10(rms))
