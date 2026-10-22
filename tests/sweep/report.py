"""Build docs/SWEEP_REPORT.md from tests/sweep/out/ and save the worst renders.

    python tests/sweep/report.py        # rebuild from the last run_sweep.py output

Verdict rules for B1-B5 are written next to each verdict in the report.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date

import numpy as np

import sweep_config as cfg

METRIC_COLS = cfg.METRICS
CAUSE_TEXT = {
    "B1": "B1 - cleanliness masks the ORIGINAL f0's harmonics (cached WORLD f0 of the input)",
    "B2": "B2 - cleanliness 100 %: 10 Hz mask < 21.5 Hz STFT bin, even with correct f0",
    "clean_mask": "cleanliness 25-75 % mask with correct f0 (STFT smear / harmonic loss below B2's extreme)",
    "B3": "B3 - smart low cut keyed to the original f0 (state.detected_pitch)",
    "B4": "B4 - breathiness re-analyses with harvest (default 71-800 Hz) instead of the right f0",
    "breath_resynth": "breathiness second WORLD resynthesis itself (amount < 1, correct f0 does not help)",
    "breath_intended": "breathiness > 1 adds aperiodicity (intended effect, fails the inharmonic rule)",
    "lowcut_design": "smart low cut with correct f0 (0.85 x f0 cutoff, filtfilt)",
    "E1": "E1 - cleanliness ISTFT edge blow-up: no leading pad, first samples / ~0 window sum (NOLA)",
    "E2": "E2 - cleanliness's own pyin f0 (no WORLD cache) is wrong, e.g. target outside its 50-500 Hz range",
    "pitch_miss": "pitch stage missed the target note; later f0/inharm failures are measured against a pitch "
                  "the post stages never received (not credited to post-pitch bugs)",
    "unexplained": "unexplained by the counterfactuals",
}


# ---------------------------------------------------------------------------
# Loading / helpers
# ---------------------------------------------------------------------------

def load():
    rows = [json.loads(line) for line in open(cfg.OUT_DIR / "results.jsonl")]
    summary = json.loads((cfg.OUT_DIR / "summary.json").read_text())
    pp = cfg.OUT_DIR / "probes.json"
    probes = json.loads(pp.read_text()) if pp.exists() else {}
    return rows, summary, probes


def f(v, nd=1, signed=False):
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        s = f"{v:+.{nd}f}" if signed else f"{v:.{nd}f}"
        return s.replace("-", "−")
    return str(v)


def fdb(v, nd=1, signed=False):
    """dB value; metrics.py floors silence at -300 dB, shown as -inf."""
    if isinstance(v, (int, float)) and v < -200.0:
        return "−∞"
    return f(v, nd, signed)


def table(headers, body) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in body:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def cause_key(c: str) -> str:
    if c.startswith("clean_mask_"):
        return "clean_mask"
    return c


_BASELINES: dict[tuple, dict] = {}


def _gkey(r) -> tuple:
    return (r["fixture"], r["mode"], r["shift"], r["stretch"])


def set_baselines(rows) -> None:
    _BASELINES.clear()
    _BASELINES.update({_gkey(r): r for r in rows if "baseline" in r["sets"]})


def causes_of(row, metric) -> list[str]:
    if "baseline" in row["sets"]:          # the pitch-only render itself (also a grid cell)
        return ["inherited"]
    att = row["attribution"].get(metric, ["unexplained"])
    base = _BASELINES.get(_gkey(row))
    if (metric in ("f0", "inharm") and att != ["inherited"] and base is not None
            and "f0" in base["fails"]):
        # The pitch stage already missed the target note: every f0/inharm number is measured
        # against a target the cleanliness/breathiness input never had, and the "correct f0"
        # counterfactuals would merely re-pitch it. Not credited to a post-pitch bug.
        return ["pitch_miss"]
    return att


def expand(c: str) -> list[str]:
    """Root-cause labels named by one attribution entry."""
    if c.startswith("joint:") or c.startswith("multi:"):
        return [cause_key(x) for x in c.split(":", 1)[1].split("+")]
    return [cause_key(c)]


def is_post_failure(row, metric) -> bool:
    return not all(c in ("inherited", "pitch_miss") for c in causes_of(row, metric))


def post_exceed(row) -> dict:
    """Exceedance ratios of the failures the post-pitch stages are responsible for."""
    ex = row.get("exceed") or {}
    return {m: v for m, v in ex.items() if m in row["fails"] and is_post_failure(row, m)}


def post_severity(row) -> float:
    return float(sum(post_exceed(row).values()))


def dominant(row) -> str:
    ex = post_exceed(row)
    return max(ex, key=ex.get) if ex else "-"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def sec_header(summary, rows) -> str:
    env, meta = summary["env"], summary["meta"]
    fid = [x for g in summary["groups"] for x in g.get("fidelity", [])]
    exact = sum(1 for x in fid if x["same_len"] and x["max_abs_diff"] == 0.0)
    lib = any(g.get("librosa") for g in summary["groups"]) or env.get("librosa_in_parent")
    errs = [g for g in summary["groups"] if "error" in g]
    lines = [
        "# FreqEnforcer post-pitch combination sweep",
        "",
        f"Generated {date.today().isoformat()} by `tests/sweep/report.py` from a run of "
        + ("`python tests/sweep/run_sweep.py --quick` (**smoke subset, not the full sweep**)."
           if meta["quick"] else "`python tests/sweep/run_sweep.py`."),
        "This sweep measures; nothing in `server/` was changed.",
        "",
        "```bash",
        "python tests/sweep/run_sweep.py          # full sweep + probes + this report",
        "python tests/sweep/report.py             # rebuild this report from tests/sweep/out/",
        "```",
        "",
        f"- git `{env['git_head']}`, Python {env['python']}, {env['platform']}, "
        f"{env['workers']} worker processes, {summary['elapsed_min']} min wall clock",
        f"- **{len(rows)} renders** through `server.routes.audio._run_pipeline` (called directly, no HTTP), "
        f"settings built with `ProcessRequest(...).model_dump()` exactly as `/api/process` does",
        f"- Counterfactual replica fidelity: {exact}/{len(fid)} checks bit-identical to `_run_pipeline`"
        f"{'' if exact == len(fid) else ' (**MISMATCH - attribution unreliable**)'}",
        f"- librosa imported in any process: {'**YES**' if lib else 'no'}",
    ]
    if errs:
        lines.append(f"- **{len(errs)} groups crashed outside the per-render guard**: "
                     + ", ".join(g["group"] for g in errs[:5]))
    return "\n".join(lines)


def sec_thresholds(summary) -> str:
    t = summary["thresholds"]
    body = [
        ["exception / nonfinite", "any exception from `_run_pipeline`, any NaN/inf sample"],
        ["length", f"\\|len(out) − round(len(in) × stretch)\\| > {t['LENGTH_TOL_MS']:g} ms "
                   "(WORLD rounds to 5 ms frames; exact-rule count given below)"],
        ["peak", f"peak > {t['PEAK_DBFS']:g} dBFS"],
        ["f0", f"\\|median YIN f0 of the note body − target\\| > {t['F0_ERR_CENTS']:g} cents, or no pitch found"],
        ["inharm", f"inharmonic energy ratio (between target harmonics / total) worse than the input's "
                   f"by > {t['INHARM_WORSE_DB']:g} dB"],
        ["tail", f"energy in the {t['TAIL_MS']:g} ms after the source offset (× stretch) > {t['TAIL_DB']:g} dB re "
                 "note body (fixtures with a silent tail only)"],
        ["rms", f"note-body RMS drop vs input > {t['RMS_LOSS_DB']:g} dB, checked only at cleanliness ≤ "
                f"{t['RMS_LOSS_MAX_CLEAN']:g} %"],
    ]
    return ("## Pass/fail rules\n\nAll thresholds live in `tests/sweep/sweep_config.py`.\n\n"
            + table(["metric", "fails when"], body) + "\n\n"
            "**Attribution.** For every failed (render, metric) the worker asks, in order: is it "
            "*inherited* (the group's pitch-only render fails it too and the render is not worse by more "
            "than the metric's threshold)? Does one counterfactual toggle clear it - **F1** (cleanliness "
            "gets the cached f0 rescaled to the target), **F3** (low cut from the target f0), **F4** "
            "(breathiness analysed with the correct f0), **F5** (cleanliness input pre-padded, isolating "
            "E1), **F6** (cleanliness without a WORLD cache gets the correct f0 instead of its own pyin, "
            "isolating E2)? Only all toggles together (*joint*)? With all toggles on, does switching one stage off "
            "clear it (*B2* at cleanliness 100, *clean_mask* below, *breath_resynth*, *breath_intended*, "
            "*lowcut_design*), or only switching several off (*multi*)? Toggles change arguments to the "
            "unmodified server functions (`tests/sweep/counterfactual.py`).")


def sec_fixtures(summary) -> str:
    body = []
    for name, m in summary["fixtures"].items():
        d = m["detected"]
        body.append([f"`{name}`", m["kind"], f"{m['truth_note']} ({f(m['truth_f0'], 2)} Hz)",
                     f"{d.get('note_name')} ({f(d.get('freq_hz'), 1)} Hz)",
                     f(m["duration_s"], 2), "yes" if m["has_tail"] else "no",
                     f(m["input"]["inharm_db"]), m["description"]])
    return ("## Fixtures\n\nSynthetic WAVs are written to `tests/sweep/out/fixtures/`. "
            "*Detected* is what `/api/load-audio` stores in `state.detected_pitch` (the smart low cut "
            "uses it); targets are truth note + shift.\n\n"
            + table(["fixture", "kind", "truth", "detected", "dur s", "tail", "input inharm dB", "content"], body))


def sec_coverage(summary, rows) -> str:
    meta = summary["meta"]
    n_sets = Counter(s for r in rows for s in r["sets"])
    return ("## Coverage\n\n" + table(["set", "renders", "definition"], [
        ["pairwise", n_sets["pairwise"],
         f"{meta['pairwise_rows']} covering-array rows × {len(meta['fixtures'])} fixtures; "
         f"verified pair coverage {meta['pairwise_coverage']:.1%} over mode × shift × stretch × lowcut × "
         "cleanliness × hf_rollback × breathiness × hf_bias"],
        ["grid", n_sets["grid"],
         f"cleanliness {meta['cleans']} × breathiness {meta['breaths']} × shift {meta['shifts']} × "
         f"{len(meta['modes'])} modes × {len(meta['fixtures'])} fixtures (stretch 1, lowcut 0, rollback 0, hf_bias 0)"],
        ["baseline", n_sets["baseline"], "pitch-only render of every (fixture, mode, shift, stretch)"],
    ]) + "\n\nA render can belong to several sets; counts below are per set.")


def _per_value_table(rows, field, values, set_name):
    body = []
    for v in values:
        sel = [r for r in rows if set_name in r["sets"] and r[field] == v]
        if not sel:
            continue
        failing = [r for r in sel if r["fails"]]
        post = [r for r in sel if any(is_post_failure(r, m) for m in r["fails"])]
        mc = Counter(m for r in sel for m in r["fails"])
        body.append([f"`{v}`" if isinstance(v, str) else f"{v:g}" if isinstance(v, float) else v,
                     len(sel), len(failing), f"{100.0 * len(failing) / len(sel):.0f} %", len(post)]
                    + [mc.get(m, 0) or "" for m in METRIC_COLS])
    return table([field, "renders", "failing", "%", "post-pitch"] + METRIC_COLS, body)


def sec_counts(rows, summary) -> str:
    meta = summary["meta"]
    out = ["## Failure counts per parameter",
           "",
           "*failing* = renders with at least one failed metric; *post-pitch* = renders with at least one "
           "failure not inherited from the pitch-only render; metric columns count failed metrics.",
           ""]
    total = len(rows)
    failing = sum(1 for r in rows if r["fails"])
    post = sum(1 for r in rows if any(is_post_failure(r, m) for m in r["fails"]))
    mc = Counter(m for r in rows for m in r["fails"])
    exact_len = sum(1 for r in rows if r["metrics"].get("n_out") is not None
                    and r["metrics"]["n_out"] != r["metrics"]["n_expected"])
    out.append(f"**All renders:** {failing}/{total} failing ({100.0 * failing / max(1, total):.0f} %), "
               f"{post} with a post-pitch failure. By metric: "
               + ", ".join(f"{m} {mc[m]}" for m in METRIC_COLS if mc[m])
               + f". With an exact-length rule instead of ±{cfg.LENGTH_TOL_MS:g} ms, {exact_len} renders "
               "would fail on length.")
    for set_name, fields in (
            ("pairwise", [("mode", cfg.PITCH_MODES), ("shift", cfg.SHIFTS), ("stretch", cfg.STRETCHES),
                          ("lowcut", cfg.LOWCUTS), ("clean", cfg.CLEANS), ("hfrb", cfg.HF_ROLLBACKS),
                          ("breath", cfg.BREATHS), ("hfbias", cfg.HF_BIASES)]),
            ("grid", [("mode", cfg.PITCH_MODES), ("shift", cfg.SHIFTS), ("clean", cfg.CLEANS),
                      ("breath", cfg.BREATHS)])):
        out += ["", f"### {set_name.capitalize()} set", ""]
        for field, values in fields:
            out += [f"**{field}**", "", _per_value_table(rows, field, values, set_name), ""]
    out += ["### Per fixture (all sets)", ""]
    body = []
    for name in meta["fixtures"]:
        sel = [r for r in rows if r["fixture"] == name]
        mcf = Counter(m for r in sel for m in r["fails"])
        body.append([f"`{name}`", len(sel), sum(1 for r in sel if r["fails"]),
                     sum(1 for r in sel if any(is_post_failure(r, m) for m in r["fails"]))]
                    + [mcf.get(m, 0) or "" for m in METRIC_COLS])
    out.append(table(["fixture", "renders", "failing", "post-pitch"] + METRIC_COLS, body))
    return "\n".join(out)


def _row_metrics(r):
    m = r["metrics"]
    return [f(m.get("f0_cents"), 0, True), f(m.get("inharm_worse_db"), 1, True), fdb(m.get("tail_db")),
            f(m.get("rms_change_db"), 1, True), fdb(m.get("peak_dbfs"), 1, True), f(m.get("length_delta_ms"), 0, True)]


def sec_worst(rows) -> str:
    worst = sorted(rows, key=lambda r: (-post_severity(r), -r["severity"]))[:cfg.N_WORST_TABLE]
    body = []
    for i, r in enumerate(worst, 1):
        causes = "; ".join(f"{m}: {'/'.join(causes_of(r, m))}" for m in r["fails"])
        body.append([i, f"`{r['id']}`", ", ".join(r["fails"]), f(post_severity(r)), f(r["severity"])]
                    + _row_metrics(r) + [causes])
    return ("## Top 20 worst combinations\n\nRanked by **post-pitch severity**: the sum of value / threshold "
            "over the failed metrics that are *not* inherited from the pitch-only render. Overall severity "
            "(all failed metrics) is shown next to it. Exceptions count 1000 and NaN 500; f0 is capped at 20. "
            "Ranking by overall severity would instead surface pitch-mode defects, mostly sine_spectral. "
            "Id = fixture | mode | shift | stretch | lowcut | cleanliness | hf_rollback | breathiness | hf_bias. "
            "Columns: f0 error (cents), inharmonic ratio vs input (dB), tail (dB re body), body RMS change "
            "(dB), peak (dBFS), length Δ (ms).\n\n"
            + table(["#", "combination", "fails", "post sev", "all sev", "f0 ¢", "inharm Δ", "tail", "RMS Δ",
                     "peak", "len Δ", "attribution"], body))


# ---------------------------------------------------------------------------
# Bug verdicts
# ---------------------------------------------------------------------------

def _count_cause(rows, label) -> tuple[int, int]:
    n_fail, n_render = 0, 0
    for r in rows:
        hit = False
        for m in r["fails"]:
            if any(label in expand(c) for c in causes_of(r, m)):
                n_fail += 1
                hit = True
        n_render += hit
    return n_fail, n_render


def sec_b1(p, rows) -> str:
    if not p or "error" in p:
        return "### B1\n\nprobe failed:\n```\n" + (p or {}).get("error", "missing") + "\n```"
    h = p["headline"]
    n_fail, n_r = _count_cause(rows, "B1")
    by_shift = Counter()
    by_cache = Counter()
    for r in rows:
        for m in r["fails"]:
            if any("B1" in expand(c) for c in causes_of(r, m)):
                by_shift[r["shift"]] += 1
                by_cache[(r["mode"].startswith("world"), r["breath"] != 1.0)] += 1
    ok = (h["stage_db_app"] - h["stage_db_fix"] < -6.0 and "f0" in h["fails_app"]
          and "f0" not in h["fails_fix"] and n_fail > 0)
    rows_t = [[r["fixture"], f(r["shift"], 0, True), r["target"], f(r["clean"], 0),
               f(r["cached_f0_median"]), f(r["target_f0"]), f(r["stage_db_app"], 1, True),
               f(r["stage_db_fix"], 1, True), f(r["f0_cents_app"], 0, True), f(r["f0_cents_fix"], 0, True),
               ", ".join(r["fails_app"]) or "pass", ", ".join(r["fails_fix"]) or "pass"]
              for r in p["stage_rows"] if r["clean"] in (50.0, 100.0)]
    cp = [[r["clean"], r["breath"], r["f0_source"], f(r["rms_change_db"], 1, True), f(r["f0_cents"], 0, True),
           f(r["inharm_worse_db"], 1, True), ", ".join(r["fails"]) or "pass"] for r in p["cache_path"]]
    return "\n".join([
        f"### B1 - cleanliness gets the original audio's f0: **{'CONFIRMED' if ok else 'REFUTED'}**",
        "",
        "*Rule: CONFIRMED if at G3 +5 st / cleanliness 100 the cleanliness stage loses > 6 dB more with the "
        "app's f0 than with the rescaled f0, the app's output fails f0 and the rescaled one does not, and "
        "the sweep attributes failures to B1.*",
        "",
        f"- Your quick check reproduces: G3 +5 st (→ {h['target']}), world_hard, cleanliness 100 - the "
        f"cleanliness stage changes the note-body RMS by **{f(h['stage_db_app'], 1, True)} dB** with the "
        f"cached f0 ({f(h['cached_f0_median'])} Hz, the original G3) vs **{f(h['stage_db_fix'], 1, True)} dB** "
        f"with that f0 rescaled to {f(h['target_f0'])} Hz (you measured 23.7 vs 7.6 dB). Output f0 error "
        f"{f(h['f0_cents_app'], 0, True)} ¢ vs {f(h['f0_cents_fix'], 0, True)} ¢.",
        f"- In the sweep F1 alone clears **{n_fail} failed metrics in {n_r} renders**. By shift: "
        + ", ".join(f"{k:+d} st: {by_shift.get(k, 0)}" for k in cfg.SHIFTS)
        + " (shift 0 has the right f0, so ~0 is expected there).",
        "- The cache exists only for world_* modes or breathiness ≠ 1. B1 failures by (WORLD mode, "
        "breath ≠ 1): " + ", ".join(f"{'WORLD' if a else 'non-WORLD'}/{'breath≠1' if b else 'breath=1'}: "
                                     f"{by_cache.get((a, b), 0)}" for a in (True, False) for b in (True, False))
        + ". Non-WORLD modes with breath = 1 run pyin on the processed audio and are not affected.",
        "",
        table(["fixture", "shift", "target", "clean", "cached f0", "target f0", "stage dB (app)",
               "stage dB (F1)", "f0 ¢ app", "f0 ¢ F1", "fails app", "fails F1"], rows_t),
        "",
        "Same input, non-WORLD mode (praat_soft, +5 st): turning breathiness from 1.0 to 0.5 switches "
        "cleanliness from pyin-on-the-output to the cached original f0:",
        "",
        table(["clean", "breath", "cleanliness f0 source", "RMS Δ", "f0 ¢", "inharm Δ", "fails"], cp),
    ])


def sec_b2(p, rows) -> str:
    if not p or "error" in p:
        return "### B2\n\nprobe failed:\n```\n" + (p or {}).get("error", "missing") + "\n```"
    r100 = [r for r in p["rows"] if r["clean"] == 100]
    eat = all(r["harm_loss_db"] <= -3.0 for r in r100) and all(r["fwhm_over_bin"] < 1.0 for r in r100)
    ring = all(r["tail_db"] is not None and r["tail_db"] > cfg.TAIL_DB for r in r100)
    sustained = any(r["tail_late_db"] is not None and r["tail_late_db"] > cfg.TAIL_DB for r in r100)
    n_b2, n_b2r = _count_cause(rows, "B2")
    n_cm, n_cmr = _count_cause(rows, "clean_mask")
    verdict = "CONFIRMED" if eat else "REFUTED"
    body = [[r["fixture"], f(r["clean"], 0), f(r["fwhm_hz"]), f(r["fwhm_over_bin"], 2),
             f(r["harm_loss_db"], 1, True), f(r["h1_loss_db"], 1, True), f(r["harm_loss_db_pyin"], 1, True),
             fdb(r["tail_db"]), fdb(r["tail_late_db"]), f(r["inharm_db"], 1)]
            for r in p["rows"] if r["clean"] in (0, 50, 70, 80, 90, 100)]
    return "\n".join([
        f"### B2 - mask narrower than an STFT bin: **{verdict}** "
        f"(harmonic loss {'yes' if eat else 'no'}; release smear {'yes' if ring else 'no'}; "
        f"sustained ringing {'yes' if sustained else 'no'})",
        "",
        "*Rule: CONFIRMED if, with the exact f0 supplied, cleanliness 100 removes ≥ 3 dB of harmonic energy "
        "on every noise-free tone while FWHM < bin width. Ringing is reported separately: tail = 0-200 ms "
        "after offset (the sweep rule), late tail = 50-200 ms (sustained ringing).*",
        "",
        f"- At 100 % the Gaussian FWHM is 10 Hz = {r100[0]['fwhm_over_bin']:.2f} of the {p['bin_hz']:.2f} Hz bin "
        f"(Hann main lobe ±{p['hann_mainlobe_hz'] / 2:.0f} Hz). With the **exact** f0 the mask still removes "
        + ", ".join(f"{r['fixture']} {f(r['harm_loss_db'], 1, True)} dB (H1 {f(r['h1_loss_db'], 1, True)})" for r in r100)
        + " of harmonic energy. The loss depends on where each harmonic falls between bin centres (picket "
        "fence), so it is f0-dependent, and it is the same through the pyin path.",
        f"- Ringing: the 0-200 ms tail rises steadily with cleanliness, from "
        + ", ".join(f"{fdb(r['tail_db'])}" for r in p["rows"] if r["clean"] == 10) + " dB at 10 % to "
        + ", ".join(f"{fdb(r['tail_db'])} dB" for r in r100) + " at 100 %. The 50-200 ms late tail stays at "
        + ", ".join(f"{fdb(r['tail_late_db'])} dB" for r in r100)
        + ": the energy is a release smear confined to one STFT window (46 ms), not a sustained ring.",
        f"- In the sweep B2 (cleanliness 100, failure persists with every toggle and clears without "
        f"cleanliness) explains **{n_b2} failed metrics in {n_b2r} renders**. The same mechanism at "
        f"25-75 % (*clean_mask*) explains {n_cm} in {n_cmr}.",
        "",
        table(["tone", "clean", "FWHM Hz", "FWHM/bin", "harm Δ dB (exact f0)", "H1 Δ dB", "harm Δ dB (pyin)",
               "tail dB", "late tail dB", "inharm dB"], body),
    ])


def sec_b3(p, rows) -> str:
    if not p or "error" in p:
        return "### B3\n\nprobe failed:\n```\n" + (p or {}).get("error", "missing") + "\n```"
    down = [r for r in p["rows"] if r["shift"] < 0]
    over = [r for r in down if r["cut_over_f0"] > 1.0]
    big = [r for r in over if r["h1_db_app"] - r["h1_db_fix"] < -3.0]
    ok = bool(big)
    n_fail, n_r = _count_cause(rows, "B3")
    body = [[r["fixture"], r["mode"], f(r["shift"], 0, True), f(r["lowcut"], 0), f(r["detected_f0"]),
             f(r["target_f0"]), f(r["cutoff_app"]), f(r["cut_over_f0"], 2), f(r["h1_db_app"], 1, True),
             f(r["h1_db_fix"], 1, True), f(r["rms_db_app"], 1, True), ", ".join(r["fails_app"]) or "pass"]
            for r in p["rows"] if r["mode"] == "praat_soft" and r["fixture"] in ("harm_G3", "harm_C2")]
    up = [r for r in p["rows"] if r["shift"] > 0]
    up_worse = sum(1 for r in up if r["h1_db_fix"] < r["h1_db_app"] - 1.0)
    return "\n".join([
        f"### B3 - smart low cut uses the original f0: **{'CONFIRMED' if ok else 'REFUTED'}**",
        "",
        "*Rule: CONFIRMED if on some downward shift the cutoff exceeds the new fundamental and the "
        "fundamental (H1) loses > 3 dB more than with the cutoff computed from the target f0.*",
        "",
        f"- On downward shifts the cutoff is above the new fundamental in {len(over)}/{len(down)} probe cases "
        f"(up to {max((r['cut_over_f0'] for r in down), default=0):.2f} × f0 at −12 st / 100 %). H1 then drops by "
        f"up to {f(min((r['h1_db_app'] for r in down), default=0), 1, True)} dB vs the pitch-only render, against "
        f"{f(min((r['h1_db_fix'] for r in down), default=0), 1, True)} dB when the cutoff comes from the target.",
        f"- The reverse happens on upward shifts: the cutoff is too *low*, so the app cuts less than "
        f"intended ({up_worse}/{len(up)} cases where the target-f0 cutoff would remove > 1 dB more H1).",
        f"- The sweep rules rarely catch it. Losing H1 changes body RMS by only "
        f"{f(min((r['rms_db_app'] for r in down), default=0), 1, True)} dB at worst, so F3 alone clears "
        f"**{n_fail} failed metrics in {n_r} renders**. The damage is spectral (a thin, fundamental-less "
        "low end) rather than a level drop the rules measure.",
        "",
        table(["fixture", "mode", "shift", "lowcut", "detected f0", "target f0", "cutoff", "cutoff/f0",
               "H1 Δ app", "H1 Δ F3", "RMS Δ app", "fails app"], body),
    ])


def sec_b4(p, rows) -> str:
    if not p or "error" in p:
        return "### B4\n\nprobe failed:\n```\n" + (p or {}).get("error", "missing") + "\n```"
    calls = p["calls"]
    second = any(c["fn"] == "harvest" and not c["kwargs"] for k in calls for c in k["calls"])
    n_fail, n_r = _count_cause(rows, "B4")
    n_rs, n_rsr = _count_cause(rows, "breath_resynth")
    rng = p["range"]
    range_bad = [r for r in rng if (r["app_harvest"]["fails"] and "f0" in r["app_harvest"]["fails"]
                                    and "f0" not in r["correct_f0"]["fails"])
                 or ((r["app_harvest"]["inharm_worse_db"] or 0) - (r["correct_f0"]["inharm_worse_db"] or 0) > 6)]
    div = p["div0"]
    div_warn = all(any("divide by zero" in w for w in d["warnings"]) for d in div if d["breath"] == 0.0)
    div_nan = any(d["nonfinite"] for d in div)
    call_rows = [[k["mode"], k.get("breathiness"),
                  " → ".join(c["fn"] + (f"({', '.join(f'{a}={b:g}' for a, b in c['kwargs'].items())})"
                                        if c["kwargs"] else ("()" if c["fn"] == "harvest" else ""))
                             for c in k["calls"]) or "(no WORLD calls)"] for k in calls]
    rng_rows = [[r["fixture"], f(r["shift"], 0, True), f(r["target_f0"]),
                 f(r["harvest_median_f0"]), f(r["harvest_voiced_frac"], 2)]
                + [f"{f(r[k]['f0_cents'], 0, True)} ¢ / {f(r[k]['inharm_worse_db'], 1, True)} dB"
                   for k in ("app_harvest", "dio_50_500", "correct_f0")] for r in rng]
    idn = [[r["fixture"], f(r["clean"], 0), fdb(r["residual_db"], 1), f(r["inharm_db_b1"], 1),
            f(r["inharm_db_b099"], 1)] for r in p["identity"]]
    idn_res = [r["residual_db"] for r in p["identity"]]
    idn_dinh = [r["inharm_db_b099"] - r["inharm_db_b1"] for r in p["identity"]
                if r["inharm_db_b099"] is not None and r["inharm_db_b1"] is not None]
    dz = [[d["fixture"], d["breath"], d["hf_bias"], d["zero_exponent_bins"], "; ".join(d["warnings"]) or "–",
           d["nonfinite"], fdb(d["residual_vs_0.01_db"], 1)] for d in div]
    ok = second and bool(range_bad)
    misses = []
    for r in rng:
        hm, tf0 = r["harvest_median_f0"], r["target_f0"]
        if hm is None or abs(1200.0 * math.log2(hm / tf0)) > 50.0:
            misses.append(f"{r['fixture']} {f(r['shift'], 0, True)} (target {f(tf0)} Hz → harvest "
                          f"{'no pitch' if hm is None else f(hm) + ' Hz'}, voiced {f(r['harvest_voiced_frac'], 2)})")
    return "\n".join([
        f"### B4 - second WORLD pass with harvest's default range; 1/0 at breathiness 0: "
        f"**{'CONFIRMED' if ok else 'REFUTED'}** (divide by zero: "
        f"**{'CONFIRMED, benign' if div_warn and not div_nan else 'CONFIRMED, produces NaN' if div_nan else 'REFUTED'}**)",
        "",
        "*Rule: CONFIRMED if instrumentation shows `harvest` called without a range after the pipeline's own "
        "analysis, and some fixture fails with harvest but passes with the correct-f0 analysis. Divide by zero: "
        "CONFIRMED if numpy's divide-by-zero warning fires; benign if the output stays finite.*",
        "",
        "pyworld calls logged during one `_run_pipeline` (G3 +5 st, cleanliness 50):",
        "",
        table(["mode", "breath", "pyworld calls in order"], call_rows),
        "",
        "- With breath ≠ 1 every render runs a third analysis and a second synthesis. For non-WORLD modes the "
        "step-0 `sp`/`ap` is computed but then thrown away (`apply_breathiness(world_cache=None)`), and its f0 "
        "only reaches cleanliness, where it causes B1.",
        f"- Range: harvest's default 71-800 Hz misses the pitch in {len(misses)}/{len(rng)} probe signals: "
        + "; ".join(misses) + ". "
        f"{len(range_bad)}/{len(rng)} cases fail f0 with harvest but not with the correct f0, or are > 6 dB "
        "more inharmonic. The dio 50-500 column shows whether the range used elsewhere would be enough.",
        f"- Sweep: F4 alone clears **{n_fail} failed metrics in {n_r} renders**. Another {n_rs} in {n_rsr} "
        "renders persist with the correct f0 and clear only without breathiness: the resynthesis itself.",
        "",
        "Breathiness 0.5 on the praat_soft output (cell = f0 error / inharmonic Δ):",
        "",
        table(["fixture", "shift", "target f0", "harvest f0", "harvest voiced", "app (harvest)", "dio 50-500",
               "correct f0"], rng_rows),
        "",
        "Near-identity resynthesis (world_hard, shift 0): breathiness 0.99 vs 1.0 (1.0 skips the stage):",
        "",
        table(["fixture", "clean", "waveform residual dB", "inharm dB at 1.0", "inharm dB at 0.99"], idn),
        "",
        f"A 1 % change of the setting rewrites the waveform: the residual is {fdb(min(idn_res))} to "
        f"{fdb(max(idn_res))} dB re signal, because the stage re-synthesises everything. The inharmonic ratio "
        f"moves {f(min(idn_dinh), 1, True)} to {f(max(idn_dinh), 1, True)} dB, which bounds how much the second "
        "pass on its own undoes cleanliness when the f0 is right.",
        "",
        "Breathiness 0 → `effective_amount` = 0 → `ap ** (1/0)`:",
        "",
        table(["fixture", "breath", "hf_bias", "bins with exponent 1/0", "warnings", "NaN/inf samples",
               "residual vs breath 0.01 (dB)"], dz),
        "",
        "`ap ** inf` is 0 for every ap < 1, so amount 0 behaves as the limit of small amounts (fully periodic). "
        "The division is real but does not corrupt the output.",
    ])


def sec_b5(p, rows) -> str:
    if not p or "error" in p:
        return "### B5\n\nprobe failed:\n```\n" + (p or {}).get("error", "missing") + "\n```"
    cases = p["cases"]
    coll = [c for c in cases if c["B"] == "lead_A4"]
    ctrl = [c for c in cases if c["B"] == "nolead_A4"]
    changed = [c for c in coll if c["hash_equal"] and c["cache_hit"]
               and (c["len_warm"] != c["len_cold"] or (c["residual_db"] or -300) > -60)]
    ctrl_ok = all(not c["cache_hit"] and c["max_abs_diff"] == 0.0 for c in ctrl)
    reach = p["reachability"]
    reachable = not (reach["load_audio"]["resets_cache"] and reach["load_audio_upload"]["resets_cache"])
    ok = bool(changed)
    len_d = sorted({round(1000.0 * (c["len_warm"] - c["len_cold"]) / cfg.SR) for c in changed
                    if c["len_warm"] is not None and c["len_cold"] is not None and c["len_warm"] != c["len_cold"]})
    body = [[c["B"], c["mode"], f"cl {c.get('cleanliness_percent', 0):g} / br {c.get('breathiness', 1):g}",
             c["hash_equal"], c["cache_hit"], f"{c['len_warm']} / {c['len_cold']}", fdb(c["residual_db"], 1),
             f"{f(c['warm']['f0_cents'], 0, True)} / {f(c['cold']['f0_cents'], 0, True)}",
             ", ".join(c["fails_warm"]) or "pass", ", ".join(c["fails_cold"]) or "pass",
             c["exception_warm"] or "–"] for c in cases]
    rr = [[f"`{k}`", "yes" if v["resets_cache"] else "no", "yes" if v["calls_cache"] else "no"] for k, v in reach.items()]
    return "\n".join([
        f"### B5 - cache keyed on md5 of the first 1000 samples: **{'CONFIRMED' if ok else 'REFUTED'}**"
        f"{' (latent: not reachable through the current endpoints)' if ok and not reachable else ''}",
        "",
        "*Rule: CONFIRMED if B with A's identical leading silence hits A's cache and its output differs from "
        "a cold-cache render of B (different length, or residual > −60 dB). Reachability is read from the "
        "endpoint source.*",
        "",
        f"- A = `lead_G3` (1.8 s), B = `lead_A4` (1.5 s), both starting with 300 ms of digital zeros. "
        f"{len(changed)}/{len(coll)} settings hit A's cache and give a different B. "
        + (f"For world_* modes B is rendered on A's time axis, so its output is "
           f"**{', '.join(f'{d:+d}' for d in len_d)} ms** longer than a cold render. " if len_d else "")
        + "The f0 column shows the pitch damage. "
        f"Control (B without leading silence): {'no cache hit, bit-identical to cold' if ctrl_ok else 'UNEXPECTED'}.",
        f"- {'Reachable' if reachable else 'Not reachable today'}: `/api/load-audio` and `/api/load-audio-upload` "
        "both reset `state.world_cache` before anything else, and `/api/process` and multisample always reuse "
        "the loaded `state.original_audio`. The collision fires only if a future caller runs `_run_pipeline` "
        "/ `_world_cache_for` on other audio without a load, e.g. batch processing or a trimmed variant.",
        "",
        table(["B", "mode", "post", "hash equal", "cache hit", "len warm / cold", "residual dB",
               "f0 ¢ warm / cold", "fails warm", "fails cold", "exception"], body),
        "",
        table(["endpoint", "resets cache", "runs pipeline"], rr),
    ])


def sec_e1(p, rows, summary) -> str:
    out = ["## Other findings (outside B1-B5)", ""]
    if p and "error" not in p:
        n_fail, n_r = _count_cause(rows, "E1")
        body = [[r["fixture"], f(r["clean"], 0), r["nola_warning"], f(r["first_nonzero_ms"], 2),
                 f(20 * math.log10(r["peak_app"]), 1, True), f(r["peak_at_ms"], 2),
                 f(20 * math.log10(r["peak_app_after_50ms"]), 1, True), f(20 * math.log10(r["peak_padded"]), 1, True),
                 f(20 * math.log10(r["input_peak"]), 1, True)] for r in p["rows"]]
        # How often the spike reaches the output, by mode and breathiness (sweep data)
        e1_body = []
        for mode in cfg.PITCH_MODES:
            for b1 in (True, False):
                sel = [r for r in rows if r["mode"] == mode and r["clean"] > 0 and (r["breath"] == 1.0) == b1
                       and r["fixture"] != "lead_G3" and r["metrics"].get("peak_dbfs") is not None]
                if not sel:
                    continue
                cred = [r for r in sel if "E1" in sum((expand(c) for c in causes_of(r, "peak")), [])
                        and "peak" in r["fails"]]
                pk = [r["metrics"]["peak_dbfs"] for r in sel]
                e1_body.append([f"`{mode}`", "1" if b1 else "≠ 1", len(sel), len(cred),
                                f(float(np.median(pk)), 1, True), f(max(pk), 1, True)])
        out += [
            "### E1 - cleanliness ISTFT blows up the first samples of the file",
            "",
            "`apply_cleanliness` pads n_fft zeros at the end only. Its `scipy.signal.istft(..., boundary=False)` "
            "then divides the first samples by a window sum of ~0 (scipy warns *NOLA condition failed* on every "
            "call). Whatever the mask did to those first samples gets multiplied by up to ~1/w[n]. Any file "
            "whose audio starts within the first STFT frame spikes, and real recordings usually do. Leading "
            "silence avoids it. Pre-padding the input (F5) removes it completely.",
            "",
            f"- The sweep credits E1 with **{n_fail} failed metrics in {n_r} renders** (mostly *peak*).",
            "- Severity grows with cleanliness because a narrower mask changes those edge samples more.",
            "",
            table(["fixture", "clean", "NOLA warning", "audio starts at ms", "peak dBFS (app)", "peak at ms",
                   "peak after 50 ms", "peak dBFS (pre-padded)", "input peak"], body),
            "",
            "In the sweep (cleanliness > 0, all fixtures except `lead_G3`), how often the spike survives to the "
            "output. A breathiness pass after cleanliness re-synthesises the audio and mostly hides it. WORLD "
            "modes start their output more gently, so the edge samples the mask disturbs are smaller:",
            "",
            table(["mode", "breath", "renders", "peak failures credited to E1", "median peak dBFS",
                   "max peak dBFS"], e1_body),
            "",
        ]
    gold = cfg.ROOT / "tests" / "golden" / "test_2s_C4" / "pipe_mode_sine_spectral__na__F4.wav"
    if gold.exists():
        import soundfile as sf
        from scipy.signal import find_peaks
        y, sr = sf.read(str(gold))
        a, b = int(0.3 * sr), int(1.7 * sr)
        spec = np.abs(np.fft.rfft(y[a:b] * np.hanning(b - a), 1 << 17))
        fr = np.fft.rfftfreq(1 << 17, 1.0 / sr)
        idx, _ = find_peaks(spec, distance=20)
        top = sorted(idx[np.argsort(spec[idx])[::-1][:6]])
        pk = ", ".join(f"{fr[i]:.1f} Hz ({20 * math.log10(spec[i] / spec.max()):+.0f} dB)" for i in top)
        out += ["### sine_spectral output is not harmonic at the target (pitch stage, golden included)", "",
                "Most of sine_spectral's pitch-only renders miss the target note or fail the inharmonic rule "
                "(tables below). The committed golden reference has the same defect, so the regression test "
                "protects it. Strongest spectral peaks of `tests/golden/test_2s_C4/pipe_mode_sine_spectral__na__F4.wav` "
                f"(target F4 = 349.2 Hz, harmonics 698.5, 1047.7 Hz…): {pk}.", ""]
    # Pitch-stage (inherited) failures by mode and metric
    inh = defaultdict(Counter)
    for r in rows:
        for m in r["fails"]:
            if all(c == "inherited" for c in causes_of(r, m)):
                inh[r["mode"]][m] += 1
    body = [[f"`{mode}`"] + [inh[mode].get(m, 0) or "" for m in METRIC_COLS] for mode in cfg.PITCH_MODES if mode in inh]
    out += ["### Pitch-stage failures (inherited, not post-pitch)", "",
            "Failures the pitch-only render already has, and the post stages do not make worse beyond the "
            "metric's threshold:", "",
            table(["mode"] + METRIC_COLS, body), ""]

    # Pitch-only renders: f0 misses and length by mode x stretch
    base = [r for r in rows if "baseline" in r["sets"]]
    f0_miss = defaultdict(list)
    for r in base:
        if "f0" in r["fails"]:
            f0_miss[r["mode"]].append(f"{r['fixture']} {r['shift']:+d}")
    body = [[f"`{m}`", len(v), ", ".join(sorted(set(v))[:12]) + (" …" if len(set(v)) > 12 else "")]
            for m, v in sorted(f0_miss.items())]
    out += ["### Pitch-only renders that miss the target note", "",
            table(["mode", "renders", "fixture shift"], body) if body else "none", ""]
    lens = defaultdict(list)
    for r in base:
        if r["metrics"].get("length_delta_ms") is not None:
            lens[(r["mode"], r["stretch"])].append(r["metrics"]["length_delta_ms"])
    body = [[f"`{m}`", f(s, 1)] + [f(float(np.median(v)), 1, True), f(float(np.min(v)), 1, True),
                                    f(float(np.max(v)), 1, True)] for (m, s), v in sorted(lens.items())]
    out += ["### Output length vs expected (pitch-only renders, ms)", "",
            table(["mode", "stretch", "median Δ", "min Δ", "max Δ"], body), ""]

    wrong = [f"`{n}`: truth {m['truth_note']}, detected {m['detected'].get('note_name')} "
             f"({f(m['detected'].get('freq_hz'))} Hz)" for n, m in summary["fixtures"].items()
             if m["detected"].get("note_name") != m["truth_note"]]
    out += ["### Load-time pitch detection (feeds the smart low cut)", "",
            ("`get_pitch_summary` (pyin 50-500 Hz) misreads: " + "; ".join(wrong) + ". "
             "Every low-cut cutoff on those fixtures is computed from the wrong f0, independently of B3.")
            if wrong else "All fixtures detected at their true note.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Root-cause ranking
# ---------------------------------------------------------------------------

def rank_causes(rows) -> list[dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"any": 0, "sole": 0, "renders": set()})
    for r in rows:
        for m in r["fails"]:
            cs = causes_of(r, m)
            labels = set()
            for c in cs:
                if c == "inherited":
                    labels.add(f"pitch:{m}")
                else:
                    labels.update(expand(c))
            for lab in labels:
                st = stats[lab]
                st["any"] += 1
                st["renders"].add(r["id"])
                if len(labels) == 1:
                    st["sole"] += 1
    out = []
    for lab, st in stats.items():
        out.append({"cause": lab, "any": st["any"], "sole": st["sole"], "renders": len(st["renders"])})
    return sorted(out, key=lambda d: (-d["any"], -d["sole"]))


PITCH_TEXT = {
    "pitch:tail": "pitch stage: energy past the source offset (release smear of the pitch mode) - inherited tail",
    "pitch:length": "pitch/stretch stage: output length off by more than the tolerance (see length table)",
    "pitch:f0": "pitch stage: mode misses the target note (see pitch-stage table)",
    "pitch:inharm": "pitch stage: mode adds inharmonic energy",
    "pitch:peak": "pitch stage: mode output above 0 dBFS (e.g. onset spikes, hot real fixture)",
    "pitch:rms": "pitch stage: level drop",
    "pitch:exception": "pitch stage: exception",
    "pitch:nonfinite": "pitch stage: NaN/inf",
}


def sec_ranking(rows) -> str:
    ranked = rank_causes(rows)
    total = sum(len(r["fails"]) for r in rows)
    body = []
    for i, d in enumerate(ranked, 1):
        lab = d["cause"]
        text = CAUSE_TEXT.get(lab) or PITCH_TEXT.get(lab) or lab
        body.append([i, f"**{lab}**" if lab in ("B1", "B2", "B3", "B4", "E1", "E2") else lab, d["any"], d["sole"],
                     d["renders"], f"{100.0 * d['any'] / max(1, total):.0f} %", text])
    post = [d for d in ranked if not d["cause"].startswith("pitch") and d["cause"] != "breath_intended"]
    post_total = sum(1 for r in rows for m in r["fails"] if is_post_failure(r, m))
    body_post = [[i, d["cause"], d["any"], d["sole"], d["renders"],
                  f"{100.0 * d['any'] / max(1, post_total):.0f} %"] for i, d in enumerate(post, 1)]
    return ("## Root causes ranked by failures explained\n\n"
            "### Post-pitch defects only\n\n"
            f"{post_total} failed (render, metric) pairs belong to the post-pitch stages: they are neither "
            "inherited from the pitch-only render nor measured on a pitch the stage never received. "
            "*breath_intended* (breathiness > 1 failing the inharmonic rule by design) is left out of "
            "this view.\n\n"
            + table(["rank", "cause", "explains", "sole", "renders", "share of post-pitch failures"], body_post)
            + "\n\n### All causes\n\n"
            f"{total} failed (render, metric) pairs in total. *explains* counts every failure the cause is "
            "credited with, alone or jointly. *sole* counts failures it is the only credited cause for. "
            "Columns overlap, so they do not sum to the total.\n\n"
            + table(["rank", "cause", "explains", "sole", "renders", "share", "what"], body))


# ---------------------------------------------------------------------------
# WAVs of the worst renders
# ---------------------------------------------------------------------------

def save_worst(rows) -> list[dict]:
    import soundfile as sf
    import fixtures
    import worker
    out_dir = cfg.OUT_DIR / "worst"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.wav"):
        old.unlink()
    picked, per_mode, per_metric = [], Counter(), Counter()
    for r in sorted(rows, key=lambda r: (-post_severity(r), -r["severity"])):
        if not post_exceed(r) or r["traceback"] or r["metrics"].get("nonfinite"):
            continue
        dm = dominant(r)
        if per_mode[r["mode"]] >= cfg.WORST_PER_MODE_CAP or per_metric[dm] >= 4:
            continue
        picked.append(r)
        per_mode[r["mode"]] += 1
        per_metric[dm] += 1
        if len(picked) >= cfg.N_WORST_WAVS:
            break
    saved = []
    for i, r in enumerate(picked, 1):
        fx = fixtures.get(r["fixture"])
        post = {"clean_lowcut_percent": r["lowcut"], "cleanliness_percent": r["clean"],
                "clean_hf_rollback_percent": r["hfrb"], "breathiness": r["breath"], "hf_bias": r["hfbias"]}
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", r["id"].replace("|", "__").replace("+", "p")).strip("_")
        files = {}
        for tag, p in (("", post), ("__pitch_only", dict(cfg.NEUTRAL_POST))):
            s = worker.make_settings(r["mode"], r["target_note"], r["stretch"], p)
            y, *_ = worker.run_pipeline_once(fx, s, fixtures.detected(r["fixture"]))
            if y is None:
                continue
            y = np.clip(np.nan_to_num(np.asarray(y, dtype=np.float64)), -1.0, 1.0).astype(np.float32)
            name = f"{i:02d}_{slug}{tag}.wav"
            sf.write(str(out_dir / name), y, fx.sr, subtype="FLOAT")
            files[tag or "render"] = name
        saved.append({"rank": i, "id": r["id"], "fails": r["fails"], "dominant": dominant(r),
                      "peak_dbfs": r["metrics"].get("peak_dbfs"), "files": files,
                      "causes": {m: causes_of(r, m) for m in r["fails"]}})
    return saved


def sec_wavs(saved, max_peak) -> str:
    body = [[s["rank"], f"`{s['files'].get('render', '–')}`", ", ".join(s["fails"]), s["dominant"],
             fdb(s["peak_dbfs"], 1, True), "; ".join(f"{m}: {'/'.join(c)}" for m, c in s["causes"].items())]
            for s in saved]
    return ("## Listening: the 10 worst renders\n\n"
            "In `tests/sweep/out/worst/`, each next to a `…__pitch_only.wav` of the same fixture, mode, shift "
            "and stretch for A/B. Selected by post-pitch severity, at most "
            f"{cfg.WORST_PER_MODE_CAP} per pitch mode and 4 per dominant post-pitch metric so the list is not "
            "ten copies of one failure. **Samples are clipped to ±1.0** so E1 spikes cannot hurt ears or speakers (the "
            f"loudest render in the sweep peaks at {f(max_peak, 1, True)} dBFS). The true peak is in the table.\n\n"
            + table(["#", "file", "fails", "dominant", "true peak dBFS", "attribution"], body))


# ---------------------------------------------------------------------------

def build(save_wavs: bool = True) -> None:
    rows, summary, probes = load()
    set_baselines(rows)
    saved = save_worst(rows) if save_wavs else []
    parts = [
        sec_header(summary, rows),
        sec_ranking(rows),
        sec_thresholds(summary),
        sec_fixtures(summary),
        sec_coverage(summary, rows),
        "## Suspected bugs\n",
        sec_b1(probes.get("B1"), rows),
        sec_b2(probes.get("B2"), rows),
        sec_b3(probes.get("B3"), rows),
        sec_b4(probes.get("B4"), rows),
        sec_b5(probes.get("B5"), rows),
        sec_e1(probes.get("E1"), rows, summary),
        sec_worst(rows),
        sec_counts(rows, summary),
        sec_wavs(saved, max((r["metrics"].get("peak_dbfs") or -300.0) for r in rows)) if saved else "",
    ]
    cfg.REPORT_PATH.write_text("\n\n".join(p for p in parts if p) + "\n", encoding="utf-8")
    print(f"wrote {cfg.REPORT_PATH}")


if __name__ == "__main__":
    build(save_wavs="--no-wavs" not in sys.argv)
