"""Audio processing endpoints for FreqEnforcer."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import soundfile as sf
from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from server.state import state

router = APIRouter(prefix="/api")

# SSE progress queue (one slot — latest progress wins)
_progress_queue: asyncio.Queue = asyncio.Queue(maxsize=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WAVEFORM_BINS = 2000


def _compute_waveform_peaks(audio: np.ndarray) -> list[list[float]]:
    """Divide buffer into WAVEFORM_BINS bins and return [[min, max], ...] per bin."""
    n = len(audio)
    if n == 0:
        return []
    bin_size = max(1, n // WAVEFORM_BINS)
    peaks = []
    for i in range(WAVEFORM_BINS):
        start = i * bin_size
        end = min(start + bin_size, n)
        if start >= n:
            peaks.append([0.0, 0.0])
        else:
            chunk = audio[start:end]
            peaks.append([float(chunk.min()), float(chunk.max())])
    return peaks


def _peak_db(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-10:
        return -120.0
    return float(20.0 * np.log10(peak))


def _rms_db(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    if rms < 1e-10:
        return -120.0
    return float(20.0 * np.log10(rms))


def _audio_to_base64_wav(audio: np.ndarray, sr: int) -> str:
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _cleanup_last_temp():
    if state._last_temp_path:
        try:
            os.unlink(state._last_temp_path)
        except OSError:
            pass
        state._last_temp_path = None


def _push_progress(loop: asyncio.AbstractEventLoop, progress: float, stage: str):
    payload = {"progress": progress, "stage": stage}
    asyncio.run_coroutine_threadsafe(_progress_queue.put(payload), loop)


# ---------------------------------------------------------------------------
# DSP pipeline (mirrors ProcessingThread.run exactly)
# ---------------------------------------------------------------------------

def _run_pipeline(audio: np.ndarray, sr: int, settings: dict, token: int,
                  loop: asyncio.AbstractEventLoop) -> np.ndarray:
    from server.audio.autotuner import (
        autotune_to_note,
        autotune_with_formant_shift,
        autotune_soft_to_note,
        autotune_world_vt,
        autotune_praat_soft_to_note,
        autotune_sine_spectral,
        autotune_stft_pitchshift,
        apply_breathiness,
    )
    from server.audio.normalizer import normalize_audio
    from server.audio.cleanliness import apply_cleanliness, apply_high_shelf, apply_low_cut, compute_smart_lowcut
    from server.audio.time_stretch import STRETCHERS
    from server.audio.harmonic_limiter import (
        analyze_harmonics,
        apply_harmonic_limiting,
        harmonic_f0_from_settings,
    )

    timings = {}
    pipeline_start = time.perf_counter()

    def progress(p: float, stage: str):
        _push_progress(loop, p, stage)

    result = audio.copy()

    # 0. Pre-compute WORLD analysis (shared by pitch correction + breathiness)
    _t = time.perf_counter()
    pitch_mode = str(settings.get("pitch_mode", "world_hard"))
    needs_world = pitch_mode in ("world_hard", "world_soft", "world_vt", "world_hnm")
    needs_breathiness = (float(settings.get("breathiness", 1.0)) != 1.0)
    world_cache = None

    if needs_world or needs_breathiness:
        import hashlib
        audio_hash = hashlib.md5(audio[:min(1000, len(audio))].tobytes()).hexdigest()
        cached = state.world_cache
        if cached.get('audio_hash') == audio_hash and cached.get('sr') == sr:
            world_cache = cached
            timings['world_analysis'] = 0.0  # cache hit
        else:
            import pyworld as pw
            x64 = np.ascontiguousarray(audio, dtype=np.float64)
            _wt = time.perf_counter()
            w_f0, w_timeaxis = pw.dio(x64, sr, f0_floor=50.0, f0_ceil=500.0)
            w_f0 = pw.stonemask(x64, w_f0, w_timeaxis, sr)
            w_sp = pw.cheaptrick(x64, w_f0, w_timeaxis, sr)
            w_ap = pw.d4c(x64, w_f0, w_timeaxis, sr)
            timings['world_analysis'] = round((time.perf_counter() - _wt) * 1000, 1)
            world_cache = {
                'audio_hash': audio_hash,
                'f0': w_f0,
                'timeaxis': w_timeaxis,
                'sp': w_sp,
                'ap': w_ap,
                'sr': sr,
            }
            state.world_cache = world_cache

    # 1. Pitch correction
    _t = time.perf_counter()
    progress(0.05, "Autotuning...")

    if pitch_mode == "world_soft":
        result = autotune_soft_to_note(
            result,
            int(sr),
            str(settings["target_note"]),
            preserve_formants=bool(settings.get("preserve_formants", True)),
            formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
            voicing_mode="strict",
            world_cache=world_cache,
        )
    elif pitch_mode == "world_vt":
        result = autotune_world_vt(
            result,
            int(sr),
            str(settings["target_note"]),
            formant_shift_beta=float(settings.get("formant_shift_beta", 0.1)),
            crossover_freq=3000.0,
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
            voicing_mode="strict",
            world_cache=world_cache,
        )
    elif pitch_mode == "world_hnm":
        result = autotune_world_vt(
            result,
            int(sr),
            str(settings["target_note"]),
            use_hnm=True,
            formant_shift_beta=0.2,
            crossover_freq=3000.0,
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
            voicing_mode="strict",
            world_cache=world_cache,
        )
    elif pitch_mode == "praat_soft":
        result = autotune_praat_soft_to_note(
            result,
            int(sr),
            str(settings["target_note"]),
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
        )
    elif pitch_mode == "sine_spectral":
        result = autotune_sine_spectral(
            result,
            int(sr),
            str(settings["target_note"]),
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
            preserve_formants=bool(settings.get("preserve_formants", True)),
            formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
        )
    elif pitch_mode == "stft_pitchshift":
        result = autotune_stft_pitchshift(
            result,
            int(sr),
            str(settings["target_note"]),
            amount=float(settings.get("pitch_amount", 1.0)),
            retune_speed_ms=float(settings.get("retune_speed_ms", 40.0)),
            preserve_vibrato=float(settings.get("preserve_vibrato", 1.0)),
            preserve_formants=bool(settings.get("preserve_formants", True)),
            formant_shift_cents=int(settings.get("formant_shift_cents", 0)),
        )
    else:
        # world_hard (default) and unknown modes
        if settings.get("preserve_formants", True):
            result = autotune_to_note(result, sr, settings["target_note"],
                                      preserve_formants=True, world_cache=world_cache)
        else:
            result = autotune_with_formant_shift(
                result, sr,
                settings["target_note"],
                settings.get("formant_shift_cents", 0),
                world_cache=world_cache,
            )

    timings['pitch_correction'] = round((time.perf_counter() - _t) * 1000, 1)

    if not state.is_current_token(token):
        return result, {}, timings

    # 2. Time stretching
    _t = time.perf_counter()
    stretch_factor = float(settings.get("stretch_factor", 1.0))
    stretch_method = str(settings.get("stretch_method", "audiotsm_wsola"))
    if abs(stretch_factor - 1.0) > 1e-6:
        progress(0.35, f"Stretching... ({stretch_method}, x{stretch_factor:.2f})")
        fn = STRETCHERS.get(stretch_method)
        if fn is None:
            raise ValueError(f"Unknown stretching method: {stretch_method}")
        result = fn(result, int(sr), float(stretch_factor))

    timings['time_stretch'] = round((time.perf_counter() - _t) * 1000, 1)

    if not state.is_current_token(token):
        return result, {}, timings

    # 3. Smart fundamental-aware low cut
    _t = time.perf_counter()
    f0_hz = float((state.detected_pitch or {}).get("freq_hz", 0.0))
    if not np.isfinite(f0_hz) or f0_hz <= 0.0:
        f0_hz = 50.0
    lowcut_pct = float(settings.get("clean_lowcut_percent", 0.0))
    if np.isfinite(lowcut_pct) and lowcut_pct > 0.0:
        lowcut_hz = compute_smart_lowcut(f0_hz, lowcut_pct)
        if lowcut_hz > 0.0:
            progress(0.50, f"Removing sub (low cut {lowcut_hz:.0f} Hz)...")
            result = apply_low_cut(result, int(sr), float(lowcut_hz))

    timings['lowcut'] = round((time.perf_counter() - _t) * 1000, 1)

    # 4. Cleanliness + HF rollback
    _t = time.perf_counter()
    cleanliness_pct = float(settings.get("cleanliness_percent", 0.0))
    hf_rollback_pct = float(settings.get("clean_hf_rollback_percent", 0.0))
    if np.isfinite(cleanliness_pct) and cleanliness_pct > 0.0:
        progress(0.58, f"Applying {cleanliness_pct:.0f}% cleanliness...")
        # Pass cached f0 from WORLD analysis to skip redundant pyin
        _cached_f0 = world_cache['f0'] if world_cache and world_cache.get('f0') is not None else None
        _cached_voiced = (_cached_f0 > 0) if _cached_f0 is not None else None
        result = apply_cleanliness(
            result, int(sr), float(cleanliness_pct),
            hf_rollback_percent=float(hf_rollback_pct) if np.isfinite(hf_rollback_pct) else 0.0,
            cached_f0=_cached_f0,
            cached_voiced=_cached_voiced,
        )
    # Note: high shelf removed — replaced by HF rollback inside apply_cleanliness
    timings['cleanliness'] = round((time.perf_counter() - _t) * 1000, 1)

    # 6. Breathiness
    _t = time.perf_counter()
    breathiness = float(settings.get("breathiness", 1.0))
    hf_bias = float(settings.get("hf_bias", 0.0))
    if np.isfinite(breathiness) and np.isfinite(hf_bias) and breathiness != 1.0:
        progress(0.70, "Applying breathiness...")
        result = apply_breathiness(
            result,
            int(sr),
            amount=float(breathiness),
            hf_bias=float(hf_bias),
            world_cache=None,  # must re-analyse the pitch-corrected/stretched audio
        )

    timings['breathiness'] = round((time.perf_counter() - _t) * 1000, 1)

    if not state.is_current_token(token):
        return result, {}, timings

    # 7. Harmonic analysis (pre)
    _t = time.perf_counter()
    f0_hz = float(harmonic_f0_from_settings(settings))
    pre_analysis = analyze_harmonics(result, int(sr), f0_hz)

    # Build absolute ceilings from per-harmonic offsets
    offsets = settings.get("harmonic_ceiling_offsets_db", {})
    if not isinstance(offsets, dict):
        offsets = {}
    ceilings_abs: dict[int, float] = {}
    for i, h in enumerate(pre_analysis.harmonic_numbers):
        off = offsets.get(int(h))
        if off is None:
            continue
        try:
            off_f = float(off)
        except Exception:
            continue
        if not np.isfinite(off_f):
            continue
        ceilings_abs[int(h)] = float(pre_analysis.peak_db[i] + off_f)

    timings['harmonic_analysis_pre'] = round((time.perf_counter() - _t) * 1000, 1)

    # 8. Harmonic limiting
    _t = time.perf_counter()
    if bool(settings.get("harmonic_limiter_enabled", False)) and ceilings_abs:
        progress(0.78, "Applying harmonic limiting...")
        result = apply_harmonic_limiting(
            result,
            int(sr),
            f0_hz=float(f0_hz),
            ceilings_db=ceilings_abs,
            knee_db=float(settings.get("harmonic_knee_db", 6.0)),
            release_ms=float(settings.get("harmonic_release_ms", 50.0)),
            attack_ms=1.0,
        )
    timings['harmonic_limiting'] = round((time.perf_counter() - _t) * 1000, 1)

    _t = time.perf_counter()
    limiter_was_active = bool(settings.get("harmonic_limiter_enabled", False)) and bool(ceilings_abs)
    if limiter_was_active:
        post_analysis = analyze_harmonics(result, int(sr), f0_hz)
    else:
        post_analysis = pre_analysis  # no change — skip redundant analysis
    timings['harmonic_analysis_post'] = round((time.perf_counter() - _t) * 1000, 1)

    harmonic_dict = {
        "pre": pre_analysis.to_dict(),
        "post": post_analysis.to_dict(),
        "ceilings_abs_db": {str(k): float(v) for k, v in ceilings_abs.items()},
        "offsets_db": {str(k): float(v) for k, v in offsets.items()},
    }

    # 9. Normalize
    _t = time.perf_counter()
    if bool(settings.get("normalize", False)):
        progress(0.92, "Normalizing...")
        result = normalize_audio(result, target_db=-0.1)
    timings['normalize'] = round((time.perf_counter() - _t) * 1000, 1)

    timings['total_dsp'] = round((time.perf_counter() - pipeline_start) * 1000, 1)

    progress(1.0, "Done.")
    print(f"\n=== DSP PIPELINE TIMINGS ===")
    for k, v in timings.items():
        print(f"  {k:.<30s} {v:>8.1f} ms")
    print()

    return result, harmonic_dict, timings




# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LoadAudioRequest(BaseModel):
    file_path: str

    @field_validator("file_path")
    @classmethod
    def must_exist(cls, v: str) -> str:
        p = Path(v)
        if not p.exists():
            raise ValueError(f"File not found: {v}")
        # Reject files over 100 MB before even opening them
        try:
            size = p.stat().st_size
            if size > 100 * 1024 * 1024:
                raise ValueError(f"File too large: {size // (1024 * 1024)} MB (max 100 MB)")
        except OSError:
            pass
        return v


class ProcessRequest(BaseModel):
    target_note: str = "C4"
    pitch_mode: str = "world_hard"
    pitch_amount: float = 1.0
    retune_speed_ms: float = 40.0
    preserve_vibrato: float = 1.0
    preserve_formants: bool = True
    formant_shift_cents: float = 0    # accept float, round to int in validator
    formant_shift_beta: float = 0.1
    stretch_factor: float = 1.0
    stretch_method: str = "audiotsm_wsola"
    clean_lowcut_percent: float = 0.0
    cleanliness_percent: float = 0.0
    clean_hf_rollback_percent: float = 0.0
    breathiness: float = 1.0
    hf_bias: float = 0.0
    harmonic_limiter_enabled: bool = False
    harmonic_ceiling_offsets_db: Dict[str, float] = {}
    harmonic_knee_db: float = 6.0
    harmonic_release_ms: float = 50.0
    normalize: bool = False

    @field_validator("stretch_factor")
    @classmethod
    def stretch_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("stretch_factor must be > 0")
        return v

    @field_validator("formant_shift_cents")
    @classmethod
    def round_formant_cents(cls, v: float) -> float:
        return float(round(v))

    @field_validator("cleanliness_percent")
    @classmethod
    def clean_range(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError("cleanliness_percent must be 0-100")
        return v


class GetAudioRequest(BaseModel):
    which: str = "original"

    @field_validator("which")
    @classmethod
    def valid_which(cls, v: str) -> str:
        if v not in ("original", "processed"):
            raise ValueError("which must be 'original' or 'processed'")
        return v


class CrossfadeLoopRequest(BaseModel):
    template_periods: int = 6
    min_loop_periods: int = 10
    crossfade_periods: int = 2
    f0_hz: Optional[float] = None


class RenderMultisampleRequest(BaseModel):
    # Note range
    low_note: str = "C2"
    high_note: str = "C7"
    # Render options
    enable_loop: bool = True
    template_periods: int = 6
    min_loop_periods: int = 10
    crossfade_periods: int = 2
    start_trim_ms: float = 0.0
    generate_sfz: bool = True
    output_dir: Optional[str] = None
    # Processing settings (same fields as ProcessRequest)
    target_note: str = "C4"
    pitch_mode: str = "world_hard"
    pitch_amount: float = 1.0
    retune_speed_ms: float = 40.0
    preserve_vibrato: float = 1.0
    preserve_formants: bool = True
    formant_shift_cents: float = 0    # accept float, round to int in validator
    formant_shift_beta: float = 0.1
    stretch_factor: float = 1.0
    stretch_method: str = "audiotsm_wsola"
    clean_lowcut_percent: float = 0.0
    cleanliness_percent: float = 0.0
    clean_hf_rollback_percent: float = 0.0
    breathiness: float = 1.0
    hf_bias: float = 0.0
    harmonic_limiter_enabled: bool = False
    harmonic_ceiling_offsets_db: Dict[str, float] = {}
    harmonic_knee_db: float = 6.0
    harmonic_release_ms: float = 50.0
    normalize: bool = False

    @field_validator("formant_shift_cents")
    @classmethod
    def round_formant_cents(cls, v: float) -> float:
        return float(round(v))


class ExportRequest(BaseModel):
    output_path: str
    target_note: str = "C4"


class QuickExportRequest(BaseModel):
    target_note: str = "C4"
    overwrite: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/load-audio")
async def load_audio(req: LoadAudioRequest):
    load_timings = {}
    load_start = time.perf_counter()

    try:
        _t = time.perf_counter()
        audio, sr, _original_sr = await asyncio.to_thread(
            _load_audio_sync, req.file_path
        )
        load_timings['file_load_and_resample'] = round((time.perf_counter() - _t) * 1000, 1)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MemoryError:
        raise HTTPException(status_code=500, detail="Out of memory loading audio file - try a shorter sample")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Load failed: {e}")

    _t = time.perf_counter()
    freq, note, cents = await asyncio.to_thread(
        _detect_pitch_sync, audio, sr
    )
    load_timings['pitch_detection'] = round((time.perf_counter() - _t) * 1000, 1)

    state.original_audio = audio
    state.processed_audio = None
    state.sample_rate = sr
    state.detected_pitch = {"freq_hz": freq, "note_name": note, "cents": cents}
    state.harmonic_analysis = None
    state.world_cache = {'audio_hash': None}
    state.loop_start = None
    state.loop_end = None
    state.source_path = req.file_path

    _t = time.perf_counter()
    waveform_peaks = _compute_waveform_peaks(audio)
    load_timings['waveform_peaks'] = round((time.perf_counter() - _t) * 1000, 1)

    _t = time.perf_counter()
    peak_db_val = round(_peak_db(audio), 2)
    rms_db_val = round(_rms_db(audio), 2)
    load_timings['peak_rms'] = round((time.perf_counter() - _t) * 1000, 1)

    duration = float(len(audio)) / float(sr)
    load_timings['total_load'] = round((time.perf_counter() - load_start) * 1000, 1)
    load_timings['sample_count'] = len(audio)
    load_timings['duration_seconds'] = round(duration, 4)

    print(f"\n=== LOAD-AUDIO TIMINGS ({req.file_path}) ===")
    for k, v in load_timings.items():
        if isinstance(v, float) and k not in ('duration_seconds',):
            print(f"  {k:.<30s} {v:>8.1f} ms")
        elif k == 'duration_seconds':
            print(f"  {k:.<30s} {v:>8.4f} s")
        else:
            print(f"  {k:.<30s} {v}")
    print()

    return {
        "success": True,
        "duration_seconds": round(duration, 4),
        "sample_rate": sr,
        "detected_pitch": state.detected_pitch,
        "waveform_peaks": waveform_peaks,
        "peak_db": peak_db_val,
        "rms_db": rms_db_val,
        "timings": load_timings,
    }


def _load_audio_sync(file_path: str):
    from server.audio.loader import load_audio
    return load_audio(file_path)


def _detect_pitch_sync(audio: np.ndarray, sr: int):
    from server.audio.pitch_detector import get_predominant_pitch
    return get_predominant_pitch(audio, sr, fast=False)


@router.post("/load-audio-upload")
async def load_audio_upload(file: UploadFile = FastAPIFile(...)):
    """Load audio from an uploaded file (used for drag-and-drop in Electron 32+
    where File.path is unavailable)."""
    suffix = Path(file.filename or "upload.wav").suffix or ".wav"
    if suffix.lower() not in (".wav", ".mp3", ".flac", ".ogg", ".aiff"):
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {suffix}")

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 100 MB)")

    # Write to a temp file so the existing loader can handle it
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, prefix="fe_upload_")
    tmp_path = tmp.name
    try:
        tmp.write(content)
        tmp.close()

        audio, sr, _original_sr = await asyncio.to_thread(_load_audio_sync, tmp_path)
    except ValueError as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail=str(e))
    except MemoryError:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail="Out of memory loading audio file")
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail=f"Load failed: {e}")

    freq, note, cents = await asyncio.to_thread(_detect_pitch_sync, audio, sr)

    state.original_audio = audio
    state.processed_audio = None
    state.sample_rate = sr
    state.detected_pitch = {"freq_hz": freq, "note_name": note, "cents": cents}
    state.harmonic_analysis = None
    state.world_cache = {'audio_hash': None}
    state.loop_start = None
    state.loop_end = None
    state.source_path = tmp_path  # keep temp path for export reference

    waveform_peaks = _compute_waveform_peaks(audio)
    duration = float(len(audio)) / float(sr)

    return {
        "success": True,
        "duration_seconds": round(duration, 4),
        "sample_rate": sr,
        "detected_pitch": state.detected_pitch,
        "waveform_peaks": waveform_peaks,
        "peak_db": round(_peak_db(audio), 2),
        "rms_db": round(_rms_db(audio), 2),
        "uploaded_path": tmp_path,
    }


@router.post("/process")
async def process_audio(req: ProcessRequest):
    endpoint_start = time.perf_counter()

    if state.original_audio is None:
        raise HTTPException(status_code=404, detail="No audio loaded. Call /api/load-audio first.")

    _t_parse = time.perf_counter()
    token = state.increment_token()
    settings = req.model_dump()
    # Convert string keys in harmonic_ceiling_offsets_db to int for pipeline
    raw_offsets = settings.get("harmonic_ceiling_offsets_db", {})
    settings["harmonic_ceiling_offsets_db"] = {
        int(k): float(v) for k, v in raw_offsets.items()
    }

    audio = state.original_audio.copy()
    sr = state.sample_rate
    loop = asyncio.get_event_loop()

    _cleanup_last_temp()
    parse_time = round((time.perf_counter() - _t_parse) * 1000, 1)

    _t_dsp = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            _pipeline_wrapper, audio, sr, settings, token, loop
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")
    dsp_wall_time = round((time.perf_counter() - _t_dsp) * 1000, 1)

    if not state.is_current_token(token):
        raise HTTPException(status_code=409, detail="Processing superseded by newer request.")

    result_audio, harmonic_dict, dsp_timings = result
    state.processed_audio = result_audio
    state.harmonic_analysis = harmonic_dict
    # New processing clears any previously-set loop points
    state.loop_start = None
    state.loop_end = None

    # Write to temp file
    _t_ser = time.perf_counter()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="fe_processed_")
    tmp_path = tmp.name
    tmp.close()
    sf.write(tmp_path, result_audio, sr, subtype="PCM_16")
    state._last_temp_path = tmp_path

    _t_peaks = time.perf_counter()
    waveform_peaks = _compute_waveform_peaks(result_audio)
    peaks_time = round((time.perf_counter() - _t_peaks) * 1000, 1)
    dsp_timings['waveform_peaks'] = peaks_time

    duration = float(len(result_audio)) / float(sr)
    serialize_time = round((time.perf_counter() - _t_ser) * 1000, 1)

    total_endpoint = round((time.perf_counter() - endpoint_start) * 1000, 1)
    dsp_timings['settings_parse'] = parse_time
    dsp_timings['response_serialize'] = serialize_time
    dsp_timings['dsp_wall_time'] = dsp_wall_time
    dsp_timings['total_endpoint'] = total_endpoint

    print(f"\n=== PROCESS ENDPOINT TIMINGS ===")
    print(f"  settings_parse........... {parse_time:>8.1f} ms")
    print(f"  dsp_wall_time............ {dsp_wall_time:>8.1f} ms")
    print(f"  waveform_peaks........... {peaks_time:>8.1f} ms")
    print(f"  response_serialize....... {serialize_time:>8.1f} ms")
    print(f"  total_endpoint........... {total_endpoint:>8.1f} ms")
    print()

    return {
        "success": True,
        "token": token,
        "waveform_peaks": waveform_peaks,
        "peak_db": round(_peak_db(result_audio), 2),
        "rms_db": round(_rms_db(result_audio), 2),
        "harmonic_analysis": harmonic_dict,
        "duration_seconds": round(duration, 4),
        "audio_temp_path": tmp_path,
        "audio_temp_filename": os.path.basename(tmp_path),
        "timings": dsp_timings,
    }


def _pipeline_wrapper(audio, sr, settings, token, loop):
    return _run_pipeline(audio, sr, settings, token, loop)


@router.post("/get-audio")
async def get_audio(req: GetAudioRequest):
    if req.which == "original":
        audio = state.original_audio
    else:
        audio = state.processed_audio

    if audio is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {req.which} audio available."
        )

    sr = state.sample_rate
    encoded = await asyncio.to_thread(_audio_to_base64_wav, audio, sr)

    return {
        "success": True,
        "audio_base64": encoded,
        "sample_rate": sr,
    }


@router.get("/audio-file/{filename}")
async def serve_audio_file(filename: str):
    """Serve a temp WAV file directly (faster than base64 encoding)."""
    # Security: only serve files from the temp directory with our prefix
    if not filename.startswith("fe_processed_") and not filename.startswith("fe_upload_"):
        raise HTTPException(status_code=403, detail="Access denied")
    filepath = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filepath, media_type="audio/wav",
                        headers={"Cache-Control": "no-cache"})


@router.post("/export")
async def export_audio(req: ExportRequest):
    if state.processed_audio is None:
        raise HTTPException(status_code=404, detail="No processed audio. Run /api/process first.")

    output_path = str(req.output_path)
    try:
        await asyncio.to_thread(_export_sync, state.processed_audio, state.sample_rate, output_path, req.target_note)
    except PermissionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    file_size = Path(output_path).stat().st_size
    return {
        "success": True,
        "output_path": output_path,
        "file_size_bytes": file_size,
    }


@router.post("/quick-export")
async def quick_export(req: QuickExportRequest):
    if state.processed_audio is None:
        raise HTTPException(status_code=404, detail="No processed audio. Run /api/process first.")
    if not state.source_path:
        raise HTTPException(status_code=400, detail="No source path set.")

    src = Path(state.source_path)
    target_safe = req.target_note.replace("#", "s").replace("/", "_")
    output_path = str(src.parent / f"{src.stem}_{target_safe}_tuned.wav")

    if Path(output_path).exists() and not req.overwrite:
        return {"exists": True, "output_path": output_path}

    try:
        await asyncio.to_thread(_export_sync, state.processed_audio, state.sample_rate, output_path, req.target_note)
    except PermissionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quick export failed: {e}")

    file_size = Path(output_path).stat().st_size
    return {
        "success": True,
        "output_path": output_path,
        "file_size_bytes": file_size,
    }


def _export_sync(audio: np.ndarray, sr: int, output_path: str, target_note: str):
    from server.audio.loader import set_wav_root_note
    from server.utils.note_utils import note_name_to_midi

    # Windows MAX_PATH check (260 chars)
    if len(output_path) > 260:
        raise ValueError("File path too long (max 260 characters on Windows)")

    try:
        sf.write(output_path, audio, sr, subtype="PCM_16")
    except PermissionError as e:
        raise PermissionError(f"Permission denied - cannot write to: {output_path}") from e
    except OSError as e:
        err_str = str(e).lower()
        if getattr(e, "errno", 0) == 28 or "no space left" in err_str or "disk full" in err_str:
            raise OSError("Disk full - cannot export file") from e
        raise

    midi_note = note_name_to_midi(target_note)
    set_wav_root_note(output_path, midi_note, sr, state.loop_start, state.loop_end)


@router.post("/crossfade-loop")
async def crossfade_loop(req: CrossfadeLoopRequest):
    audio = state.processed_audio if state.processed_audio is not None else state.original_audio
    if audio is None:
        raise HTTPException(status_code=404, detail="No audio loaded. Call /api/load-audio first.")

    sr = state.sample_rate
    try:
        result_audio, loop_start, loop_end = await asyncio.to_thread(
            _crossfade_loop_sync,
            audio, sr,
            req.f0_hz,
            req.template_periods,
            req.min_loop_periods,
            req.crossfade_periods,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crossfade loop failed: {e}")

    state.processed_audio = result_audio
    state.loop_start = loop_start
    state.loop_end = loop_end

    loop_duration = (
        round((loop_end - loop_start) / sr, 4)
        if loop_start is not None and loop_end is not None
        else None
    )

    return {
        "success": True,
        "loop_start": loop_start,
        "loop_end": loop_end,
        "loop_duration_seconds": loop_duration,
        "sample_count": len(result_audio),
        "crossfade_periods": req.crossfade_periods,
    }


def _crossfade_loop_sync(audio, sr, f0_hz, template_periods, min_loop_periods, crossfade_periods):
    from server.audio.loop_crossfade import process_with_loop
    return process_with_loop(
        audio, sr,
        f0_hz=f0_hz,
        template_periods=template_periods,
        min_loop_periods=min_loop_periods,
        crossfade_periods=crossfade_periods,
    )


@router.post("/render-multisample")
async def render_multisample(req: RenderMultisampleRequest):
    if state.original_audio is None:
        raise HTTPException(status_code=404, detail="No audio loaded. Call /api/load-audio first.")
    if not state.source_path:
        raise HTTPException(status_code=400, detail="No source path set.")

    from server.utils.note_utils import note_name_to_midi
    try:
        low_midi = note_name_to_midi(req.low_note)
        high_midi = note_name_to_midi(req.high_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if low_midi > high_midi:
        raise HTTPException(status_code=400, detail="low_note must be <= high_note")

    # Resolve output directory
    src = Path(state.source_path)
    output_dir = req.output_dir or str(src.parent / src.stem)
    base_name = src.stem
    sfz_path = os.path.join(output_dir, f"{base_name}.sfz") if req.generate_sfz else None

    # Snapshot audio/settings for the thread
    source_audio = state.original_audio.copy()
    sr = state.sample_rate
    token = state.increment_token()

    settings_base = req.model_dump(exclude={
        "low_note", "high_note", "enable_loop",
        "template_periods", "min_loop_periods", "crossfade_periods",
        "start_trim_ms", "generate_sfz", "output_dir",
    })
    raw_offsets = settings_base.get("harmonic_ceiling_offsets_db", {})
    settings_base["harmonic_ceiling_offsets_db"] = {
        int(k): float(v) for k, v in raw_offsets.items()
    }

    progress_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def run_render():
        try:
            from server.audio.loop_crossfade import process_with_loop
            from server.audio.loader import save_audio, set_wav_root_note
            from server.audio.sfz_writer import write_sfz, note_name_for_filename

            import os
            os.makedirs(output_dir, exist_ok=True)

            note_names_display = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            total = high_midi - low_midi + 1
            results = []

            for i, midi_note in enumerate(range(low_midi, high_midi + 1)):
                if not state.is_current_token(token):
                    asyncio.run_coroutine_threadsafe(
                        progress_q.put({"cancelled": True}), loop
                    )
                    return

                note_name = note_name_for_filename(midi_note)
                # Pipeline needs '#' style names for pitch detection
                target_note_str = note_names_display[midi_note % 12] + str(midi_note // 12 - 1)

                # Send progress before processing this note
                asyncio.run_coroutine_threadsafe(
                    progress_q.put({
                        "progress": round(i / total, 4),
                        "current_note": note_name,
                        "notes_done": i,
                        "notes_total": total,
                    }),
                    loop,
                )

                note_settings = dict(settings_base)
                note_settings["target_note"] = target_note_str

                # Run DSP pipeline (internal sub-progress goes to main queue, ignored)
                processed, _, _timings = _run_pipeline(
                    source_audio.copy(), sr, note_settings, token, loop
                )

                if req.start_trim_ms > 0:
                    trim_samples = int(req.start_trim_ms / 1000.0 * sr)
                    if trim_samples < len(processed):
                        processed = processed[trim_samples:]

                loop_start = None
                loop_end = None
                if req.enable_loop:
                    # Compute target f0 for this MIDI note
                    target_f0 = 440.0 * (2 ** ((midi_note - 69) / 12))
                    processed, loop_start, loop_end = process_with_loop(
                        processed, sr,
                        f0_hz=target_f0,
                        template_periods=req.template_periods,
                        min_loop_periods=req.min_loop_periods,
                        crossfade_periods=req.crossfade_periods,
                    )

                filename = f"{base_name}_{note_name}.wav"
                filepath = os.path.join(output_dir, filename)

                save_audio(filepath, processed, sr)
                set_wav_root_note(filepath, midi_note, sr, loop_start, loop_end)

                results.append({
                    "midi": midi_note,
                    "note_name": note_name,
                    "path": filepath,
                    "filename": filename,
                    "loop_start": loop_start,
                    "loop_end": loop_end,
                    "sample_count": len(processed),
                })

            # Generate SFZ if requested
            generated_sfz_path = None
            if req.generate_sfz and results:
                write_sfz(sfz_path, base_name, results)
                generated_sfz_path = sfz_path

            asyncio.run_coroutine_threadsafe(
                progress_q.put({
                    "complete": True,
                    "output_dir": output_dir,
                    "sfz_path": generated_sfz_path,
                    "notes_rendered": len(results),
                }),
                loop,
            )

        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                progress_q.put({"error": str(e)}),
                loop,
            )

    threading.Thread(target=run_render, daemon=True).start()

    async def event_generator():
        while True:
            try:
                payload = await asyncio.wait_for(progress_q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            yield f"data: {json.dumps(payload)}\n\n".encode()
            if payload.get("complete") or payload.get("error") or payload.get("cancelled"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stretch-methods")
async def stretch_methods():
    return {
        "methods": [
            {"id": "audiotsm_wsola", "name": "WSOLA", "description": "Window Similarity Overlap-Add"},
            {"id": "audiotsm_ola", "name": "OLA", "description": "Overlap-Add"},
            {"id": "audiotsm_phasevocoder", "name": "Phase Vocoder", "description": "Phase Vocoder (audiotsm)"},
            {"id": "rubberband_default_engine_faster", "name": "Rubber Band (Faster)", "description": "Rubber Band default engine, faster"},
            {"id": "rubberband_default_engine_finer", "name": "Rubber Band (Finer)", "description": "Rubber Band default engine, finer"},
            {"id": "rubberband_percussive_engine_finer", "name": "Rubber Band Percussive", "description": "Rubber Band percussive engine, finer"},
            {"id": "tdpsola", "name": "TD-PSOLA", "description": "Time-Domain Pitch Synchronous Overlap-Add"},
        ]
    }


@router.post("/warmup")
async def warmup():
    t0 = time.monotonic()
    await asyncio.to_thread(_warmup_sync)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {"success": True, "duration_ms": elapsed_ms}


def _warmup_sync():
    sr = 44100
    t = np.linspace(0.0, 0.25, int(sr * 0.25), endpoint=False, dtype=np.float32)
    x = (0.15 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)

    # 1. librosa (pitch detection)
    try:
        from server.audio.pitch_detector import get_predominant_pitch
        get_predominant_pitch(x, sr, fast=True)
    except Exception as e:
        print(f"[warmup] pitch_detector: {e}")

    # 2. pyworld (autotuner — heaviest cold-start)
    try:
        from server.audio.autotuner import autotune_to_note
        autotune_to_note(x, sr, "C4", preserve_formants=True)
    except Exception as e:
        print(f"[warmup] autotuner: {e}")

    # 3. audiotsm (time stretching)
    try:
        from server.audio.time_stretch import STRETCHERS
        fn = STRETCHERS.get("audiotsm_wsola")
        if fn:
            fn(x, sr, 1.0)
    except Exception as e:
        print(f"[warmup] time_stretch: {e}")

    # 4. scipy.signal / scipy.ndimage (cleanliness / spectral processing)
    try:
        from server.audio.cleanliness import apply_cleanliness
        apply_cleanliness(x, sr, 10.0)
    except Exception as e:
        print(f"[warmup] cleanliness: {e}")


@router.get("/process-progress")
async def process_progress():
    """Server-Sent Events stream for processing progress."""
    async def event_generator():
        while True:
            try:
                payload = await asyncio.wait_for(_progress_queue.get(), timeout=30.0)
                data = f"data: {json.dumps(payload)}\n\n"
                yield data.encode()
            except asyncio.TimeoutError:
                # Keep-alive comment
                yield b": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
