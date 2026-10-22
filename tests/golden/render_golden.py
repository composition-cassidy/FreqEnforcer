"""Render the FreqEnforcer golden reference set.

Usage:
    python tests/golden/render_golden.py              # (re)write all references
    python tests/golden/render_golden.py --only hnm   # only case ids containing "hnm"
    python tests/golden/render_golden.py --out DIR    # render elsewhere (determinism check)

Writes float32 WAVs to tests/golden/<fixture_stem>/<mode>__<voicing>__<note>.wav
and tests/golden/manifest.json.  Only regenerate after an *intentional* DSP
change, and commit the new references together with that change.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matrix  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402


def _env() -> dict:
    def ver(pkg: str) -> str | None:
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None

    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=matrix.ROOT,
                                       text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "server"],
                                             cwd=matrix.ROOT, text=True).strip())
    except Exception:
        head, dirty = None, None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_head": head,
        "server_dirty": dirty,
        "packages": {p: ver(p) for p in ("numpy", "scipy", "soundfile", "pyworld",
                                          "praat-parselmouth", "pylibrb", "stftpitchshift",
                                          "soxr")},
        "rng_seed": matrix.RNG_SEED,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="substring filter on case id")
    ap.add_argument("--out", type=Path, default=matrix.GOLDEN_DIR,
                    help="output directory (default: tests/golden)")
    args = ap.parse_args()

    out_dir: Path = args.out
    manifest_path = out_dir / "manifest.json"
    existing = {}
    if args.only and manifest_path.exists():
        existing = {c["id"]: c for c in json.loads(manifest_path.read_text())["cases"]}

    cases = matrix.build_cases()
    if args.only:
        cases = [c for c in cases if args.only in c.id]

    sources = {}
    for fx in matrix.FIXTURES:
        f0, note, cents = matrix.detect_source(fx)
        sources[fx] = {"detected_f0": round(float(f0), 3), "note": note, "cents": cents}

    t_all = time.perf_counter()
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        audio, sr, extra = matrix.render(case)
        dt = time.perf_counter() - t0
        a32 = audio.astype(np.float32)

        path = out_dir / case.rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), a32, sr, subtype="FLOAT")

        entry = {
            "id": case.id,
            "file": case.rel_path,
            "fixture": case.fixture,
            "mode": case.mode,
            "function": case.function,
            "params": case.params,
            "voicing": case.voicing,
            "semitones": case.semitones,
            "target_note": case.target_note,
            "sr": sr,
            "n_samples": int(a32.size),
            "sha256": matrix.sha256_f32(a32),
            **matrix.measure(a32, sr),
            "render_s": round(dt, 3),
            **extra,
        }
        existing[case.id] = entry
        print(f"[{i:3d}/{len(cases)}] {case.id:<55s} {dt:6.2f}s  "
              f"rms={entry['rms']:.4f} f0={entry['detected_f0']}", flush=True)

    manifest = {
        "description": "FreqEnforcer DSP golden references (float32 WAV). "
                       "See tests/test_regression.py for comparison rules.",
        "env": _env(),
        "sources": sources,
        "cases": sorted(existing.values(), key=lambda c: c["id"]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    print(f"\n{len(cases)} cases rendered in {time.perf_counter() - t_all:.1f}s -> {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
