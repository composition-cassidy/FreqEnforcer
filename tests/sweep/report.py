"""Build docs/SWEEP_REPORT.md from the latest run (tests/sweep/out/), the frozen
pre-fix baseline (tests/sweep/baseline/prefix.json.gz), the pass-rate history
(tests/sweep/history.json) and the regenerated-golden log
(tests/sweep/intentional_changes.json).

    python tests/sweep/report.py            # rebuild, re-render the A/B WAVs
    python tests/sweep/report.py --no-wavs  # rebuild text only
"""

from __future__ import annotations

import gzip
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date

import numpy as np

import classify
import sweep_config as cfg

METRIC_COLS = cfg.METRICS
N_PREV_WORST = 30

CAUSE_TEXT = {
    # pre-fix labels (counterfactual harness)
    "B1": "cleanliness masks the ORIGINAL f0's harmonics (cached WORLD f0 of the input)",
    "B2": "cleanliness 100 %: 10 Hz mask < 21.5 Hz STFT bin, even with correct f0",
    "clean_mask": "cleanliness 25-75 % mask with correct f0",
    "B3": "smart low cut keyed to the original f0 (state.detected_pitch)",
    "B4": "breathiness re-analyses with harvest (default 71-800 Hz)",
    "breath_resynth": "breathiness second WORLD resynthesis itself",
    "E1": "cleanliness ISTFT start-of-file blow-up (no leading pad, NOLA)",
    "E2": "cleanliness's own pyin f0 wrong (50-500 Hz range)",
    "lowcut_design": "smart low cut with correct f0",
    # stage labels (current harness)
    "clean": "cleanliness stage (failure clears with cleanliness off)",
    "lowcut": "smart low cut stage (clears with low cut off)",
    "breath": "breathiness < 1 (clears with breathiness 1)",
    "breath_intended": "breathiness > 1 adds aperiodicity by design (fails the inharmonic rule)",
    "unexplained": "no single stage switched off clears it",
}
PITCH_TEXT = {
    "pitch:tail": "pitch stage: energy past the source offset (the mode's release smear)",
    "pitch:length": "pitch/stretch stage: output length off by more than the tolerance",
    "pitch:f0": "pitch stage: mode misses the target note",
    "pitch:inharm": "pitch stage: mode adds inharmonic energy",
    "pitch:peak": "pitch stage: output above 0 dBFS (onset spikes, hot real fixture)",
    "pitch:rms": "pitch stage: level drop",
    "pitch_miss": "pitch stage missed the target note; f0/inharm after it are measured against a pitch "
                  "the post stages never received",
}


# ---------------------------------------------------------------------------
# Loading / formatting
# ---------------------------------------------------------------------------

def load_current():
    rows = [json.loads(line) for line in open(cfg.OUT_DIR / "results.jsonl")]
    summary = json.loads((cfg.OUT_DIR / "summary.json").read_text())
    pp = cfg.OUT_DIR / "probes.json"
    return rows, summary, (json.loads(pp.read_text()) if pp.exists() else {})


def load_baseline(tag: str = "prefix") -> dict | None:
    p = cfg.BASELINE_DIR / f"{tag}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


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


def pct(n, d):
    return f"{100.0 * n / max(1, d):.1f} %"


def labels_of(cl, r, m) -> set[str]:
    out = set()
    for c in cl.causes(r, m):
        out.update([f"pitch:{m}"] if c == "inherited" else classify.expand(c))
    return out


def rank_causes(cl, rows, post_only: bool) -> list[dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"any": 0, "sole": 0, "renders": set()})
    for r in rows:
        for m in r["fails"]:
            if post_only and not cl.is_post(r, m):
                continue
            labs = labels_of(cl, r, m)
            for lab in labs:
                st = stats[lab]
                st["any"] += 1
                st["renders"].add(r["id"])
                st["sole"] += len(labs) == 1
    return sorted(({"cause": k, "any": v["any"], "sole": v["sole"], "renders": len(v["renders"])}
                   for k, v in stats.items()), key=lambda d: (-d["any"], -d["sole"]))


def metric_cells(m: dict) -> list:
    return [f(m.get("f0_cents"), 0, True), f(m.get("inharm_worse_db"), 1, True), fdb(m.get("tail_db")),
            f(m.get("rms_change_db"), 1, True), fdb(m.get("peak_dbfs"), 1, True),
            f(m.get("length_delta_ms"), 0, True)]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def sec_header(summary, rows) -> str:
    env, meta = summary["env"], summary["meta"]
    lib = any(g.get("librosa") for g in summary["groups"]) or env.get("librosa_in_parent")
    errs = [g for g in summary["groups"] if "error" in g]
    lines = [
        "# FreqEnforcer post-pitch combination sweep",
        "",
        f"Generated {date.today().isoformat()} by `tests/sweep/report.py`. The latest run is "
        + ("a `--quick` **smoke subset, not the full sweep**." if meta["quick"] else "a full sweep.")
        + " The sweep is the acceptance test for the post-pitch pipeline (smart low cut, cleanliness, "
        "breathiness); its thresholds have not changed since the pre-fix run.",
        "",
        "```bash",
        "python tests/sweep/run_sweep.py --tag <label>   # full sweep + probes + this report, adds a history entry",
        "python tests/sweep/report.py                    # rebuild this report from tests/sweep/out/",
        "python -m pytest tests/test_pipeline_combos.py  # the 30 previous-worst combinations + cache collision",
        "```",
        "",
        f"- Latest run: git `{env['git_head']}`, Python {env['python']}, {env['platform']}, "
        f"{env['workers']} worker processes, {summary['elapsed_min']} min, **{len(rows)} renders** through "
        "`server.routes.audio._run_pipeline` with settings built by `ProcessRequest(...).model_dump()`.",
        f"- librosa imported in any process: {'**YES**' if lib else 'no'}",
    ]
    if errs:
        lines.append(f"- **{len(errs)} groups crashed outside the per-render guard**: "
                     + ", ".join(g["group"] for g in errs[:5]))
    return "\n".join(lines)


def sec_history(hist) -> str:
    body = []
    for h in hist:
        top = ", ".join(f"{k} {v}" for k, v in list(h.get("post_failures_by_cause", {}).items())[:4]) or "–"
        body.append([f"**{h['tag']}**", f"`{h['git_head']}`" + (" (dirty)" if h.get("server_or_ui_dirty") else ""),
                     h["date"], h["n"], f"{h['raw_pct']:.1f} %", f"{h['post_pct']:.1f} %",
                     f"{h['post_ex_pct']:.1f} %", h["post_failures"], top])
    return ("## Pass rate after each change\n\n"
            "One row per full sweep (`tests/sweep/history.json`). *raw* = renders with no failed metric. "
            "*post-pitch* = renders with no failure caused after the pitch stage: failures inherited from the "
            "pitch-only render, and f0/inharm failures where the pitch stage already missed the note, are "
            "excluded. *excl. intended* also allows breathiness > 1 failing the inharmonic rule, which is "
            "what that setting is for.\n\n"
            + table(["run", "commit", "date", "renders", "raw", "post-pitch", "post-pitch excl. intended",
                     "post-pitch failures", "top post-pitch causes"], body))


def sec_before_after(rows, cl, base, bcl) -> str:
    brows = base["rows"]
    out = ["## Before / after (pre-fix vs latest run)", ""]
    # metric counts
    body = []
    for m in METRIC_COLS:
        b_all = sum(m in r["fails"] for r in brows)
        a_all = sum(m in r["fails"] for r in rows)
        b_post = sum(m in bcl.post_fails(r) for r in brows)
        a_post = sum(m in cl.post_fails(r) for r in rows)
        if b_all or a_all:
            body.append([m, b_all, a_all, b_post, a_post])
    bp, ap = bcl.pass_rates(brows), cl.pass_rates(rows)
    out += ["Failed metrics (counted per render):", "",
            table(["metric", "all, before", "all, after", "post-pitch, before", "post-pitch, after"], body),
            "",
            f"Renders passing: raw **{bp['raw_pct']:.1f} % → {ap['raw_pct']:.1f} %**, post-pitch "
            f"**{bp['post_pct']:.1f} % → {ap['post_pct']:.1f} %**, post-pitch excl. intended "
            f"**{bp['post_ex_pct']:.1f} % → {ap['post_ex_pct']:.1f} %**.", ""]

    # fixed / regressed renders
    bmap = {r["id"]: r for r in brows}
    fixed = regressed = still = 0
    reg_rows = []
    for r in rows:
        b = bmap.get(r["id"])
        if b is None:
            continue
        bf, af = bcl.post_ex_fails(b), cl.post_ex_fails(r)
        if bf and not af:
            fixed += 1
        elif af and not bf:
            regressed += 1
            reg_rows.append((r, b))
        elif af and bf:
            still += 1
    out += [f"Per render (post-pitch, excl. intended): **{fixed} fixed**, **{regressed} newly failing**, "
            f"{still} failing before and after.", ""]
    if reg_rows:
        reg_rows.sort(key=lambda t: -cl.post_severity(t[0]))
        out += ["Newly failing renders (worst 20):", "",
                table(["combination", "fails now", "causes now", "f0 ¢", "inharm Δ", "tail", "RMS Δ", "peak", "len Δ"],
                      [[f"`{r['id']}`", ", ".join(cl.post_ex_fails(r)),
                        "; ".join(f"{m}: {'/'.join(cl.causes(r, m))}" for m in cl.post_ex_fails(r))]
                       + metric_cells(r["metrics"]) for r, _b in reg_rows[:20]]), ""]

    # causes before/after
    bc = {d["cause"]: d["any"] for d in rank_causes(bcl, brows, True)}
    ac = {d["cause"]: d["any"] for d in rank_causes(cl, rows, True)}
    keys = sorted(set(bc) | set(ac), key=lambda k: -(bc.get(k, 0) + ac.get(k, 0)))
    out += ["Post-pitch failures by cause. The pre-fix harness named bugs through counterfactual re-renders "
            "(B1-B4, E1, E2); the current harness names the stage whose removal clears the failure:", "",
            table(["cause", "before", "after", "meaning"],
                  [[k, bc.get(k, 0) or "", ac.get(k, 0) or "", CAUSE_TEXT.get(k, PITCH_TEXT.get(k, ""))]
                   for k in keys]), ""]

    # previous worst 30
    amap = {r["id"]: r for r in rows}
    worst = sorted(brows, key=lambda r: (-bcl.post_severity(r), -r["severity"]))[:N_PREV_WORST]
    body = []
    for i, b in enumerate(worst, 1):
        a = amap.get(b["id"])
        body.append([i, f"`{b['id']}`", ", ".join(bcl.post_fails(b)) or "pass",
                     (", ".join(cl.post_fails(a)) or "**pass**") if a else "not run",
                     f"{f(b['metrics'].get('peak_dbfs'), 1, True)} → {f((a or {}).get('metrics', {}).get('peak_dbfs'), 1, True)}",
                     f"{f(b['metrics'].get('f0_cents'), 0, True)} → {f((a or {}).get('metrics', {}).get('f0_cents'), 0, True)}",
                     f"{f(b['metrics'].get('inharm_worse_db'), 1, True)} → {f((a or {}).get('metrics', {}).get('inharm_worse_db'), 1, True)}",
                     f"{fdb(b['metrics'].get('tail_db'))} → {fdb((a or {}).get('metrics', {}).get('tail_db'))}",
                     "; ".join(f"{m}: {'/'.join(cl.causes(a, m))}" for m in a["fails"]) if a else ""])
    out += [f"The {N_PREV_WORST} worst pre-fix combinations by post-pitch severity (these are the permanent "
            "cases in `tests/test_pipeline_combos.py`), before → after:", "",
            table(["#", "combination", "post-pitch fails before", "post-pitch fails after", "peak dBFS",
                   "f0 ¢", "inharm Δ dB", "tail dB", "all failures now: cause"], body)]
    return "\n".join(out)


def sec_remaining(rows, cl) -> str:
    out = ["## Remaining failures", ""]
    inh = defaultdict(Counter)
    miss = Counter()
    intended = Counter()
    post = []
    for r in rows:
        for m in r["fails"]:
            cs = cl.causes(r, m)
            if cs == ["inherited"]:
                inh[r["mode"]][m] += 1
            elif cs == ["pitch_miss"]:
                miss[r["mode"]] += 1
            elif cl.intended(r, m):
                intended[m] += 1
            else:
                post.append((r, m))
    total = sum(len(r["fails"]) for r in rows)
    n_inh = sum(sum(c.values()) for c in inh.values())
    out += [f"{total} failed (render, metric) pairs in the latest run:", "",
            table(["category", "failures", "why it remains"], [
                ["inherited from the pitch stage", n_inh,
                 "The pitch-only render fails the same metric. Fixing pitch modes is out of scope for this "
                 "change set (see the per-mode table)."],
                ["pitch stage missed the note (f0/inharm)", sum(miss.values()),
                 "Measured against a target the post stages never received."],
                ["breathiness > 1 (intended)", sum(intended.values()),
                 "Breathiness above 1 is meant to add aperiodic energy; the inharmonic rule counts that as a "
                 "failure."],
                ["**post-pitch**", f"**{len(post)}**", "listed below"],
            ]), ""]
    body = [[f"`{mode}`"] + [inh[mode].get(m, 0) or "" for m in METRIC_COLS] + [miss.get(mode, 0) or ""]
            for mode in cfg.PITCH_MODES if mode in inh or mode in miss]
    out += ["Pitch-stage failures by mode:", "", table(["mode"] + METRIC_COLS + ["pitch_miss"], body), ""]
    if post:
        def missed(r):
            b = cl.base.get(classify.gkey(r))
            return b is not None and "f0" in b["fails"]
        by = Counter((m, "/".join(cl.causes(r, m)), r["breath"] == 1.0, missed(r)) for r, m in post)
        out += ["Post-pitch failures by metric and cause. *breath = 1*: breathiness off, so the failure "
                "comes from cleanliness / low cut alone. *pitch-only misses the note*: the pitch stage already "
                "produced the wrong pitch, so cleanliness (which masks the target's harmonics) removes most "
                "of the body and tail/rms, which are relative to the body, move with it.", "",
                table(["metric", "cause", "breath = 1", "pitch-only misses the note", "failures"],
                      [[m, c, "yes" if b1 else "no", "yes" if mi else "no", n]
                       for (m, c, b1, mi), n in by.most_common()]), ""]
        post.sort(key=lambda t: -(t[0].get("exceed") or {}).get(t[1], 0))
        out += ["Worst post-pitch failures (up to 40):", "",
                table(["combination", "metric", "cause", "f0 ¢", "inharm Δ", "tail", "RMS Δ", "peak", "len Δ"],
                      [[f"`{r['id']}`", m, "/".join(cl.causes(r, m))] + metric_cells(r["metrics"])
                       for r, m in post[:40]])]
        out += ["", *sec_reasons(post, cl)]
    return "\n".join(out)


REASONS = {
    "pitch_miss_body": (
        "Pitch-only render already misses the target note. Cleanliness masks the target's harmonics, so it "
        "removes most of the (off-target) body; tail and rms are measured relative to that body. Fix belongs "
        "to the pitch mode (mostly sine_spectral / stft_pitchshift), not the post stages."),
    "yin_bias": (
        "YIN (the sweep's f0 metric) misreads the note: the spectral peaks of harmonics 1-4 sit within 2 cents "
        "of the target. Seen on the breathy fixture once its pitch-locked aspiration noise is removed. The "
        "pitch is right; the metric is left unchanged, as required."),
    "lowcut_100": (
        "Smart low cut at 100 %: the cutoff is 0.85 x the output's lowest f0 (filtfilt, 2nd order), which "
        "takes ~3.6 dB off the fundamental by design; stacked with other stages it crosses the rule. Lowering "
        "the 0.85 ceiling would change the control's documented behaviour - a product decision."),
    "marginal_tail": (
        "The pitch-only render's own release smear sits just under -40 dB; the post stages raise it by 3 dB "
        "or less, past the line. The extra energy is in voiced release frames of the pitch mode's synthesis."),
    "hnm_low_release": (
        "world_hnm on C1-C2 targets, tail failures caused only by breathiness < 1 and/or the low cut "
        "(all within ~1 dB of the -40 dB limit in this sweep). Breathiness < 1 makes the decaying "
        "release frames fully periodic, so HNM's harmonic part rings longer; with the low cut, the IIR "
        "high-pass (cutoff ~40 Hz) rings after the offset. Fixing either is a design change (keep release "
        "frames' aperiodicity / guard the low cut's envelope), proposed as a follow-up rather than tuned here."),
    "other": "Not covered above - listed individually.",
}


def reason_of(r, m, cl, f0_cache: dict) -> str:
    base = cl.base.get(classify.gkey(r))
    if base is not None and "f0" in base["fails"]:
        return "pitch_miss_body"
    if m == "f0":
        if r["id"] not in f0_cache:
            f0_cache[r["id"]] = spectral_harmonics(r)
        hs = f0_cache[r["id"]]
        if hs and max(abs(c) for c in hs) <= 2.0:
            return "yin_bias"
    labels = {x for c in cl.causes(r, m) for x in classify.expand(c)}
    if "lowcut" in labels and r["lowcut"] >= 100.0:
        return "lowcut_100"
    if (m == "tail" and base is not None and r["metrics"].get("tail_db") is not None
            and base["metrics"].get("tail_db") is not None
            and r["metrics"]["tail_db"] - base["metrics"]["tail_db"] <= 3.0):
        return "marginal_tail"
    if (m == "tail" and r["mode"] == "world_hnm" and r["target_f0"] < 70.0
            and labels and labels <= {"breath", "lowcut"}):
        return "hnm_low_release"
    return "other"


def sec_reasons(post, cl) -> list[str]:
    f0_cache: dict = {}
    tagged = [(r, m, reason_of(r, m, cl, f0_cache)) for r, m in post]
    counts = Counter(t[2] for t in tagged)
    out = ["**Every remaining post-pitch failure, by documented reason:**", "",
           table(["reason", "failures", "why it is not fixed here"],
                 [[k, counts[k], REASONS[k]] for k in REASONS if counts.get(k)]), ""]
    yb = [(r, m) for r, m, k in tagged if k == "yin_bias"][:24]
    if yb:
        out += ["Evidence for *yin_bias* (up to 24): YIN reading vs the offset of harmonics 1-4 from n x target "
                "(1 M-point FFT of the note body):", "",
                table(["combination", "YIN ¢", "spectral H1..H4 ¢"],
                      [[f"`{r['id']}`", f(r["metrics"].get("f0_cents"), 1, True),
                        ", ".join(f(c, 2, True) for c in f0_cache[r["id"]])] for r, m in yb]), ""]
    other = [(r, m) for r, m, k in tagged if k == "other"]
    if other:
        out += ["Failures under *other*:", "",
                table(["combination", "metric", "cause", "f0 ¢", "inharm Δ", "tail", "RMS Δ", "peak", "len Δ"],
                      [[f"`{r['id']}`", m, "/".join(cl.causes(r, m))] + metric_cells(r["metrics"])
                       for r, m in other])]
    return out


def spectral_harmonics(r) -> list[float]:
    """Re-render *r* and return the offset (cents) of harmonics 1-4 from n x target."""
    import fixtures
    import metrics
    import worker
    fx = fixtures.get(r["fixture"])
    post = {"clean_lowcut_percent": r["lowcut"], "cleanliness_percent": r["clean"],
            "clean_hf_rollback_percent": r["hfrb"], "breathiness": r["breath"], "hf_bias": r["hfbias"]}
    s = worker.make_settings(r["mode"], r["target_note"], r["stretch"], post)
    y, *_ = worker.run_pipeline_once(fx, s, fixtures.detected(r["fixture"]))
    if y is None:
        return []
    a, b = metrics.regions(fx, r["stretch"], len(y))["body"]
    seg = np.asarray(y[a:b], dtype=np.float64)
    spec = np.abs(np.fft.rfft(seg * np.hanning(seg.size), 1 << 20))
    df = fx.sr / float(1 << 20)
    out = []
    for n in range(1, 5):
        c = n * r["target_f0"]
        if c * 1.03 >= fx.sr / 2:
            break
        lo, hi = int(c * 0.97 / df), int(c * 1.03 / df)
        k = lo + int(np.argmax(spec[lo:hi]))
        out.append(1200.0 * math.log2(k * df / c))
    return out


def sec_intentional(changes) -> str:
    if not changes:
        return "## Intentional output changes\n\nNo golden reference has been regenerated."
    body = []
    for c in changes:
        b, a = c["before"], c["after"]
        body.append([c["change"], f"`{c['file']}`", c["reason"],
                     f"{fdb(b.get('peak_dbfs'), 1, True)} → {fdb(a.get('peak_dbfs'), 1, True)}",
                     f"{f(b.get('rms_change_db'), 1, True)} → {f(a.get('rms_change_db'), 1, True)}",
                     f"{f(b.get('f0_cents'), 0, True)} → {f(a.get('f0_cents'), 0, True)}",
                     f"{f(b.get('inharm_worse_db'), 1, True)} → {f(a.get('inharm_worse_db'), 1, True)}",
                     f"{f(b.get('h1_vs_input_db'), 1, True)} → {f(a.get('h1_vs_input_db'), 1, True)}",
                     f(c.get("max_abs_diff"), 4), ", ".join(b.get("fails", [])) or "pass",
                     ", ".join(a.get("fails", [])) or "pass"])
    return ("## Intentional output changes\n\n"
            "Golden references regenerated because their render has cleanliness, breathiness or low cut "
            "active (`tests/sweep/intentional_changes.json`). Pitch-only references are unchanged. Metrics "
            "use the sweep's definitions on the 2 s C4 fixture; *H1 vs input* is the fundamental's level "
            "relative to the source's.\n\n"
            + table(["change", "file", "why", "peak dBFS", "RMS Δ dB", "f0 ¢", "inharm Δ dB", "H1 vs input dB",
                     "max\\|old−new\\|", "sweep fails before", "sweep fails after"], body))


# ---------------------------------------------------------------------------
# Probe before/after
# ---------------------------------------------------------------------------

def _probe_ok(p):
    return p and "error" not in p


def sec_probes(cur: dict, before: dict) -> str:
    out = ["## Suspected bugs: before / after", "",
           "Each probe renders through `_run_pipeline` and compares a render with its pitch-only twin "
           "(`tests/sweep/probes.py`); *before* is the same probe code on the pre-fix pipeline.", ""]

    def both(key):
        return before.get(key), cur.get(key)

    # B1
    b, a = both("B1")
    if _probe_ok(b) and _probe_ok(a):
        hb, ha = b["headline"], a["headline"]
        nb = sum("f0" in r["post"] for r in b["rows"])
        na = sum("f0" in r["post"] for r in a["rows"])
        body = []
        for rb, ra in zip(b["rows"], a["rows"]):
            body.append([rb["fixture"], f(rb["shift"], 0, True), rb["target"], f(rb["clean"], 0),
                         f"{f(rb['body_vs_pitch_db'], 1, True)} → {f(ra['body_vs_pitch_db'], 1, True)}",
                         f"{f(rb['f0_cents'], 0, True)} → {f(ra['f0_cents'], 0, True)}",
                         f"{', '.join(rb['post']) or 'pass'} → {', '.join(ra['post']) or 'pass'}"])
        cp = [[f(rb["clean"], 0), rb["breath"], f"{f(rb['body_vs_pitch_db'], 1, True)} → {f(ra['body_vs_pitch_db'], 1, True)}",
               f"{f(rb['f0_cents'], 0, True)} → {f(ra['f0_cents'], 0, True)}",
               f"{f(rb['inharm_worse_db'], 1, True)} → {f(ra['inharm_worse_db'], 1, True)}",
               f"{', '.join(rb['post']) or 'pass'} → {', '.join(ra['post']) or 'pass'}"]
              for rb, ra in zip(b["cache_path"], a["cache_path"])]
        out += ["### B1 - cleanliness used the original audio's f0", "",
                f"G3 +5 st, world_hard, cleanliness 100: note body vs pitch-only **{f(hb['body_vs_pitch_db'], 1, True)} dB "
                f"→ {f(ha['body_vs_pitch_db'], 1, True)} dB**, f0 {f(hb['f0_cents'], 0, True)} ¢ → {f(ha['f0_cents'], 0, True)} ¢. "
                f"Probe renders with a post-pitch f0 failure: {nb} → {na}.", "",
                table(["fixture", "shift", "target", "clean", "body vs pitch-only dB", "f0 ¢", "post-pitch fails"], body), "",
                "praat_soft G3 +5 st (before: breathiness ≠ 1 switched cleanliness to the cached original f0):", "",
                table(["clean", "breath", "body vs pitch-only dB", "f0 ¢", "inharm Δ dB", "post-pitch fails"], cp), ""]

    # B2
    b, a = both("B2")
    if _probe_ok(b) and _probe_ok(a):
        body = []
        for rb, ra in zip(b["rows"], a["rows"]):
            if rb["clean"] not in (50, 80, 90, 100):
                continue
            body.append([rb["fixture"], rb["mode"], rb["clean"],
                         f"{f(rb['harm_vs_pitch_db'], 1, True)} → {f(ra['harm_vs_pitch_db'], 1, True)}",
                         f"{f(rb['h1_vs_pitch_db'], 1, True)} → {f(ra['h1_vs_pitch_db'], 1, True)}",
                         f"{fdb(rb['tail_db'])} → {fdb(ra['tail_db'])}",
                         f"{fdb(rb['tail_late_db'])} → {fdb(ra['tail_late_db'])}",
                         f"{fdb(rb['peak_dbfs'], 1, True)} → {fdb(ra['peak_dbfs'], 1, True)}",
                         f"{', '.join(rb['post']) or 'pass'} → {', '.join(ra['post']) or 'pass'}"])
        out += ["### B2 - cleanliness mask narrower than the STFT resolution", "",
                "Noise-free tones at shift 0 (the f0 was right before and after), cleanliness vs the "
                "pitch-only render:", "",
                table(["tone", "mode", "clean", "harmonic energy dB", "H1 dB", "tail dB", "late tail dB",
                       "peak dBFS", "post-pitch fails"], body), ""]

    # B3
    b, a = both("B3")
    if _probe_ok(b) and _probe_ok(a):
        def worst_h1(p, down):
            v = [r["h1_vs_pitch_db"] for r in p["rows"] if (r["shift"] < 0) == down and r["h1_vs_pitch_db"] is not None]
            return min(v) if v else None
        body = []
        for rb, ra in zip(b["rows"], a["rows"]):
            if rb["mode"] != "praat_soft" or rb["fixture"] not in ("harm_G3", "harm_C2"):
                continue
            body.append([rb["fixture"], f(rb["shift"], 0, True), f(rb["lowcut"], 0), f(rb["target_f0"]),
                         f"{f(rb['h1_vs_pitch_db'], 1, True)} → {f(ra['h1_vs_pitch_db'], 1, True)}",
                         f"{f(rb['body_vs_pitch_db'], 1, True)} → {f(ra['body_vs_pitch_db'], 1, True)}",
                         f"{', '.join(rb['post']) or 'pass'} → {', '.join(ra['post']) or 'pass'}"])
        out += ["### B3 - smart low cut keyed to the original f0", "",
                f"Worst fundamental (H1) loss vs pitch-only on downward shifts: **{f(worst_h1(b, True), 1, True)} dB → "
                f"{f(worst_h1(a, True), 1, True)} dB**; on upward shifts {f(worst_h1(b, False), 1, True)} → "
                f"{f(worst_h1(a, False), 1, True)} dB.", "",
                table(["fixture", "shift", "lowcut", "target f0", "H1 vs pitch-only dB", "body dB", "post-pitch fails"], body), ""]

    # B4
    b, a = both("B4")
    if _probe_ok(b) and _probe_ok(a):
        def calls(p):
            return [[k["mode"], k["breath"], " → ".join(c["fn"] + (f"({', '.join(f'{x}={y:g}' for x, y in c['kwargs'].items())})"
                                                              if c["kwargs"] else "") for c in k["calls"]) or "(none)"]
                    for k in p["calls"]]
        rng = [[rb["fixture"], rb["mode"], f(rb["shift"], 0, True), f(rb["target_f0"]),
                f"{f(rb['f0_cents'], 0, True)} → {f(ra['f0_cents'], 0, True)}",
                f"{f(rb['inharm_worse_db'], 1, True)} → {f(ra['inharm_worse_db'], 1, True)}",
                f"{', '.join(rb['post']) or 'pass'} → {', '.join(ra['post']) or 'pass'}"]
               for rb, ra in zip(b["range"], a["range"])]
        idn = [[rb["fixture"], f(rb["clean"], 0), f"{fdb(rb['residual_db'])} → {fdb(ra['residual_db'])}",
                f"{f(rb['inharm_db_b099'], 1)} → {f(ra['inharm_db_b099'], 1)} (1.0: {f(ra['inharm_db_b1'], 1)})"]
               for rb, ra in zip(b["identity"], a["identity"])]
        dz = [[rb["fixture"], rb["mode"], rb["hf_bias"], "; ".join(rb["warnings"]) or "–", "; ".join(ra["warnings"]) or "–",
               f"{rb['nonfinite']} → {ra['nonfinite']}",
               f"{fdb(rb['residual_vs_0.01_db'])} → {fdb(ra['residual_vs_0.01_db'])}"]
              for rb, ra in zip(b["div0"], a["div0"])]
        out += ["### B4 - breathiness ran a second WORLD pass (harvest, default range); 1/0 at breathiness 0", "",
                "pyworld calls in one render (G3 +5 st, cleanliness 50), **before**:", "", table(["mode", "breath", "calls"], calls(b)), "",
                "**after**:", "", table(["mode", "breath", "calls"], calls(a)), "",
                "Breathiness 0.5 vs pitch-only:", "",
                table(["fixture", "mode", "shift", "target f0", "f0 ¢", "inharm Δ dB", "post-pitch fails"], rng), "",
                "Breathiness 0.99 vs 1.0 (world_hard, shift 0):", "",
                table(["fixture", "clean", "waveform residual dB", "inharm dB at 0.99"], idn), "",
                "Breathiness 0:", "",
                table(["fixture", "mode", "hf_bias", "warnings before", "warnings after", "NaN/inf samples",
                       "residual vs 0.01 dB"], dz), ""]

    # B5
    b, a = both("B5")
    if _probe_ok(b) and _probe_ok(a):
        body = [[rb["B"], rb["mode"], f"cl {rb.get('cleanliness_percent', 0):g} / br {rb.get('breathiness', 1):g}",
                 f"{f(rb['cache_hit'])} → {f(ra['cache_hit'])}",
                 f"{rb['len_warm']}/{rb['len_cold']} → {ra['len_warm']}/{ra['len_cold']}",
                 f"{fdb(rb['residual_db'])} → {fdb(ra['residual_db'])}"]
                for rb, ra in zip(b["cases"], a["cases"])]
        out += ["### B5 - WORLD cache keyed on md5 of the first 1000 samples", "",
                "A = `lead_G3`, then B (same 300 ms of leading zeros for `lead_A4`) without resetting the cache, "
                "vs a cold render of B:", "",
                table(["B", "mode", "post", "cache hit", "len warm/cold", "warm vs cold residual dB"], body), ""]

    # E1
    b, a = both("E1")
    if _probe_ok(b) and _probe_ok(a):
        body = [[rb["fixture"], rb["mode"], f(rb["clean"], 0),
                 f"{fdb(rb['peak_dbfs'], 1, True)} → {fdb(ra['peak_dbfs'], 1, True)}",
                 f"{f(rb['peak_at_ms'], 2)} → {f(ra['peak_at_ms'], 2)}", fdb(ra["pitch_only_peak_dbfs"], 1, True),
                 f"{f(rb['nola_warning'])} → {f(ra['nola_warning'])}"]
                for rb, ra in zip(b["rows"], a["rows"])]
        out += ["### E1 - cleanliness spiked the first samples of the file", "",
                table(["fixture", "mode", "clean", "peak dBFS", "peak at ms", "pitch-only peak", "NOLA warning"], body), ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Current-run detail
# ---------------------------------------------------------------------------

def sec_ranking(rows, cl) -> str:
    total = sum(len(r["fails"]) for r in rows)
    post_total = sum(len(cl.post_fails(r)) for r in rows)
    post = rank_causes(cl, rows, True)
    allc = rank_causes(cl, rows, False)
    return ("## Root causes in the latest run\n\n"
            f"Post-pitch failures ({post_total}):\n\n"
            + table(["rank", "cause", "explains", "sole", "renders", "meaning"],
                    [[i, d["cause"], d["any"], d["sole"], d["renders"], CAUSE_TEXT.get(d["cause"], "")]
                     for i, d in enumerate(post, 1)])
            + f"\n\nAll failures ({total}):\n\n"
            + table(["rank", "cause", "explains", "sole", "renders", "meaning"],
                    [[i, d["cause"], d["any"], d["sole"], d["renders"],
                      CAUSE_TEXT.get(d["cause"]) or PITCH_TEXT.get(d["cause"], "")]
                     for i, d in enumerate(allc, 1)]))


def sec_thresholds(summary) -> str:
    t = summary["thresholds"]
    body = [
        ["exception / nonfinite", "any exception from `_run_pipeline`, any NaN/inf sample"],
        ["length", f"\\|len(out) − round(len(in) × stretch)\\| > {t['LENGTH_TOL_MS']:g} ms"],
        ["peak", f"peak > {t['PEAK_DBFS']:g} dBFS"],
        ["f0", f"\\|median YIN f0 of the note body − target\\| > {t['F0_ERR_CENTS']:g} cents, or no pitch found"],
        ["inharm", f"inharmonic energy ratio worse than the input's by > {t['INHARM_WORSE_DB']:g} dB"],
        ["tail", f"energy in the {t['TAIL_MS']:g} ms after the source offset > {t['TAIL_DB']:g} dB re note body"],
        ["rms", f"note-body RMS drop vs input > {t['RMS_LOSS_DB']:g} dB at cleanliness ≤ {t['RMS_LOSS_MAX_CLEAN']:g} %"],
    ]
    return ("## Pass/fail rules (unchanged)\n\nAll thresholds live in `tests/sweep/sweep_config.py`. A failure is "
            "*inherited* when the group's pitch-only render fails the metric too and the render is not worse "
            "by more than the metric's margin (10 ms, 1 dB, 15 ¢, 6 dB, 6 dB, 6 dB). Other failures are "
            "attributed by re-rendering with one post-pitch stage switched off.\n\n"
            + table(["metric", "fails when"], body))


def sec_fixtures(summary) -> str:
    body = []
    for name, m in summary["fixtures"].items():
        d = m["detected"]
        body.append([f"`{name}`", m["kind"], f"{m['truth_note']} ({f(m['truth_f0'], 2)} Hz)",
                     f"{d.get('note_name')} ({f(d.get('freq_hz'), 1)} Hz)", f(m["duration_s"], 2),
                     "yes" if m["has_tail"] else "no", m["description"]])
    return ("## Fixtures\n\n" + table(["fixture", "kind", "truth", "detected at load", "dur s", "tail", "content"], body))


def sec_counts(rows, cl, summary) -> str:
    out = ["## Failure counts per parameter (latest run)", "",
           "*post-pitch* = renders with at least one post-pitch failure.", ""]

    def tab(field, values, set_name):
        body = []
        for v in values:
            sel = [r for r in rows if set_name in r["sets"] and r[field] == v]
            if not sel:
                continue
            mc = Counter(m for r in sel for m in r["fails"])
            body.append([f"`{v}`" if isinstance(v, str) else f"{v:g}" if isinstance(v, float) else v, len(sel),
                         sum(1 for r in sel if r["fails"]), sum(1 for r in sel if cl.post_fails(r)),
                         sum(1 for r in sel if cl.post_ex_fails(r))] + [mc.get(m, 0) or "" for m in METRIC_COLS])
        return table([field, "renders", "failing", "post-pitch", "post excl. intended"] + METRIC_COLS, body)

    for set_name, fields in (
            ("pairwise", [("mode", cfg.PITCH_MODES), ("shift", cfg.SHIFTS), ("stretch", cfg.STRETCHES),
                          ("lowcut", cfg.LOWCUTS), ("clean", cfg.CLEANS), ("hfrb", cfg.HF_ROLLBACKS),
                          ("breath", cfg.BREATHS), ("hfbias", cfg.HF_BIASES)]),
            ("grid", [("mode", cfg.PITCH_MODES), ("shift", cfg.SHIFTS), ("clean", cfg.CLEANS),
                      ("breath", cfg.BREATHS)])):
        out += [f"### {set_name.capitalize()} set", ""]
        for field, values in fields:
            out += [f"**{field}**", "", tab(field, values, set_name), ""]
    body = []
    for name in summary["meta"]["fixtures"]:
        sel = [r for r in rows if r["fixture"] == name]
        body.append([f"`{name}`", len(sel), sum(1 for r in sel if r["fails"]),
                     sum(1 for r in sel if cl.post_fails(r)), sum(1 for r in sel if cl.post_ex_fails(r))])
    out += ["### Per fixture", "", table(["fixture", "renders", "failing", "post-pitch", "post excl. intended"], body)]
    return "\n".join(out)


def sec_worst(rows, cl) -> str:
    worst = sorted(rows, key=lambda r: (-cl.post_severity(r), -r["severity"]))[:cfg.N_WORST_TABLE]
    worst = [r for r in worst if cl.post_fails(r)]
    if not worst:
        return "## Top 20 worst combinations (latest run)\n\nNo post-pitch failures."
    body = [[i, f"`{r['id']}`", ", ".join(r["fails"]), f(cl.post_severity(r)), f(r["severity"])]
            + metric_cells(r["metrics"]) + ["; ".join(f"{m}: {'/'.join(cl.causes(r, m))}" for m in r["fails"])]
            for i, r in enumerate(worst, 1)]
    return ("## Top 20 worst combinations (latest run)\n\nRanked by post-pitch severity (sum of value / threshold "
            "over post-pitch failures).\n\n"
            + table(["#", "combination", "fails", "post sev", "all sev", "f0 ¢", "inharm Δ", "tail", "RMS Δ",
                     "peak", "len Δ", "causes"], body))


# ---------------------------------------------------------------------------
# A/B WAVs of the previous 10 worst
# ---------------------------------------------------------------------------

def _slug(rid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", rid.replace("|", "__").replace("+", "p")).strip("_")


def save_ab(base: dict, rows) -> list[dict]:
    import soundfile as sf
    import fixtures
    import worker
    out_dir = cfg.OUT_DIR / "ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.wav"):
        old.unlink()
    prefix_wavs = cfg.OUT_DIR / "prefix_run" / "worst"
    amap = {r["id"]: r for r in rows}
    bmap = {r["id"]: r for r in base["rows"]}
    saved = []
    for w in base["worst"]:
        rid = w["id"]
        parts = rid.split("|")
        fixture, mode, shift, stretch = parts[0], parts[1], int(parts[2]), float(parts[3][1:])
        post = {"clean_lowcut_percent": float(parts[4][2:]), "cleanliness_percent": float(parts[5][2:]),
                "clean_hf_rollback_percent": float(parts[6][2:]), "breathiness": float(parts[7][2:]),
                "hf_bias": float(parts[8][2:])}
        fx = fixtures.get(fixture)
        tnote = fixtures.target_note(fx, shift)
        stem = f"{w['rank']:02d}_{_slug(rid)}"
        files = {}
        if w.get("file") and (prefix_wavs / w["file"]).exists():
            shutil.copyfile(prefix_wavs / w["file"], out_dir / f"{stem}__before.wav")
            files["before"] = f"{stem}__before.wav"
        for tag, p in (("after", post), ("after_pitch_only", dict(cfg.NEUTRAL_POST))):
            s = worker.make_settings(mode, tnote, stretch, p)
            y, *_ = worker.run_pipeline_once(fx, s, fixtures.detected(fixture))
            if y is None:
                continue
            y = np.clip(np.nan_to_num(np.asarray(y, dtype=np.float64)), -1.0, 1.0).astype(np.float32)
            sf.write(str(out_dir / f"{stem}__{tag}.wav"), y, fx.sr, subtype="FLOAT")
            files[tag] = f"{stem}__{tag}.wav"
        saved.append({"rank": w["rank"], "id": rid, "files": files, "before": bmap.get(rid), "after": amap.get(rid)})
    return saved


def sec_ab(saved, cl, bcl) -> str:
    body = []
    for s in saved:
        b, a = s["before"] or {}, s["after"] or {}
        bm, am = b.get("metrics", {}), a.get("metrics", {})
        body.append([s["rank"], f"`{s['id']}`", ", ".join(s["files"]) if s["files"] else "–",
                     f"{', '.join(bcl.post_fails(b)) if b else '–'} → {(', '.join(cl.post_fails(a)) or 'pass') if a else 'not run'}",
                     f"{fdb(bm.get('peak_dbfs'), 1, True)} → {fdb(am.get('peak_dbfs'), 1, True)}",
                     f"{f(bm.get('f0_cents'), 0, True)} → {f(am.get('f0_cents'), 0, True)}",
                     f"{f(bm.get('inharm_worse_db'), 1, True)} → {f(am.get('inharm_worse_db'), 1, True)}"])
    return ("## A/B listening: the 10 previous-worst renders\n\n"
            "In `tests/sweep/out/ab/`: `…__before.wav` (pre-fix render, saved by the pre-fix run), `…__after.wav` "
            "(this code) and `…__after_pitch_only.wav`. All are clipped to ±1.0 for safe listening; the true "
            "peaks are in the table.\n\n"
            + table(["#", "combination", "files", "post-pitch fails before → after", "peak dBFS", "f0 ¢",
                     "inharm Δ dB"], body))


def sec_appendix(tag="prefix") -> str:
    p = cfg.BASELINE_DIR / f"{tag}_report.md"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", text, flags=re.M)   # demote headings
    text = text.replace("## FreqEnforcer post-pitch combination sweep", "## Appendix: pre-fix report (frozen)", 1)
    return ("<!-- frozen copy of the pre-fix report; tests/sweep/baseline/prefix_report.md -->\n" + text)


# ---------------------------------------------------------------------------

def build(save_wavs: bool = True) -> None:
    rows, summary, probes = load_current()
    cl = classify.Classifier(rows)
    base = load_baseline()
    bcl = classify.Classifier(base["rows"]) if base else None
    hist = load_json(cfg.HISTORY_PATH, [])
    changes = load_json(cfg.INTENTIONAL_PATH, [])
    saved = save_ab(base, rows) if (save_wavs and base) else []
    parts = [
        sec_header(summary, rows),
        sec_history(hist),
        sec_before_after(rows, cl, base, bcl) if base else "",
        sec_remaining(rows, cl),
        sec_intentional(changes),
        sec_probes(probes, base.get("probes", {})) if base else "",
        sec_ab(saved, cl, bcl) if saved else "",
        sec_ranking(rows, cl),
        sec_thresholds(summary),
        sec_fixtures(summary),
        sec_worst(rows, cl),
        sec_counts(rows, cl, summary),
        sec_appendix(),
    ]
    cfg.REPORT_PATH.write_text("\n\n".join(p for p in parts if p) + "\n", encoding="utf-8")
    print(f"wrote {cfg.REPORT_PATH}")


if __name__ == "__main__":
    build(save_wavs="--no-wavs" not in sys.argv)
