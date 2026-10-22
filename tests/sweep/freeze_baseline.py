"""Freeze a sweep run as the committed before/after reference.

    python tests/sweep/freeze_baseline.py --run-dir tests/sweep/out/prefix_run \
        --probes tests/sweep/out/probes.json --report docs/SWEEP_REPORT.md --tag prefix

Writes tests/sweep/baseline/<tag>.json.gz (compact rows, fixture meta, probe
results, the 10 worst renders picked for listening) and
baseline/<tag>_report.md, and adds a "<tag>" entry to history.json.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from collections import Counter
from pathlib import Path

import classify
import sweep_config as cfg

KEEP_METRICS = ("f0_cents", "f0_voiced", "inharm_db", "inharm_worse_db", "tail_db", "tail_late_db",
                "rms_change_db", "peak_dbfs", "length_delta_ms", "body_db", "harm_db", "h1_db",
                "nonfinite", "exception", "n_out", "n_expected", "pre_db")
KEEP_ROW = ("id", "sets", "fixture", "mode", "shift", "stretch", "lowcut", "clean", "hfrb", "breath",
            "hfbias", "target_note", "fails", "exceed", "severity", "attribution", "warnings")


def select_worst(rows, cl: classify.Classifier, n: int = cfg.N_WORST_WAVS) -> list[dict]:
    """Worst renders by post-pitch severity, <= WORST_PER_MODE_CAP per mode and
    <= 4 per dominant post-pitch metric (same rule the report has always used)."""
    picked, per_mode, per_metric = [], Counter(), Counter()
    for r in sorted(rows, key=lambda r: (-cl.post_severity(r), -r["severity"])):
        if not cl.post_exceed(r) or r.get("traceback") or r["metrics"].get("nonfinite"):
            continue
        dm = cl.dominant(r)
        if per_mode[r["mode"]] >= cfg.WORST_PER_MODE_CAP or per_metric[dm] >= 4:
            continue
        picked.append(r)
        per_mode[r["mode"]] += 1
        per_metric[dm] += 1
        if len(picked) >= n:
            break
    return picked


def compact(r: dict) -> dict:
    out = {k: r.get(k) for k in KEEP_ROW}
    out["metrics"] = {k: r["metrics"].get(k) for k in KEEP_METRICS if k in r["metrics"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--probes", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--tag", default="prefix")
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.run_dir / "results.jsonl")]
    summary = json.loads((args.run_dir / "summary.json").read_text())
    probes = json.loads(args.probes.read_text())
    cl = classify.Classifier(rows)
    worst = select_worst(rows, cl)
    wav_dir = args.run_dir / "worst"
    files = sorted(p.name for p in wav_dir.glob("*.wav")) if wav_dir.exists() else []

    payload = {
        "tag": args.tag, "git_head": summary["env"]["git_head"], "elapsed_min": summary["elapsed_min"],
        "thresholds": summary["thresholds"], "meta": summary["meta"], "fixtures": summary["fixtures"],
        "pass_rates": cl.pass_rates(rows), "probes": probes,
        "worst": [{"rank": i, "id": r["id"],
                   "file": next((f for f in files if f.startswith(f"{i:02d}_") and "pitch_only" not in f), None)}
                  for i, r in enumerate(worst, 1)],
        "rows": [compact(r) for r in rows],
    }
    cfg.BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(cfg.BASELINE_DIR / f"{args.tag}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    shutil.copyfile(args.report, cfg.BASELINE_DIR / f"{args.tag}_report.md")

    pr = payload["pass_rates"]
    causes = Counter()
    for r in rows:
        for m in cl.post_fails(r):
            for c in cl.causes(r, m):
                for lab in classify.expand(c):
                    causes[lab] += 1
    entry = {"tag": args.tag, "date": "frozen", "git_head": payload["git_head"], "server_or_ui_dirty": False,
             "elapsed_min": payload["elapsed_min"], **pr,
             "post_failures": sum(len(cl.post_fails(r)) for r in rows),
             "post_failures_by_cause": dict(causes.most_common())}
    hist = json.loads(cfg.HISTORY_PATH.read_text()) if cfg.HISTORY_PATH.exists() else []
    hist = [entry] + [h for h in hist if h["tag"] != args.tag]
    cfg.HISTORY_PATH.write_text(json.dumps(hist, indent=1) + "\n")
    print(f"froze {len(rows)} rows as {args.tag}: raw {pr['raw_pct']:.1f} %, post {pr['post_pct']:.1f} %, "
          f"post excl. intended {pr['post_ex_pct']:.1f} %; worst: {[w['file'] for w in payload['worst']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
