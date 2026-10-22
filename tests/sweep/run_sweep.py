"""Post-pitch combination sweep for FreqEnforcer (measures; fixes nothing).

    python tests/sweep/run_sweep.py --tag change1   # full sweep + probes + report;
                                                    # appends a pass-rate entry to history.json
    python tests/sweep/run_sweep.py --quick         # smoke subset (~1 min), no history entry
    python tests/sweep/run_sweep.py --probes-only   # probes only -> out/probes.json
    python tests/sweep/report.py                    # rebuild the report from out/

Renders every combination through server.routes.audio._run_pipeline directly
(no HTTP) in a process pool:

  pairwise  greedy covering array over mode x shift x stretch x lowcut x
            cleanliness x hf_rollback x breathiness x hf_bias, on every fixture
  grid      cleanliness x breathiness x shift x mode, on every fixture
  baseline  pitch-only render of every (fixture, mode, shift, stretch)
  probes    targeted experiments for suspected bugs B1-B5 (probes.py)

Outputs: tests/sweep/out/{results.jsonl, summary.json, probes.json,
fixtures/*.wav, worst/*.wav} and docs/SWEEP_REPORT.md.
Thresholds and swept values: tests/sweep/sweep_config.py.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

import fixtures
import pairwise
import probes
import sweep_config as cfg
import worker


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def build_tasks(quick: bool) -> tuple[list[dict], dict]:
    fx_names = fixtures.QUICK_FIXTURES if quick else fixtures.SWEEP_FIXTURES
    modes = ["world_hard", "praat_soft"] if quick else cfg.PITCH_MODES
    shifts = [-12, 0, 5] if quick else cfg.SHIFTS
    cleans = [0.0, 50.0, 100.0] if quick else cfg.CLEANS
    breaths = [0.0, 1.0, 2.0] if quick else cfg.BREATHS

    rows, coverage = pairwise.build(cfg.PAIRWISE_FACTORS, cfg.PAIRWISE_SEED, cfg.PAIRWISE_CANDIDATES)
    if quick:
        rows = [r for r in rows if r["pitch_mode"] in modes and r["_shift"] in shifts]

    groups: dict[tuple, dict] = {}

    def group(fx_name, mode, shift, stretch):
        key = (fx_name, mode, int(shift), float(stretch))
        if key not in groups:
            groups[key] = {"fixture": fx_name, "mode": mode, "shift": int(shift),
                           "stretch": float(stretch), "combos": []}
        return groups[key]

    for fx_name in fx_names:
        for mode in modes:
            for shift in shifts:
                for stretch in cfg.STRETCHES:
                    group(fx_name, mode, shift, stretch)          # baseline always rendered
                g = group(fx_name, mode, shift, 1.0)
                for clean in cleans:
                    for breath in breaths:
                        g["combos"].append(({"cleanliness_percent": clean, "breathiness": breath}, "grid"))
        for r in rows:
            post = {k: v for k, v in r.items() if k not in ("pitch_mode", "_shift", "stretch_factor")}
            group(fx_name, r["pitch_mode"], r["_shift"], r["stretch_factor"])["combos"].append((post, "pairwise"))

    meta = {"pairwise_rows": len(rows), "pairwise_coverage": coverage, "fixtures": fx_names,
            "modes": modes, "shifts": shifts, "cleans": cleans, "breaths": breaths, "quick": quick}
    return list(groups.values()), meta


def _weight(task: dict) -> float:
    fx = fixtures.get(task["fixture"])
    return (len(fx.audio) / fx.sr) * task["stretch"] * (1 + len(task["combos"]))


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=cfg.ROOT,
                                       text=True).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain", "--", "server", "src"],
                                            cwd=cfg.ROOT, text=True).strip())
    except Exception:
        return True


def append_history(tag: str, summary: dict) -> None:
    """One pass-rate entry per full run (history.json is committed with each change)."""
    import classify
    from collections import Counter
    rows = [json.loads(line) for line in open(cfg.OUT_DIR / "results.jsonl")]
    cl = classify.Classifier(rows)
    causes = Counter()
    for r in rows:
        for m in cl.post_fails(r):
            for c in cl.causes(r, m):
                for lab in classify.expand(c):
                    causes[lab] += 1
    entry = {"tag": tag, "date": time.strftime("%Y-%m-%d %H:%M"), "git_head": _git_head(),
             "server_or_ui_dirty": _git_dirty(), "elapsed_min": summary["elapsed_min"],
             **cl.pass_rates(rows),
             "post_failures": sum(len(cl.post_fails(r)) for r in rows),
             "post_failures_by_cause": dict(causes.most_common())}
    hist = json.loads(cfg.HISTORY_PATH.read_text()) if cfg.HISTORY_PATH.exists() else []
    hist = [h for h in hist if h["tag"] != tag] + [entry]
    cfg.HISTORY_PATH.write_text(json.dumps(hist, indent=1) + "\n")
    print(f"history: {tag} raw {entry['raw_pct']:.1f} %  post {entry['post_pct']:.1f} %  "
          f"post excl. intended {entry['post_ex_pct']:.1f} %")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=cfg.WORKERS)
    ap.add_argument("--quick", action="store_true", help="small smoke subset")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--probes-only", action="store_true")
    ap.add_argument("--tag", default=None, help="history.json label for this run")
    args = ap.parse_args()

    from server.audio.modes import MODES
    assert sorted(MODES) == sorted(cfg.PITCH_MODES), f"pitch modes changed: {sorted(MODES)}"

    t_start = time.perf_counter()
    cfg.OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.probes_only:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(probes.PROBES))) as pool:
            res = dict(pool.map(probes.run_probe, probes.PROBES))
        (cfg.OUT_DIR / "probes.json").write_text(json.dumps(res, indent=1, default=_jsonable))
        print("probes:", {k: v.get("elapsed_s") for k, v in res.items()},
              "errors:", [k for k, v in res.items() if "error" in v])
        return 0
    tasks, meta = build_tasks(args.quick)
    print(f"pairwise: {meta['pairwise_rows']} rows, pair coverage {meta['pairwise_coverage']:.1%}")

    # Detected pitch exactly as /api/load-audio sets it, computed once here
    det = {n: fixtures.detected(n) for n in meta["fixtures"]}
    fx_meta = {}
    for n in meta["fixtures"]:
        fx = fixtures.get(n)
        fx_meta[n] = {"kind": fx.kind, "truth_note": fx.truth_note, "truth_f0": fx.truth_f0,
                      "duration_s": len(fx.audio) / fx.sr, "onset_s": fx.onset_s, "offset_s": fx.offset_s,
                      "has_tail": fx.has_tail, "description": fx.description, "detected": det[n],
                      "input": worker.input_metrics(fx)}
    fixtures.save_all(cfg.OUT_DIR / "fixtures", meta["fixtures"])
    for t in tasks:
        t["detected_pitch"] = det[t["fixture"]]
    tasks.sort(key=_weight, reverse=True)
    n_renders = sum(1 + len({worker.post_key(p) for p, _ in t["combos"]} - {worker.post_key(cfg.NEUTRAL_POST)})
                    for t in tasks)
    print(f"{len(tasks)} groups, ~{n_renders} renders, {args.workers} workers")

    results_path = cfg.OUT_DIR / "results.jsonl"
    probe_res: dict = {}
    group_meta = []
    n_rows = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool, open(results_path, "w") as fh:
        futs = {}
        if not args.no_probes:
            for name in probes.PROBES:
                futs[pool.submit(probes.run_probe, name)] = ("probe", name)
        for t in tasks:
            futs[pool.submit(worker.run_group, t)] = ("group", t)
        done = 0
        n_groups = len(tasks)
        for fut in as_completed(futs):
            kind, ref = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # worker crashed outside the per-render guard
                if kind == "probe":
                    probe_res[ref] = {"error": repr(e)}
                else:
                    group_meta.append({"group": f"{ref['fixture']}|{ref['mode']}|{ref['shift']}|{ref['stretch']}",
                                       "error": repr(e)})
                continue
            if kind == "probe":
                name, pres = res
                probe_res[name] = pres
                print(f"  probe {name} done ({pres.get('elapsed_s')} s){' ERROR' if 'error' in pres else ''}")
                continue
            for row in res["rows"]:
                fh.write(json.dumps(row, default=_jsonable) + "\n")
            n_rows += len(res["rows"])
            group_meta.append({k: res[k] for k in ("group", "fidelity", "librosa", "elapsed_s")})
            done += 1
            if done % max(1, n_groups // 20) == 0 or done == n_groups:
                el = time.perf_counter() - t_start
                print(f"  {done}/{n_groups} groups, {n_rows} renders, {el / 60:.1f} min elapsed, "
                      f"~{el / done * (n_groups - done) / 60:.1f} min left")

    summary = {
        "meta": meta, "fixtures": fx_meta, "groups": group_meta, "n_rows": n_rows,
        "elapsed_min": round((time.perf_counter() - t_start) / 60.0, 2),
        "env": {"python": platform.python_version(), "platform": platform.platform(),
                "git_head": _git_head(), "workers": args.workers,
                "librosa_in_parent": "librosa" in sys.modules},
        "thresholds": {k: getattr(cfg, k) for k in ("F0_ERR_CENTS", "INHARM_WORSE_DB", "TAIL_DB", "TAIL_MS",
                                                    "RMS_LOSS_DB", "RMS_LOSS_MAX_CLEAN", "LENGTH_TOL_MS",
                                                    "PEAK_DBFS")},
    }
    (cfg.OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1, default=_jsonable))
    if probe_res:
        (cfg.OUT_DIR / "probes.json").write_text(json.dumps(probe_res, indent=1, default=_jsonable))
    print(f"wrote {n_rows} rows to {results_path} in {summary['elapsed_min']} min")
    if args.tag and not args.quick:
        append_history(args.tag, summary)

    if not args.no_report:
        import report
        report.build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
