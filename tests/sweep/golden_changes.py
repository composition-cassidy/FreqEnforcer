"""Regenerate golden references whose render has a post-pitch stage active,
logging before/after metrics to tests/sweep/intentional_changes.json.

    python tests/sweep/golden_changes.py --change change1 \
        --reason "cleanliness/low cut follow the output F0" pipe_clean

Each positional argument must match exactly one manifest case id. Cases
without cleanliness, breathiness or low cut active are refused, since
pitch-only references must never change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np
import soundfile as sf

import fixtures
import metrics
import sweep_config as cfg

sys.path.insert(0, str(cfg.ROOT / "tests" / "golden"))
import matrix  # noqa: E402


def post_active(params: dict) -> bool:
    return (float(params.get("cleanliness_percent", 0.0)) > 0.0
            or float(params.get("clean_lowcut_percent", 0.0)) > 0.0
            or float(params.get("breathiness", 1.0)) != 1.0)


def measure(audio: np.ndarray, case) -> dict:
    from server.utils.note_utils import note_name_to_freq
    fx = fixtures.get(case.fixture.rsplit(".", 1)[0])
    settings = dict(matrix.PIPELINE_DEFAULTS, **case.params)
    stretch = float(settings.get("stretch_factor", 1.0))
    inp = metrics.input_metrics(fx)
    m = metrics.render_metrics(audio, fx, stretch, float(note_name_to_freq(case.target_note)), inp)
    fails, _ex, _sev = metrics.evaluate(m, settings)
    keep = {k: m.get(k) for k in ("peak_dbfs", "rms_change_db", "f0_cents", "inharm_worse_db", "tail_db",
                                  "length_delta_ms")}
    keep["h1_vs_input_db"] = None if m.get("h1_db") is None or inp.get("h1_db") is None else m["h1_db"] - inp["h1_db"]
    keep["fails"] = fails
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--change", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("cases", nargs="+", help="case id substrings, one match each")
    args = ap.parse_args()

    manifest = json.loads(matrix.MANIFEST_PATH.read_text())
    log = json.loads(cfg.INTENTIONAL_PATH.read_text()) if cfg.INTENTIONAL_PATH.exists() else []
    for pat in args.cases:
        hits = [c for c in manifest["cases"] if pat in c["id"]]
        if len(hits) != 1:
            raise SystemExit(f"{pat!r} matches {len(hits)} cases: {[c['id'] for c in hits]}")
        entry = hits[0]
        case = matrix.case_from_manifest(entry)
        if case.function != "_run_pipeline" or not post_active(case.params):
            raise SystemExit(f"refusing {entry['id']}: no cleanliness/breathiness/low cut in its render")
        path = matrix.GOLDEN_DIR / entry["file"]
        old, _sr = sf.read(str(path), dtype="float64")
        new, _sr2, _extra = matrix.render(case)
        before, after = measure(old, case), measure(new, case)
        diff = float(np.max(np.abs(old - new))) if old.shape == new.shape else None
        log.append({"change": args.change, "case": entry["id"], "file": f"tests/golden/{entry['file']}",
                    "reason": args.reason, "before": before, "after": after, "max_abs_diff": diff})
        print(f"{entry['id']}: before {before['fails']} -> after {after['fails']}, max|diff| {diff}")
        subprocess.check_call([sys.executable, "-B", str(cfg.ROOT / "tests" / "golden" / "render_golden.py"),
                               "--only", entry["id"]], cwd=cfg.ROOT)
    cfg.INTENTIONAL_PATH.write_text(json.dumps(log, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
