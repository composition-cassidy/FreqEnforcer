"""End-to-end smoke test of a backend binary over HTTP.

Usage:
    python tests/smoke_backend.py                      # build-backend exe
    python tests/smoke_backend.py --python             # python server/main.py
    python tests/smoke_backend.py --exe path/to/backend.exe

Starts the backend with ``--port 0`` (reads the announced FREQENFORCER_PORT
line; falls back to 8765 for older builds), then exercises load-audio, every
pitch mode, a WSOLA and a Rubber Band stretch, and a short multisample
render.  Exits non-zero on the first failure.  Not collected by pytest
(it needs a built exe and takes ~30 s).
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "build-backend" / "freqenforcer-backend" / "freqenforcer-backend.exe"
FIXTURE = ROOT / "tests" / "fixtures" / "test_2s_C4.wav"

MODES = ["world_hard", "world_soft", "world_vt", "world_hnm", "praat_soft",
         "sine_spectral", "stft_pitchshift"]


def start(cmd: list[str]) -> tuple[subprocess.Popen, int, float]:
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout], daemon=True).start()
    port = None
    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline and port is None:
        try:
            line = lines.get(timeout=0.05)
            if line.startswith("FREQENFORCER_PORT="):
                port = int(line.split("=", 1)[1])
        except queue.Empty:
            pass
        if proc.poll() is not None:
            raise SystemExit(f"backend exited early with {proc.returncode}")
        if port is None:  # legacy builds never announce; probe the fixed port
            try:
                if httpx.get("http://127.0.0.1:8765/health", timeout=0.3).status_code == 200:
                    port = 8765
            except httpx.HTTPError:
                pass
    if port is None:
        raise SystemExit("backend never reported a port")
    while True:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5).status_code == 200:
                return proc, port, time.perf_counter() - t0
        except httpx.HTTPError:
            time.sleep(0.02)


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    ap.add_argument("--python", action="store_true", help="run python server/main.py instead")
    args = ap.parse_args()
    cmd = ([sys.executable, str(ROOT / "server" / "main.py")] if args.python
           else [str(args.exe)]) + ["--port", "0"]

    proc, port, t_ready = start(cmd)
    print(f"backend ready on port {port} in {t_ready:.2f}s ({' '.join(cmd[:2])})")
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=300) as c:
            r = c.post("/api/load-audio", json={"file_path": str(FIXTURE)})
            check(r.status_code == 200 and r.json()["detected_pitch"]["note_name"] == "C4",
                  f"load-audio -> {r.status_code} {r.json().get('detected_pitch')}")
            for mode in MODES:
                r = c.post("/api/process", json={"target_note": "F4", "pitch_mode": mode})
                ok = r.status_code == 200
                if ok:
                    a = c.get(f"/api/audio-file/{r.json()['audio_temp_filename']}")
                    ok = a.status_code == 200 and len(a.content) > 44
                check(ok, f"process {mode} -> {r.status_code}")
            for method in ("audiotsm_wsola", "rubberband_default_engine_finer"):
                r = c.post("/api/process", json={"target_note": "F4", "stretch_factor": 1.5,
                                                 "stretch_method": method})
                check(r.status_code == 200 and r.json()["duration_seconds"] > 2.5,
                      f"stretch {method} -> {r.status_code}")
            with tempfile.TemporaryDirectory(prefix="fe_smoke_") as out:
                t0 = time.perf_counter()
                last = None
                with c.stream("POST", "/api/render-multisample",
                              json={"low_note": "C4", "high_note": "D#4", "output_dir": out}) as r:
                    for line in r.iter_lines():
                        if line.startswith("data: "):
                            last = json.loads(line[6:])
                            if last.get("complete") or last.get("error"):
                                break
                files = sorted(p.name for p in Path(out).iterdir())
                check(bool(last and last.get("complete")) and last.get("notes_rendered") == 4,
                      f"multisample 4 notes in {time.perf_counter() - t0:.1f}s -> {last}")
                check(not any("#" in f for f in files), f"no '#' in filenames: {files}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
