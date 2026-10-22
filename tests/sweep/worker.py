"""Process-pool task: render one group (fixture, mode, shift, stretch) through
the real _run_pipeline, measure every render, and attribute each failure.

Attribution of a failed (render, metric):
  1. inherited  - the pitch-only baseline of the group fails the same metric
                  and the render is not worse by more than WORSE_MARGIN.
  2. B1/B3/B4   - the single counterfactual toggle F1/F3/F4 makes it pass.
  3. joint:...  - only all relevant toggles together make it pass.
  4. B2 / clean_mask_N / breath_resynth / breath_intended / lowcut_design
                - with all toggles on, switching that stage off makes it pass.
  5. unexplained.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import time
import traceback
import warnings

import numpy as np

import counterfactual as cf
import fixtures
import metrics
import sweep_config as cfg

POST_KEYS = ("clean_lowcut_percent", "cleanliness_percent", "clean_hf_rollback_percent",
             "breathiness", "hf_bias")


def make_settings(mode: str, target_note: str, stretch: float, post: dict) -> dict:
    """Settings dict exactly as /api/process builds it from a ProcessRequest."""
    from server.routes.audio import ProcessRequest
    req = ProcessRequest(target_note=target_note, pitch_mode=mode, stretch_factor=stretch, **post)
    settings = req.model_dump()
    settings["harmonic_ceiling_offsets_db"] = {
        int(k): float(v) for k, v in settings.get("harmonic_ceiling_offsets_db", {}).items()}
    return settings


def post_key(post: dict) -> tuple:
    return tuple(float(post.get(k, cfg.NEUTRAL_POST[k])) for k in POST_KEYS)


def _warn_strings(caught) -> list[str]:
    out = []
    for w in caught:
        s = f"{w.category.__name__}: {str(w.message)[:120]} @ {os.path.basename(w.filename)}:{w.lineno}"
        if s not in out:
            out.append(s)
    return out


def run_pipeline_once(fx, settings: dict, detected_pitch: dict, reset_cache: bool = True):
    """One real _run_pipeline call. Returns (audio|None, timings, warnings, traceback|None)."""
    from server.routes.audio import _run_pipeline
    from server.state import state

    state.detected_pitch = dict(detected_pitch)
    if reset_cache:
        state.world_cache = {"audio_hash": None}
    token = state.increment_token()
    np.random.seed(cfg.RNG_SEED)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out, _harm, timings = _run_pipeline(fx.audio.copy(), fx.sr, settings, token, None)
            return np.asarray(out), timings, _warn_strings(caught), None
        except Exception:
            return None, {}, _warn_strings(caught), traceback.format_exc()


_INPUT_METRICS: dict[str, dict] = {}


def input_metrics(fx) -> dict:
    if fx.name not in _INPUT_METRICS:
        _INPUT_METRICS[fx.name] = metrics.input_metrics(fx)
    return _INPUT_METRICS[fx.name]


def measure(out, fx, stretch, target_f0, settings, exc=None) -> tuple[dict, list, dict, float]:
    if exc is not None or out is None:
        m = {"exception": (exc or "no output").strip().splitlines()[-1][:300]}
    else:
        m = metrics.render_metrics(out, fx, stretch, target_f0, input_metrics(fx))
    fails, ex, sev = metrics.evaluate(m, settings)
    return m, fails, ex, sev


def run_group(task: dict) -> dict:
    t_group = time.perf_counter()
    fx = fixtures.get(task["fixture"])
    mode, shift, stretch = task["mode"], int(task["shift"]), float(task["stretch"])
    tnote = fixtures.target_note(fx, shift)
    from server.utils.note_utils import note_name_to_freq
    target_f0 = float(note_name_to_freq(tnote))
    det = task["detected_pitch"]

    # Unique post combos; the neutral (pitch-only) one first
    combos: dict[tuple, dict] = {}
    neutral = post_key(cfg.NEUTRAL_POST)
    combos[neutral] = {"post": dict(cfg.NEUTRAL_POST), "sets": ["baseline"]}
    for post, set_name in task["combos"]:
        key = post_key(post)
        entry = combos.setdefault(key, {"post": {k: float(post.get(k, cfg.NEUTRAL_POST[k])) for k in POST_KEYS},
                                        "sets": []})
        if set_name not in entry["sets"]:
            entry["sets"].append(set_name)

    rows = []
    outputs: dict[tuple, np.ndarray | None] = {}
    for key, entry in combos.items():
        settings = make_settings(mode, tnote, stretch, entry["post"])
        t0 = time.perf_counter()
        out, timings, warns, exc = run_pipeline_once(fx, settings, det)
        elapsed = time.perf_counter() - t0
        m, fails, ex, sev = measure(out, fx, stretch, target_f0, settings, exc)
        outputs[key] = out
        p = entry["post"]
        rows.append({
            "id": (f"{fx.name}|{mode}|{shift:+d}|x{stretch:g}|lc{p['clean_lowcut_percent']:g}"
                   f"|cl{p['cleanliness_percent']:g}|rb{p['clean_hf_rollback_percent']:g}"
                   f"|br{p['breathiness']:g}|hb{p['hf_bias']:g}"),
            "sets": entry["sets"], "fixture": fx.name, "mode": mode, "shift": shift,
            "stretch": stretch, "lowcut": p["clean_lowcut_percent"], "clean": p["cleanliness_percent"],
            "hfrb": p["clean_hf_rollback_percent"], "breath": p["breathiness"], "hfbias": p["hf_bias"],
            "target_note": tnote, "target_f0": target_f0, "cache_used": cf.app_has_cache(settings),
            "metrics": m, "fails": fails, "exceed": ex, "severity": sev, "warnings": warns,
            "traceback": exc, "elapsed_s": round(elapsed, 3), "attribution": {},
            "_key": key, "_settings": settings,
        })

    base = rows[0]
    fidelity: list[dict] = []
    _attribute(rows, base, fx, task, target_f0, outputs, fidelity)

    for r in rows:
        r.pop("_key", None)
        r.pop("_settings", None)
    return {"rows": rows, "fidelity": fidelity, "librosa": "librosa" in sys.modules,
            "group": f"{fx.name}|{mode}|{shift:+d}|x{stretch:g}",
            "elapsed_s": round(time.perf_counter() - t_group, 2)}


def _attribute(rows, base, fx, task, target_f0, outputs, fidelity) -> None:
    from server.state import state

    stretch = float(task["stretch"])
    det = task["detected_pitch"]
    reg = metrics.regions(fx, stretch)
    note_span = reg["note"]
    pitched = None
    world_cache = None
    pitch_error = None
    memo: dict[tuple, tuple[list, dict]] = {}

    def ensure_pitched(settings):
        nonlocal pitched, world_cache, pitch_error
        if pitched is None and pitch_error is None:
            try:
                state.detected_pitch = dict(det)
                with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                    warnings.simplefilter("ignore")
                    pitched, world_cache = cf.pitch_stage(fx.audio, fx.sr, settings)
            except Exception:
                pitch_error = traceback.format_exc()
        return pitched is not None

    def replica(settings, fixes=frozenset(), diags=frozenset()):
        eff = dict(settings)
        if "no_clean" in diags:
            eff["cleanliness_percent"] = 0.0
        if "no_breath" in diags:
            eff["breathiness"] = 1.0
        if "no_lowcut" in diags:
            eff["clean_lowcut_percent"] = 0.0
        fixes = frozenset(f for f in fixes if f in cf.relevant_fixes(eff))
        key = (post_key(eff), fixes)
        if key in memo:
            return memo[key]
        try:
            with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                warnings.simplefilter("ignore")
                y = cf.post_stage(pitched, fx.sr, eff, world_cache, det, target_f0, note_span, fixes)
            m, fails, _ex, _sev = measure(y, fx, stretch, target_f0, eff)
        except Exception:
            m, fails, _ex, _sev = measure(None, fx, stretch, target_f0, eff, traceback.format_exc())
            y = None
        memo[key] = (fails, m, y)
        return memo[key]

    # Fidelity: replica without toggles must equal _run_pipeline (two post-processed combos)
    checked = 0
    for r in rows[1:]:
        if checked >= 2 or r["traceback"] or outputs.get(r["_key"]) is None:
            continue
        s = r["_settings"]
        if not (s["cleanliness_percent"] > 0 or s["breathiness"] != 1.0 or s["clean_lowcut_percent"] > 0):
            continue
        if not ensure_pitched(s):
            break
        _f, _m, y = replica(s)
        ref = outputs[r["_key"]]
        same_len = y is not None and y.shape == ref.shape
        diff = float(np.max(np.abs(np.asarray(y, np.float64) - np.asarray(ref, np.float64)))) if same_len else None
        fidelity.append({"id": r["id"], "same_len": same_len, "max_abs_diff": diff})
        checked += 1

    base_fails = set(base["fails"])
    for r in rows[1:]:
        if not r["fails"]:
            continue
        s = r["_settings"]
        for metric in r["fails"]:
            causes = []
            if metric in base_fails:
                if metric in ("exception", "nonfinite"):
                    causes = ["inherited"]
                else:
                    v, vb = metrics.metric_value(r["metrics"], metric), metrics.metric_value(base["metrics"], metric)
                    if v is None or vb is None or v - vb <= metrics.WORSE_MARGIN[metric]:
                        causes = ["inherited"]
            if not causes:
                if not ensure_pitched(s):
                    causes = ["pitch_stage_error"]
                else:
                    causes = _explain(s, metric, replica, base)
            r["attribution"][metric] = causes


def _cleared(metric: str, fails: list, m: dict, base: dict) -> bool:
    """A counterfactual clears a failure when the metric passes, or - if the
    pitch-only baseline already fails it - when it is back within
    WORSE_MARGIN of the baseline (the post stages no longer add to it)."""
    if metric not in fails:
        return True
    if metric in base["fails"] and metric not in ("exception", "nonfinite"):
        v, vb = metrics.metric_value(m, metric), metrics.metric_value(base["metrics"], metric)
        return v is not None and vb is not None and v - vb <= metrics.WORSE_MARGIN[metric]
    return False


def _explain(s, metric, replica, base) -> list[str]:
    rel = cf.relevant_fixes(s)
    causes = []
    for f in rel:
        fails, m, _y = replica(s, frozenset([f]))
        if _cleared(metric, fails, m, base):
            causes.append(cf.FIX_LABEL[f])
    if causes:
        return causes
    if len(rel) >= 2:
        fails, m, _y = replica(s, frozenset(rel))
        if _cleared(metric, fails, m, base):
            return ["joint:" + "+".join(cf.FIX_LABEL[f] for f in rel)]
    stages = cf.active_stages(s)
    for d in stages:
        fails, m, _y = replica(s, frozenset(rel), frozenset([d]))
        if _cleared(metric, fails, m, base):
            causes.append(cf.diag_label(d, s))
    if causes:
        return causes
    if len(stages) >= 2:
        # Each stage alone is enough to fail: only removing them together clears it
        fails, m, _y = replica(s, frozenset(rel), frozenset(stages))
        if _cleared(metric, fails, m, base):
            return ["multi:" + "+".join(cf.diag_label(d, s) for d in stages)]
    return ["unexplained"]
