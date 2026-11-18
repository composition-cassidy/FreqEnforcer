"""Multisample render time and peak memory of a built backend exe.

    py -3.14 tests/profiling/multisample_bench.py <backend exe> [runs]

Loads tests/fixtures/test_2s_C4.wav, renders 24 notes (C3-B4, world_hard,
looping on) through /api/render-multisample, and samples the private
(committed) memory of the backend and its worker processes every 100 ms.
Prints wall time and peak memory per run; the exe is killed (by PID, with its
process tree) afterwards.
"""
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXE = Path(sys.argv[1]).resolve()
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
WAV = ROOT / "tests" / "fixtures" / "test_2s_C4.wav"


def tree_private_mb(pid: int) -> float:
    ps = ("$ids=@(%d); $all=Get-CimInstance Win32_Process; "
          "do { $n=$ids.Count; $ids=@($ids + ($all | ? { $ids -contains $_.ParentProcessId } | %% ProcessId) | select -Unique) } while ($ids.Count -ne $n); "
          "($all | ? { $ids -contains $_.ProcessId } | Measure-Object PrivatePageCount -Sum).Sum" % pid)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    return float(out or 0) / 1048576


def post(port, path, body, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


rows = []
for i in range(RUNS):
    p = subprocess.Popen([str(EXE), "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    port = None
    while port is None:
        m = re.match(r"FREQENFORCER_PORT=(\d+)", p.stdout.readline())
        port = m and int(m.group(1))
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()  # drain
    while True:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.02)
    post(port, "/api/load-audio", {"file_path": str(WAV)}).read()

    peak = [tree_private_mb(p.pid)]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            peak.append(tree_private_mb(p.pid))
            time.sleep(0.1)

    t = threading.Thread(target=sample, daemon=True)
    out_dir = tempfile.mkdtemp(prefix="fe_msbench_")
    t.start()
    t0 = time.perf_counter()
    with post(port, "/api/render-multisample", {"low_note": "C3", "high_note": "B4", "target_note": "C4",
                                                "output_dir": out_dir}) as r:
        last = ""
        for line in r:
            if line.startswith(b"data:"):
                last = line.decode()
    wall = time.perf_counter() - t0
    stop.set()
    t.join()
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    p.wait()
    ok = '"complete": true' in last.replace("True", "true") or '"complete":true' in last
    rows.append((wall, max(peak)))
    print(f"run {i + 1}: {wall:.2f} s, peak private {max(peak):.0f} MB, complete={ok}")
    time.sleep(1)

print(f"median: {sorted(r[0] for r in rows)[len(rows) // 2]:.2f} s, "
      f"peak private {sorted(r[1] for r in rows)[len(rows) // 2]:.0f} MB")
