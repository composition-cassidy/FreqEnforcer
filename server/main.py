"""FreqEnforcer FastAPI server.

    python server/main.py              # listens on config.PORT (8765)
    python server/main.py --port 0     # OS-assigned port (what Electron uses)

The bound port is always announced on stdout as ``FREQENFORCER_PORT=<n>``.
"""

import argparse
import multiprocessing
import os
import socket
import sys
import threading

# numpy and scipy each start an OpenBLAS pool with one thread per core, and
# each pool commits its buffers up front: ~1.5 GB of private memory on a
# 24-thread CPU, multiplied by every multisample worker. The DSP only calls
# BLAS for vector dot products, which OpenBLAS runs on one thread anyway.
# Must be set before numpy is first imported; child processes inherit it.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure the server package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from server.config import PORT, HOST, VERSION
from server.routes.audio import router as audio_router


@asynccontextmanager
async def lifespan(app):
    """Verify DSP module imports on startup.

    Only modules that requests actually use. The heavy third-party libraries
    (scipy.signal, pyworld, parselmouth, Rubber Band) are imported lazily inside
    the DSP functions; /api/warmup pulls them in after the UI is up.
    (server.audio.sinusoidal is not on any request path and imports all of
    scipy.signal at module level, ~0.5 s, so it is not imported here.)
    """
    try:
        from server.audio import (
            autotuner,
            cleanliness,
            harmonic_limiter,
            hnm_synth,
            loader,
            normalizer,
            pitch_detector,
            time_stretch,
        )
    except ImportError as e:
        print(f"WARNING: DSP import failed: {e}")
        print("The server will still run, but audio processing may not work.")
    # The first thing a session does is load a file, and pitch detection
    # imports scipy.ndimage (~0.25 s). Import it in the background once the
    # server is listening: /health answers right away, and a load that arrives
    # first just waits on the same import it would have needed anyway.
    threading.Thread(target=_preload_load_path, name="preload", daemon=True).start()
    yield


def _preload_load_path():
    try:
        from server.audio import pitch_yin  # noqa: F401  (scipy.ndimage)
    except ImportError:
        pass


app = FastAPI(title="FreqEnforcer", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION}


def _parse_port(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="FreqEnforcer backend")
    parser.add_argument("--port", type=int, default=PORT,
                        help=f"port to listen on (default {PORT}; 0 = let the OS pick a free one)")
    # parse_known_args: frozen/multiprocessing launches may append their own args
    return parser.parse_known_args(argv)[0].port


def _bind(port: int) -> socket.socket:
    """Bind before starting uvicorn so the real port is known up front and a
    taken port fails fast with a clear message instead of a uvicorn traceback."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, port))
    return sock


if __name__ == "__main__":
    # Multisample rendering uses a process pool; in the frozen exe the worker
    # processes re-launch this binary and must be diverted here.
    multiprocessing.freeze_support()
    requested = _parse_port(sys.argv[1:])
    try:
        sock = _bind(requested)
    except OSError:
        print(f"ERROR: Port {requested} is already in use. Start with --port 0 to use a free port.")
        sys.exit(1)
    port = sock.getsockname()[1]
    print(f"FREQENFORCER_PORT={port}", flush=True)
    # No websocket routes: ws="none" keeps uvicorn from loading a websocket stack.
    uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, ws="none")).run(sockets=[sock])
