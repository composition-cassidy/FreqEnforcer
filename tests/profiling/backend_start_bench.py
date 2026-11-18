"""Time the backend from spawn to first 200 on /health.

    python tests/profiling/backend_start_bench.py <backend exe or 'source'> [runs] [ENV=VAL ...]

Prints per-run (port line, health) in ms and the median of runs 2..n.
"""
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
target = sys.argv[1]
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 6
env = dict(os.environ)
for kv in sys.argv[3:]:
    k, v = kv.split("=", 1)
    env[k] = v
cmd = [sys.executable, str(ROOT / "server" / "main.py"), "--port", "0"] if target == "source" else [target, "--port", "0"]

rows = []
for i in range(runs):
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=ROOT, text=True)
    port = None
    while port is None:
        line = p.stdout.readline()
        if not line:
            sys.exit("backend exited early")
        m = re.match(r"FREQENFORCER_PORT=(\d+)", line)
        if m:
            port = int(m.group(1))
    t_port = time.perf_counter() - t0
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.002)
    t_health = time.perf_counter() - t0
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    p.wait()
    rows.append((t_port * 1000, t_health * 1000))
    print(f"run {i + 1}: port {t_port * 1000:6.0f} ms   health {t_health * 1000:6.0f} ms")
    time.sleep(0.5)

warm = rows[1:] or rows
print(f"median (runs 2..{runs}): port {statistics.median(r[0] for r in warm):.0f} ms   "
      f"health {statistics.median(r[1] for r in warm):.0f} ms")
