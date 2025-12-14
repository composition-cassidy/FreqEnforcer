from __future__ import annotations

from collections.abc import Callable
import sys

import numpy as np


class MissingDependencyError(RuntimeError):
    pass


StretchFn = Callable[[np.ndarray, int, float], np.ndarray]


def _as_mono_float(audio: np.ndarray) -> np.ndarray:
    audio_arr = np.asarray(audio)
    if audio_arr.ndim != 1:
        raise ValueError("audio must be a mono (1D) array")
    if audio_arr.size == 0:
        raise ValueError("audio must be non-empty")
    audio_arr = np.asarray(audio_arr, dtype=np.float32)
    if not np.all(np.isfinite(audio_arr)):
        raise ValueError("audio contains invalid (NaN/Inf) samples")
    return np.clip(audio_arr, -1.0, 1.0).astype(np.float32, copy=False)


def _audiotsm_stretch(audio: np.ndarray, sr: int, stretch_factor: float, procedure: str) -> np.ndarray:
    audio_arr = _as_mono_float(audio)
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    try:
        from audiotsm.io.array import ArrayReader, ArrayWriter
        import audiotsm
    except (ModuleNotFoundError, ImportError) as e:  # pragma: no cover
        if bool(getattr(sys, "frozen", False)):
            raise MissingDependencyError(
                "audiotsm is missing from this build. "
                "Reinstall a full release or rebuild the app with audiotsm included."
            ) from e

        py = sys.executable or "python"
        raise MissingDependencyError(
            "audiotsm is not installed for the Python running this app. "
            f"Python: {py}. Install with: {py} -m pip install audiotsm"
        ) from e

    factor = float(stretch_factor)
    if not np.isfinite(factor) or factor <= 0.0:
        raise ValueError("stretch_factor must be a positive finite number")

    speed = 1.0 / factor

    proc = str(procedure)
    if not hasattr(audiotsm, proc):
        raise ValueError(f"Unsupported audiotsm procedure: {proc}")

    tsm_factory = getattr(audiotsm, proc)
    tsm = tsm_factory(1, speed=float(speed))

    reader = ArrayReader(audio_arr[np.newaxis, :])
    writer = ArrayWriter(1)
    tsm.run(reader, writer)
    out = writer.data
    if out.ndim != 2 or out.shape[0] != 1:
        raise RuntimeError("Unexpected audiotsm output shape")
    return np.asarray(out[0], dtype=np.float32)


def audiotsm_wsola(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _audiotsm_stretch(audio, sr, stretch_factor, procedure="wsola")


def audiotsm_ola(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _audiotsm_stretch(audio, sr, stretch_factor, procedure="ola")


def audiotsm_phasevocoder(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _audiotsm_stretch(audio, sr, stretch_factor, procedure="phasevocoder")


def _pylibrb_import():
    try:
        from pylibrb import Option, RubberBandStretcher, create_audio_array

        return Option, RubberBandStretcher, create_audio_array
    except (ModuleNotFoundError, ImportError) as e:  # pragma: no cover
        if bool(getattr(sys, "frozen", False)):
            raise MissingDependencyError(
                "pylibrb is missing from this build. "
                "Reinstall a full release or rebuild the app with pylibrb included."
            ) from e

        py = sys.executable or "python"
        raise MissingDependencyError(
            "pylibrb is not installed for the Python running this app. "
            f"Python: {py}. Install with: {py} -m pip install pylibrb"
        ) from e


def _pylibrb_stretch(
    audio: np.ndarray,
    sr: int,
    stretch_factor: float,
    engine: str,
    preset: str,
) -> np.ndarray:
    audio_arr = _as_mono_float(audio)
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    factor = float(stretch_factor)
    if not np.isfinite(factor) or factor <= 0.0:
        raise ValueError("stretch_factor must be a positive finite number")

    Option, RubberBandStretcher, create_audio_array = _pylibrb_import()

    opts = 0

    if hasattr(Option, "PROCESS_OFFLINE"):
        opts |= int(Option.PROCESS_OFFLINE)
    elif hasattr(Option, "PROCESS_REALTIME"):
        opts |= int(Option.PROCESS_REALTIME)

    engine_attr = str(engine)
    if not hasattr(Option, engine_attr):
        raise RuntimeError(f"pylibrb.Option does not support engine {engine_attr}")

    opts |= int(getattr(Option, engine_attr))

    preset_attr = str(preset)
    if not hasattr(Option, preset_attr):
        raise RuntimeError(f"pylibrb.Option does not support preset {preset_attr}")

    opts |= int(getattr(Option, preset_attr))

    stretcher = RubberBandStretcher(
        sample_rate=int(sr),
        channels=1,
        options=opts,
        initial_time_ratio=float(factor),
    )

    block = 1024
    if hasattr(stretcher, "set_max_process_size"):
        stretcher.set_max_process_size(int(block))

    audio_in = create_audio_array(channels_num=1, samples_num=int(block))
    out_chunks: list[np.ndarray] = []

    i = 0
    n_total = int(audio_arr.shape[0])
    while i < n_total:
        n = min(block, n_total - i)
        audio_in[:] = 0
        audio_in[0, :n] = audio_arr[i : i + n]

        stretcher.process(audio_in)

        while stretcher.available():
            out_block = np.asarray(stretcher.retrieve_available())
            if out_block.ndim != 2 or out_block.shape[0] != 1:
                raise RuntimeError("Unexpected pylibrb output shape")
            out_chunks.append(np.asarray(out_block[0], dtype=np.float32))

        i += n

    if hasattr(stretcher, "finish"):
        stretcher.finish()

    while stretcher.available():
        out_block = np.asarray(stretcher.retrieve_available())
        if out_block.ndim != 2 or out_block.shape[0] != 1:
            raise RuntimeError("Unexpected pylibrb output shape")
        out_chunks.append(np.asarray(out_block[0], dtype=np.float32))

    if not out_chunks:
        return np.zeros((0,), dtype=np.float32)

    return _as_mono_float(np.concatenate(out_chunks, axis=0))


def rubberband_default_engine_faster(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _pylibrb_stretch(audio, sr, stretch_factor, engine="ENGINE_FASTER", preset="PRESET_DEFAULT")


def rubberband_default_engine_finer(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _pylibrb_stretch(audio, sr, stretch_factor, engine="ENGINE_FINER", preset="PRESET_DEFAULT")


def rubberband_percussive_engine_finer(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    return _pylibrb_stretch(audio, sr, stretch_factor, engine="ENGINE_FINER", preset="PRESET_PERCUSSIVE")


def tdpsola(audio: np.ndarray, sr: int, stretch_factor: float) -> np.ndarray:
    audio_arr = _as_mono_float(audio)
    if sr <= 0:
        raise ValueError("sr must be a positive integer")

    factor = float(stretch_factor)
    if not np.isfinite(factor) or factor <= 0.0:
        raise ValueError("stretch_factor must be a positive finite number")

    try:
        import librosa
    except Exception as e:  # pragma: no cover
        raise MissingDependencyError("librosa is required for TD-PSOLA") from e

    hop_length = int(round(float(sr) * 0.01))
    frame_length = 2048

    f0, _voiced_flag, _voiced_prob = librosa.pyin(
        audio_arr,
        fmin=50.0,
        fmax=500.0,
        sr=int(sr),
        frame_length=int(frame_length),
        hop_length=int(hop_length),
    )

    if f0 is None or len(f0) == 0:
        raise RuntimeError("Failed to estimate f0 for TD-PSOLA")

    voiced = np.asarray(f0)
    voiced = voiced[np.isfinite(voiced)]
    if voiced.size == 0:
        raise RuntimeError("No voiced frames detected for TD-PSOLA")

    f0_med = float(np.median(voiced))
    if not np.isfinite(f0_med) or f0_med <= 0.0:
        raise RuntimeError("Invalid f0 estimate for TD-PSOLA")

    period = int(round(float(sr) / f0_med))
    period = max(16, min(period, int(sr // 50)))

    win_length = int(2 * period)
    if win_length % 2 == 1:
        win_length += 1
    half = win_length // 2

    window = np.hanning(win_length).astype(np.float32)

    n_in = int(audio_arr.shape[0])
    n_out = int(round(float(n_in) * factor))
    output = np.zeros((n_out + win_length + 2,), dtype=np.float32)

    analysis_step = float(period) / float(factor)
    synthesis_step = int(period)

    k = 0
    while True:
        a_center = int(round(float(k) * analysis_step))
        s_center = int(k * synthesis_step)

        if a_center - half >= n_in:
            break
        if s_center - half >= n_out:
            break

        a0 = a_center - half
        a1 = a_center + half
        seg = np.zeros((win_length,), dtype=np.float32)
        src0 = max(0, a0)
        src1 = min(n_in, a1)
        if src1 > src0:
            seg[(src0 - a0) : (src1 - a0)] = audio_arr[src0:src1]
        seg *= window

        o0 = s_center - half
        o1 = s_center + half
        dst0 = max(0, o0)
        dst1 = min(output.shape[0], o1)
        if dst1 > dst0:
            output[dst0:dst1] += seg[(dst0 - o0) : (dst1 - o0)]

        k += 1

    output = output[:n_out]
    return _as_mono_float(output)


STRETCHERS: dict[str, StretchFn] = {
    "audiotsm_wsola": audiotsm_wsola,
    "audiotsm_ola": audiotsm_ola,
    "audiotsm_phasevocoder": audiotsm_phasevocoder,
    "rubberband_default_engine_faster": rubberband_default_engine_faster,
    "rubberband_default_engine_finer": rubberband_default_engine_finer,
    "rubberband_percussive_engine_finer": rubberband_percussive_engine_finer,
    "tdpsola": tdpsola,
}
