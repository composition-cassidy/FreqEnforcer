"""FreqEnforcer profiling baseline (wall-clock + cProfile).

Usage:
    python tests/profiling/profile_baseline.py all
    python tests/profiling/profile_baseline.py startup|http|dsp|multisample

Sections:
  startup      cold start of the PyInstaller backend exe vs `python server/main.py`
               (time from spawn to first 200 on /health) + -X importtime breakdown
  http         /api/load-audio + /api/process per pitch mode end-to-end over HTTP
  dsp          DSP-only wall clock (median of 3) + cProfile per pitch mode
  multisample  24-note render: real /api/render-multisample SSE call + cProfile'd
               in-process replica of the endpoint's loop

Raw results go to tests/profiling/out/<section>.json (+ .prof files); a
markdown summary is printed for docs/PROFILE.md.  Needs port 8765 free.
"""

from __future__ import annotations

import cProfile
import json
import os
import pstats
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import types
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "tests" / "golden"))
import matrix  # noqa: E402  (also sets up sys.path for server.* / audio.*)

import numpy as np  # noqa: E402

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
EXE = Path(os.environ.get("FE_BACKEND_EXE",
                          ROOT / "build-backend" / "freqenforcer-backend" / "freqenforcer-backend.exe"))
FIXTURE = "test_10s_C4.wav"
TARGET = "F4"  # +5 semitones from the C4 fixtures

BUCKETS = ["Python glue", "numpy/scipy", "pyworld", "parselmouth", "pylibrb",
           "HTTP/IO", "startup", "other 3rd-party"]

# App-equivalent calls per pitch mode (voicing as _run_pipeline passes it).
DSP_MODES = {
    "world_hard": ("autotune_to_note", {"preserve_formants": True}),
    "world_formant": ("autotune_with_formant_shift", {"formant_shift_cents": 200}),
    "world_soft": ("autotune_soft_to_note", {"voicing_mode": "strict"}),
    "world_vt": ("autotune_world_vt", {"formant_shift_beta": 0.1, "voicing_mode": "strict"}),
    "world_hnm": ("autotune_world_vt", {"use_hnm": True, "formant_shift_beta": 0.2,
                                        "voicing_mode": "strict"}),
    "praat_soft": ("autotune_praat_soft_to_note", {}),
    "sine_spectral": ("autotune_sine_spectral", {}),
    "stft_pitchshift": ("autotune_stft_pitchshift", {}),
}
HTTP_MODES = ["world_hard", "world_soft", "world_vt", "world_hnm", "praat_soft",
              "sine_spectral", "stft_pitchshift"]


# ---------------------------------------------------------------------------
# cProfile attribution
# ---------------------------------------------------------------------------

_RULES = [
    ("pyworld", re.compile(r"pyworld", re.I)),
    ("parselmouth", re.compile(r"parselmouth", re.I)),
    ("pylibrb", re.compile(r"pylibrb", re.I)),
    ("startup", re.compile(r"importlib|<frozen |_bootstrap|zipimport")),
    ("other 3rd-party", re.compile(r"stftpitchshift|soxr", re.I)),
    ("HTTP/IO", re.compile(r"soundfile|_soundfile|cffi|uvicorn|starlette|fastapi|h11|httpx|"
                           r"anyio|json|socket|selectors|asyncio|_io\.|'_io|io\.Buffered|"
                           r"tempfile|threading|queue", re.I)),
    ("numpy/scipy", re.compile(r"numpy|scipy|ufunc|ndarray|_pocketfft|pocketfft|_methods\.py|"
                               r"fromnumeric|_multiarray|linalg", re.I)),
    ("Python glue", re.compile(r"[\\/]server[\\/]|[\\/]tests[\\/]")),
]


# cProfile (CPython 3.14) does not record calls into Cython (pyworld) or
# nanobind (pylibrb) functions, so their time lands in the *calling* Python
# frame, and it occasionally drops or double-books events entirely.  We
# therefore route every native entry point through a trampoline installed at
# runtime (no source changes) that accumulates its own exclusive wall time per
# bucket.  Native buckets come from these timers; cProfile is only used to
# split the remaining (pure-Python-frame) time between glue / numpy / IO.

_NATIVE_T: dict[str, float] = defaultdict(float)


def _native(fn, label: str):
    bucket = bucket_for("", f"native[{label}]")

    def native_call(*a, **k):
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            _NATIVE_T[bucket] += time.perf_counter() - t0
    code = native_call.__code__.replace(co_name=f"native[{label}]",
                                        co_qualname=f"native[{label}]")
    return types.FunctionType(code, native_call.__globals__, code.co_name,
                              None, native_call.__closure__)


class _RBProxy:
    """Wraps a pylibrb.RubberBandStretcher so its methods are timed as pylibrb."""

    def __init__(self, cls, *a, **k):
        self._s = _native(cls, "pylibrb.RubberBandStretcher")(*a, **k)

    def __getattr__(self, name):
        attr = getattr(self._s, name)
        return _native(attr, f"pylibrb.{name}") if callable(attr) else attr


_wrappers_installed = False


def install_native_wrappers() -> None:
    global _wrappers_installed
    if _wrappers_installed:
        return
    import parselmouth.praat
    import pyworld
    import soundfile
    import soxr
    import stftpitchshift.vocoder as vocoder
    from server.audio import time_stretch

    for n in ("dio", "harvest", "stonemask", "cheaptrick", "d4c", "synthesize"):
        setattr(pyworld, n, _native(getattr(pyworld, n), f"pyworld.{n}"))
    parselmouth.praat.call = _native(parselmouth.praat.call, "parselmouth.call")
    for n in ("read", "write"):
        setattr(soundfile, n, _native(getattr(soundfile, n), f"soundfile.{n}"))
    soxr.resample = _native(soxr.resample, "soxr.resample")
    for n in ("encode", "decode"):
        setattr(vocoder, n, _native(getattr(vocoder, n), f"stftpitchshift.{n}"))

    orig_import = time_stretch._pylibrb_import

    def _pylibrb_import():
        Option, RBS, create = orig_import()
        return Option, (lambda *a, **k: _RBProxy(RBS, *a, **k)), _native(create, "pylibrb.create")
    time_stretch._pylibrb_import = _pylibrb_import
    _wrappers_installed = True


def bucket_for(filename: str, funcname: str) -> str:
    text = f"{filename} {funcname}"
    for name, rx in _RULES:
        if rx.search(text):
            return name
    if filename == "~":  # remaining C builtins (len, math.*, list ops ...) = interpreter glue
        return "Python glue"
    return "other 3rd-party"


def attribute(prof: cProfile.Profile, wall: float, native: dict[str, float]) -> dict:
    """Bucket seconds = native timers + (wall - native) split by cProfile ratios."""
    st = pstats.Stats(prof)
    py_totals: dict[str, float] = defaultdict(float)
    top: list[tuple[float, str, str]] = []
    for (filename, lineno, func), (_cc, _nc, tt, _ct, _callers) in st.stats.items():
        # Harness frames and trampolines: their time is either no DSP work or
        # already counted by the native timers.
        if Path(filename).resolve() == Path(__file__).resolve():
            continue
        b = bucket_for(filename, func)
        if b in native:  # e.g. stftpitchshift/soundfile .py frames: inside a native timer
            continue
        py_totals[b] += tt
        top.append((tt, b, f"{Path(filename).name}:{lineno}({func})" if filename != "~" else func))
    native_total = sum(native.values())
    residual = max(wall - native_total, 0.0)
    py_sum = sum(py_totals.values()) or 1e-12
    seconds = {b: native.get(b, 0.0) + residual * py_totals.get(b, 0.0) / py_sum for b in BUCKETS}
    top += [(t, b, f"native timer [{b}]") for b, t in native.items()]
    top.sort(reverse=True)
    return {
        "wall_profiled_s": wall,
        "native_timed_s": dict(native),
        "cprofile_python_frames_s": dict(py_totals),
        "cprofile_unaccounted_s": wall - native_total - sum(py_totals.values()),
        "seconds": seconds,
        "percent": {b: 100.0 * s / wall for b, s in seconds.items()},
        "top": [{"self_s": round(t, 4), "bucket": b, "func": f} for t, b, f in top[:15]],
    }


def profiled(fn, prof_path: Path):
    prof = cProfile.Profile()
    _NATIVE_T.clear()
    t0 = time.perf_counter()
    prof.enable()
    try:
        result = fn()
    finally:
        prof.disable()
    wall = time.perf_counter() - t0
    prof.dump_stats(str(prof_path))
    return result, attribute(prof, wall, dict(_NATIVE_T))


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

def port_free() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def wait_health(proc: subprocess.Popen, t0: float, timeout: float = 120.0) -> float:
    import httpx
    while time.perf_counter() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with {proc.returncode}")
        try:
            if httpx.get(f"{BASE}/health", timeout=0.5).status_code == 200:
                return time.perf_counter() - t0
        except Exception:
            pass
        time.sleep(0.01)
    raise TimeoutError("server did not become healthy")


def start_server(cmd: list[str]) -> tuple[subprocess.Popen, float]:
    if not port_free():
        raise SystemExit(f"port {PORT} is in use; close FreqEnforcer / dev server first")
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc, wait_health(proc, t0)


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    for _ in range(200):
        if port_free():
            return
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# (a) startup
# ---------------------------------------------------------------------------

def importtime_breakdown() -> dict:
    code = ("import server.main\n"
            "from server.audio import autotuner, cleanliness, harmonic_limiter, hnm_synth, "
            "loader, normalizer, pitch_detector, sinusoidal, time_stretch\n")
    res = subprocess.run([sys.executable, "-X", "importtime", "-c", code], cwd=str(ROOT),
                         capture_output=True, text=True)
    pkg_self: dict[str, float] = defaultdict(float)
    for line in res.stderr.splitlines():
        m = re.match(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|(\s*)(\S+)", line)
        if not m:
            continue
        pkg_self[m.group(4).split(".")[0]] += int(m.group(1)) / 1e6
    total = sum(pkg_self.values())
    buckets: dict[str, float] = defaultdict(float)
    for pkg, s in pkg_self.items():
        if pkg in ("numpy", "scipy"):
            buckets["numpy/scipy"] += s
        elif pkg in ("fastapi", "starlette", "pydantic", "pydantic_core", "uvicorn", "anyio",
                     "h11", "httptools", "websockets", "soundfile", "_soundfile", "cffi",
                     "email", "http", "json", "asyncio", "multipart", "python_multipart",
                     "typing_extensions", "annotated_types", "sniffio", "idna", "click"):
            buckets["HTTP/IO"] += s
        elif pkg == "server":
            buckets["Python glue"] += s
        elif pkg == "pyworld":
            buckets["pyworld"] += s
        else:
            buckets["other (stdlib etc.)"] += s
    top = sorted(pkg_self.items(), key=lambda kv: -kv[1])[:12]
    return {"total_import_s": total, "buckets_s": dict(buckets),
            "top_packages_s": {k: round(v, 4) for k, v in top}}


def section_startup(repeats: int = 5) -> dict:
    out: dict = {"exe": str(EXE), "exe_mtime": time.ctime(EXE.stat().st_mtime) if EXE.exists() else None}
    variants = {"python server/main.py": [sys.executable, str(ROOT / "server" / "main.py")]}
    if EXE.exists():
        variants["PyInstaller exe"] = [str(EXE)]
    for name, cmd in variants.items():
        times = []
        for _ in range(repeats + 1):
            proc, t = start_server(cmd)
            stop_server(proc)
            times.append(t)
        out[name] = {"first_s": times[0], "warm_median_s": statistics.median(times[1:]),
                     "all_s": times}
        print(f"  startup {name}: first {times[0]:.2f}s, warm median {statistics.median(times[1:]):.2f}s")
    out["importtime"] = importtime_breakdown()
    print(f"  importtime total {out['importtime']['total_import_s']:.2f}s")
    return out


# ---------------------------------------------------------------------------
# (b) HTTP end-to-end
# ---------------------------------------------------------------------------

def section_http(warm_repeats: int = 3) -> dict:
    import httpx
    proc, t_health = start_server([sys.executable, str(ROOT / "server" / "main.py")])
    out: dict = {"fixture": FIXTURE, "target_note": TARGET, "health_s": t_health, "modes": {}}
    try:
        with httpx.Client(base_url=BASE, timeout=600) as c:
            t0 = time.perf_counter()
            r = c.post("/api/load-audio", json={"file_path": str(ROOT / FIXTURE)})
            r.raise_for_status()
            out["load_audio"] = {"client_s": time.perf_counter() - t0,
                                 "server_timings_ms": r.json()["timings"],
                                 "response_bytes": len(r.content)}
            for mode in HTTP_MODES:
                runs = []
                for i in range(warm_repeats + 1):
                    t0 = time.perf_counter()
                    r = c.post("/api/process", json={"target_note": TARGET, "pitch_mode": mode})
                    t_proc = time.perf_counter() - t0
                    r.raise_for_status()
                    body = r.json()
                    t1 = time.perf_counter()
                    a = c.get(f"/api/audio-file/{body['audio_temp_filename']}")
                    t_file = time.perf_counter() - t1
                    tm = body["timings"]
                    runs.append({
                        "process_client_s": t_proc,
                        "audio_file_client_s": t_file,
                        "audio_file_bytes": len(a.content),
                        "response_bytes": len(r.content),
                        "server_total_endpoint_s": tm["total_endpoint"] / 1000,
                        "server_dsp_wall_s": tm["dsp_wall_time"] / 1000,
                        "server_serialize_s": tm["response_serialize"] / 1000,
                        "server_world_analysis_s": tm.get("world_analysis", 0) / 1000,
                        "server_pitch_s": tm["pitch_correction"] / 1000,
                        "server_harmonic_pre_s": tm["harmonic_analysis_pre"] / 1000,
                    })
                warm = runs[1:]
                med = {k: statistics.median(r_[k] for r_ in warm) for k in warm[0]}
                e2e = med["process_client_s"] + med["audio_file_client_s"]
                med["e2e_s"] = e2e
                med["http_overhead_s"] = e2e - med["server_dsp_wall_s"]
                out["modes"][mode] = {"first": runs[0], "warm_median": med}
                print(f"  http {mode:16s} first {runs[0]['process_client_s']:.2f}s  warm e2e {e2e:.2f}s "
                      f"(dsp {med['server_dsp_wall_s']:.2f}s, overhead {med['http_overhead_s'] * 1000:.0f}ms)")
    finally:
        stop_server(proc)
    return out


# ---------------------------------------------------------------------------
# (c) DSP only
# ---------------------------------------------------------------------------

def section_dsp(repeats: int = 3) -> dict:
    from server.audio import autotuner
    install_native_wrappers()
    audio, sr = matrix.load_fixture(FIXTURE)
    out: dict = {"fixture": FIXTURE, "target_note": TARGET, "modes": {}}

    def run_mode(fn_name, kw):
        np.random.seed(0)
        return getattr(autotuner, fn_name)(audio.copy(), sr, TARGET, **kw)

    for mode, (fn_name, kw) in DSP_MODES.items():
        run_mode(fn_name, kw)  # warm lazy imports
        walls = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            run_mode(fn_name, kw)
            walls.append(time.perf_counter() - t0)
        _, att = profiled(lambda: run_mode(fn_name, kw), OUT / f"dsp_{mode}.prof")
        att["wall_median_s"] = statistics.median(walls)
        out["modes"][mode] = att
        print(f"  dsp {mode:16s} {att['wall_median_s']:.2f}s  " +
              " ".join(f"{b.split('/')[0]}={att['percent'][b]:.0f}%" for b in BUCKETS if att['percent'][b] >= 1))

    # Full /process pipeline in-process (incl. world precompute, harmonic analysis,
    # temp WAV write + peaks) so the e2e row can be attributed.
    from server.routes import audio as routes
    import soundfile as sf

    def process_like_endpoint(settings):
        from server.state import state
        state.world_cache = {"audio_hash": None}
        state.detected_pitch = {"freq_hz": 261.6, "note_name": "C4", "cents": 0}
        tok = state.increment_token()
        res, _h, _t = routes._run_pipeline(audio.copy(), sr, settings, tok, matrix._progress_loop())
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, res, sr, subtype="PCM_16")
        routes._compute_waveform_peaks(res)
        os.unlink(tmp.name)

    for name, extra in {
        "endpoint_world_hard": {},
        "endpoint_heavy_chain": {"pitch_mode": "world_soft", "clean_lowcut_percent": 50.0,
                                 "cleanliness_percent": 50.0, "breathiness": 2.0,
                                 "stretch_factor": 1.5,
                                 "stretch_method": "rubberband_default_engine_finer",
                                 "harmonic_limiter_enabled": True,
                                 "harmonic_ceiling_offsets_db": {2: -6.0, 3: -6.0}},
    }.items():
        settings = dict(matrix.PIPELINE_DEFAULTS, target_note=TARGET, **extra)
        process_like_endpoint(settings)
        t0 = time.perf_counter()
        process_like_endpoint(settings)
        wall = time.perf_counter() - t0
        _, att = profiled(lambda: process_like_endpoint(settings), OUT / f"dsp_{name}.prof")
        att["wall_median_s"] = wall
        out["modes"][name] = att
        print(f"  dsp {name:16s} {wall:.2f}s")
    return out


# ---------------------------------------------------------------------------
# (d) 24-note multisample
# ---------------------------------------------------------------------------

MS_FIXTURE = "test_2s_C4.wav"
MS_LOW, MS_HIGH = "C3", "B4"  # 24 notes


def _multisample_replica(audio, sr, out_dir: str):
    """Same per-note work as render_multisample.run_render in server/routes/audio.py."""
    from server.audio.loader import save_audio, set_wav_root_note
    from server.audio.loop_crossfade import process_with_loop
    from server.audio.sfz_writer import note_name_for_filename, write_sfz
    from server.routes.audio import _run_pipeline
    from server.state import state
    from server.utils.note_utils import note_name_to_midi

    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    state.detected_pitch = {"freq_hz": 261.6, "note_name": "C4", "cents": 0}
    state.world_cache = {"audio_hash": None}
    tok = state.increment_token()
    results = []
    for midi in range(note_name_to_midi(MS_LOW), note_name_to_midi(MS_HIGH) + 1):
        settings = dict(matrix.PIPELINE_DEFAULTS, target_note=names[midi % 12] + str(midi // 12 - 1))
        processed, _, _ = _run_pipeline(audio.copy(), sr, settings, tok, matrix._progress_loop())
        processed, ls, le = process_with_loop(processed, sr, f0_hz=440.0 * 2 ** ((midi - 69) / 12))
        fn = os.path.join(out_dir, f"ms_{note_name_for_filename(midi)}.wav")
        save_audio(fn, processed, sr)
        set_wav_root_note(fn, midi, sr, ls, le)
        results.append({"midi": midi, "note_name": note_name_for_filename(midi), "path": fn,
                        "filename": os.path.basename(fn), "loop_start": ls, "loop_end": le,
                        "sample_count": len(processed)})
    write_sfz(os.path.join(out_dir, "ms.sfz"), "ms", results)
    return len(results)


def section_multisample() -> dict:
    import httpx
    out: dict = {"fixture": MS_FIXTURE, "range": f"{MS_LOW}-{MS_HIGH}", "pitch_mode": "world_hard"}
    tmp_root = Path(tempfile.mkdtemp(prefix="fe_ms_profile_"))
    try:
        # In-process replica, wall + cProfile
        install_native_wrappers()
        audio, sr = matrix.load_fixture(MS_FIXTURE)
        d1 = tmp_root / "wall"
        d1.mkdir()
        t0 = time.perf_counter()
        n = _multisample_replica(audio, sr, str(d1))
        out["inprocess_wall_s"] = time.perf_counter() - t0
        out["notes"] = n
        d2 = tmp_root / "prof"
        d2.mkdir()
        _, att = profiled(lambda: _multisample_replica(audio, sr, str(d2)), OUT / "multisample.prof")
        out["inprocess_profile"] = att
        print(f"  multisample in-process {n} notes {out['inprocess_wall_s']:.2f}s")

        # Real endpoint over HTTP (SSE)
        proc, _ = start_server([sys.executable, str(ROOT / "server" / "main.py")])
        try:
            with httpx.Client(base_url=BASE, timeout=600) as c:
                c.post("/api/load-audio", json={"file_path": str(ROOT / MS_FIXTURE)}).raise_for_status()
                d3 = tmp_root / "http"
                t0 = time.perf_counter()
                last = None
                with c.stream("POST", "/api/render-multisample",
                              json={"low_note": MS_LOW, "high_note": MS_HIGH,
                                    "output_dir": str(d3), "pitch_mode": "world_hard"}) as r:
                    for line in r.iter_lines():
                        if line.startswith("data: "):
                            last = json.loads(line[6:])
                            if last.get("complete") or last.get("error"):
                                break
                out["http_wall_s"] = time.perf_counter() - t0
                out["http_final_event"] = last
                print(f"  multisample HTTP {out['http_wall_s']:.2f}s  -> {last}")
        finally:
            stop_server(proc)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# (e) headroom: interpreter overhead vs numpy kernel time in the hot loops
# ---------------------------------------------------------------------------

def _best_of(fn, n=3) -> float:
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def section_headroom() -> dict:
    """How much of the hottest Python-frame time is interpreter overhead?

    Compares the shipped per-frame/per-lag Python loops with harness-only
    vectorised numpy equivalents (same maths, checked with allclose).  Nothing
    here is used by the app; it only sizes the "Python glue" share.
    """
    from server.audio import pitch_yin
    from server.audio.pitch_detector import detect_pitch
    audio, sr = matrix.load_fixture(FIXTURE)
    out: dict = {"fixture": FIXTURE}

    # pYIN as used by sine_spectral / stft_pitchshift / load-audio
    out["detect_pitch_full_s"] = _best_of(lambda: detect_pitch(audio, sr, fast=False), 2)

    x = audio.astype(np.float64)
    n, hop = 2048, 512
    tau_max = min(n // 2, int(sr / 50.0))
    n_frames = 1 + (len(x) - n) // hop
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop][:n_frames]

    def loop_version():
        return np.stack([pitch_yin._cmnd(pitch_yin._difference_function(f, tau_max), tau_max)
                         for f in frames])

    def vector_version():
        taus = np.arange(tau_max + 1)
        cs = np.concatenate([np.zeros((len(frames), 1)), np.cumsum(frames ** 2, axis=1)], axis=1)
        spec = np.fft.rfft(frames, 2 * n, axis=1)
        r = np.fft.irfft(spec * np.conj(spec), axis=1)[:, : tau_max + 1]
        d = cs[:, n - taus] - cs[:, :1] + cs[:, n:n + 1] - cs[:, taus] - 2.0 * r
        d[:, 0] = 0.0
        running = np.cumsum(d[:, 1:], axis=1)
        dp = np.ones_like(d)
        with np.errstate(divide="ignore", invalid="ignore"):
            dp[:, 1:] = np.where(running != 0.0, d[:, 1:] * taus[1:] / running, 1.0)
        return dp

    ref, vec = loop_version(), vector_version()
    out["yin_diff_cmnd"] = {
        "frames": int(n_frames), "lags": int(tau_max),
        "python_loop_s": _best_of(loop_version, 2),
        "vectorised_numpy_s": _best_of(vector_version, 3),
        "max_abs_err": float(np.max(np.abs(ref - vec))),
    }
    y = out["yin_diff_cmnd"]
    y["speedup"] = y["python_loop_s"] / y["vectorised_numpy_s"]
    print(f"  headroom yin diff+cmnd: loop {y['python_loop_s']:.2f}s vs numpy "
          f"{y['vectorised_numpy_s'] * 1000:.0f}ms ({y['speedup']:.0f}x, err {y['max_abs_err']:.1e})")

    # HNM harmonic kernel: numpy cos/outer/dot per 5 ms frame at the F4 target
    fs, fft_size, f0 = sr, 2048, 349.23
    n_harm = min(int(fs / (2.0 * f0)), int(fs / 2.0 / 50.0) + 1)
    freq = np.arange(1, n_harm + 1) * f0
    t_local = np.arange(fft_size) / fs
    amps, ph = np.random.rand(n_harm), np.random.rand(n_harm)

    def kernel():
        theta = np.outer(freq, t_local) * (2.0 * np.pi)
        theta += ph[:, None]
        return np.dot(amps, np.cos(theta))

    reps = 200
    per_frame = _best_of(lambda: [kernel() for _ in range(reps)], 3) / reps
    n_hnm_frames = int(len(audio) / (fs * 0.005)) + 1
    out["hnm_kernel"] = {"n_harmonics": n_harm, "per_frame_ms": per_frame * 1000,
                         "frames": n_hnm_frames,
                         "numpy_kernel_total_s": per_frame * n_hnm_frames}
    print(f"  headroom hnm kernel: {per_frame * 1000:.2f} ms/frame x {n_hnm_frames} = "
          f"{per_frame * n_hnm_frames:.2f}s")
    return out


# ---------------------------------------------------------------------------

def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUT.mkdir(parents=True, exist_ok=True)
    sections = {"startup": section_startup, "http": section_http,
                "dsp": section_dsp, "multisample": section_multisample,
                "headroom": section_headroom}
    todo = list(sections) if which == "all" else [which]
    for name in todo:
        print(f"== {name} ==", flush=True)
        res = sections[name]()
        (OUT / f"{name}.json").write_text(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
