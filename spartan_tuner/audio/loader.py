from __future__ import annotations

from pathlib import Path
import struct

import numpy as np
import soundfile as sf

_INTERNAL_SR = 44100
_SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg"}


def load_audio(filepath: str) -> tuple[np.ndarray, int, int]:
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(str(path))

    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {ext}")

    try:
        audio, original_sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception as e:
        raise ValueError(f"Failed to read audio file: {path}") from e

    if audio is None or (hasattr(audio, "size") and audio.size == 0):
        raise ValueError(f"Empty audio file: {path}")

    if audio.ndim == 2:
        audio = np.mean(audio, axis=1, dtype=np.float32)

    audio = np.asarray(audio, dtype=np.float32)

    if original_sr <= 0:
        raise ValueError(f"Invalid sample rate in file: {path}")

    if original_sr != _INTERNAL_SR:
        try:
            import librosa
            audio = librosa.resample(y=audio, orig_sr=original_sr, target_sr=_INTERNAL_SR)
        except Exception as e:
            raise ValueError(f"Failed to resample audio: {path}") from e

    audio = np.asarray(audio, dtype=np.float32)

    if audio.size == 0:
        raise ValueError(f"Empty audio after processing: {path}")

    if not np.all(np.isfinite(audio)):
        raise ValueError(f"Audio contains invalid (NaN/Inf) samples: {path}")

    max_abs = float(np.max(np.abs(audio)))
    if np.isfinite(max_abs) and max_abs > 1.0:
        audio = (audio / max_abs).astype(np.float32, copy=False)
    else:
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32, copy=False)

    return audio, _INTERNAL_SR, int(original_sr)


def save_audio(filepath: str, audio: np.ndarray, sample_rate: int, bit_depth: int = 16):
    path = Path(filepath)

    if path.suffix.lower() != ".wav":
        raise ValueError("Only WAV export is supported for now")

    if bit_depth not in (16, 24):
        raise ValueError("bit_depth must be 16 or 24")

    if sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")

    audio_arr = np.asarray(audio, dtype=np.float32)

    if audio_arr.size == 0:
        raise ValueError("Cannot save empty audio")

    if audio_arr.ndim not in (1, 2):
        raise ValueError("audio must be a 1D (mono) or 2D (multi-channel) array")

    audio_arr = np.clip(audio_arr, -1.0, 1.0).astype(np.float32, copy=False)

    subtype = "PCM_16" if bit_depth == 16 else "PCM_24"

    try:
        sf.write(str(path), audio_arr, int(sample_rate), subtype=subtype, format="WAV")
    except RuntimeError as e:
        raise ValueError(f"Failed to write WAV file: {path}") from e


def set_wav_root_note(filepath: str, midi_note: int, sample_rate: int):
    path = Path(filepath)

    if path.suffix.lower() != ".wav":
        raise ValueError("Only WAV files are supported")

    midi = int(midi_note)
    if midi < 0 or midi > 127:
        raise ValueError("midi_note must be in range 0..127")

    sr = int(sample_rate)
    if sr <= 0:
        raise ValueError("sample_rate must be a positive integer")

    data = path.read_bytes()
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Not a valid RIFF/WAVE file")

    chunks: list[tuple[bytes, bytes]] = []
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + int(chunk_size)
        if end > len(data):
            break
        chunk_data = data[start:end]
        chunks.append((chunk_id, chunk_data))
        offset = end + (chunk_size & 1)

    sample_period = int(round(1_000_000_000.0 / float(sr)))

    smpl_data = struct.pack(
        "<9I",
        0,
        0,
        int(sample_period),
        midi,
        0,
        0,
        0,
        0,
        0,
    )

    inst_data = struct.pack(
        "<BbbBBBB",
        midi,
        0,
        0,
        0,
        127,
        1,
        127,
    )

    filtered = [(cid, cdata) for (cid, cdata) in chunks if cid not in (b"smpl", b"inst")]

    insert_at = None
    for i, (cid, _cdata) in enumerate(filtered):
        if cid == b"data":
            insert_at = i
            break
    if insert_at is None:
        insert_at = len(filtered)

    filtered[insert_at:insert_at] = [(b"smpl", smpl_data), (b"inst", inst_data)]

    out = bytearray()
    out += b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE"
    for cid, cdata in filtered:
        out += cid
        out += struct.pack("<I", len(cdata))
        out += cdata
        if len(cdata) & 1:
            out += b"\x00"

    struct.pack_into("<I", out, 4, len(out) - 8)
    path.write_bytes(out)
