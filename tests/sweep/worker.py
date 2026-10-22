"""Process-pool task: render one group (fixture, mode, shift, stretch) through
the real _run_pipeline, measure every render, and attribute each failure.

Attribution of a failed (render, metric), using only real _run_pipeline
calls so it keeps working as the pipeline changes:
  1. inherited       - the group's pitch-only render fails the same metric and
                       the render is not worse by more than WORSE_MARGIN.
  2. stage labels    - switching one post-pitch stage off (cleanliness,
                       smart low cut, breathiness) makes it pass:
                       clean / lowcut / breath / breath_intended (> 1).
  3. multi:a+b       - only switching several stages off makes it pass.
  4. unexplained.
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
    for key, entry in combos.items():
        settings = make_settings(mode, tnote, stretch, entry["post"])
        t0 = time.perf_counter()
        out, timings, warns, exc = run_pipeline_once(fx, settings, det)
        elapsed = time.perf_counter() - t0
        m, fails, ex, sev = measure(out, fx, stretch, target_f0, settings, exc)
        p = entry["post"]
        rows.append({
            "id": (f"{fx.name}|{mode}|{shift:+d}|x{stretch:g}|lc{p['clean_lowcut_percent']:g}"
                   f"|cl{p['cleanliness_percent']:g}|rb{p['clean_hf_rollback_percent']:g}"
                   f"|br{p['breathiness']:g}|hb{p['hf_bias']:g}"),
            "sets": entry["sets"], "fixture": fx.name, "mode": mode, "shift": shift,
            "stretch": stretch, "lowcut": p["clean_lowcut_percent"], "clean": p["cleanliness_percent"],
            "hfrb": p["clean_hf_rollback_percent"], "breath": p["breathiness"], "hfbias": p["hf_bias"],
            "target_note": tnote, "target_f0": target_f0,
            "metrics": m, "fails": fails, "exceed": ex, "severity": sev, "warnings": warns,
            "traceback": exc, "elapsed_s": round(elapsed, 3), "attribution": {},
            "_key": key, "_settings": settings,
        })

    _attribute(rows, rows[0], fx, task, tnote, target_f0)

    for r in rows:
        r.pop("_key", None)
        r.pop("_settings", None)
    return {"rows": rows, "fidelity": [], "librosa": "librosa" in sys.modules,
            "group": f"{fx.name}|{mode}|{shift:+d}|x{stretch:g}",
            "elapsed_s": round(time.perf_counter() - t_group, 2)}


STAGE_OFF = {
    "clean": {"cleanliness_percent": 0.0, "clean_hf_rollback_percent": 0.0},
    "lowcut": {"clean_lowcut_percent": 0.0},
    "breath": {"breathiness": 1.0, "hf_bias": 0.0},
}


def active_stages(post: dict) -> list[str]:
    out = []
    if post["cleanliness_percent"] > 0.0:
        out.append("clean")
    if post["clean_lowcut_percent"] > 0.0:
        out.append("lowcut")
    if post["breathiness"] != 1.0:
        out.append("breath")
    return out


def stage_label(stage: str, post: dict) -> str:
    if stage == "breath" and post["breathiness"] > 1.0:
        return "breath_intended"
    return stage


def _attribute(rows, base, fx, task, tnote, target_f0) -> None:
    import classify

    stretch = float(task["stretch"])
    det = task["detected_pitch"]
    memo = {r["_key"]: (r["fails"], r["metrics"]) for r in rows}

    def render(post: dict):
        key = post_key(post)
        if key not in memo:
            settings = make_settings(task["mode"], tnote, stretch, post)
            out, _t, _w, exc = run_pipeline_once(fx, settings, det)
            m, fails, _ex, _sev = measure(out, fx, stretch, target_f0, settings, exc)
            memo[key] = (fails, m)
        return memo[key]

    def cleared(metric, fails, m) -> bool:
        return metric not in fails or classify.inherited(metric, m, base)

    for r in rows[1:]:
        post = {k: r["_settings"][k] for k in POST_KEYS}
        for metric in r["fails"]:
            if classify.inherited(metric, r["metrics"], base):
                r["attribution"][metric] = ["inherited"]
                continue
            stages = active_stages(post)
            causes = []
            for st in stages:
                fails, m = render(dict(post, **STAGE_OFF[st]))
                if cleared(metric, fails, m):
                    causes.append(stage_label(st, post))
            if not causes and len(stages) >= 2:
                off = dict(post)
                for st in stages:
                    off.update(STAGE_OFF[st])
                fails, m = render(off)
                if cleared(metric, fails, m):
                    causes = ["multi:" + "+".join(stage_label(st, post) for st in stages)]
            r["attribution"][metric] = causes or ["unexplained"]
