"""Targeted experiments for B1-B5 and E1, at pipeline level.

Every probe goes through the real _run_pipeline (worker.run_pipeline_once)
and compares a render with its pitch-only twin, so the same code measures
the unfixed and the fixed pipeline. The B4 probe also wraps pyworld's entry
points to log which analyses / syntheses a render runs (restored after).
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import math

import numpy as np

import classify
import fixtures
import sweep_config as cfg
import worker


def _freq(note: str) -> float:
    from server.utils.note_utils import note_name_to_freq
    return float(note_name_to_freq(note))


def _render(name: str, mode: str, shift: int, post: dict | None = None, stretch: float = 1.0,
            reset_cache: bool = True) -> dict:
    fx = fixtures.get(name)
    tnote = fixtures.target_note(fx, shift)
    s = worker.make_settings(mode, tnote, stretch, dict(post or {}))
    y, timings, warns, exc = worker.run_pipeline_once(fx, s, fixtures.detected(name), reset_cache=reset_cache)
    m, fails, _ex, _sev = worker.measure(y, fx, stretch, _freq(tnote), s, exc)
    return {"y": y, "m": m, "fails": fails, "warns": warns, "exc": exc, "timings": timings,
            "fx": fx, "target": tnote, "target_f0": _freq(tnote)}


def _vs(r: dict, r0: dict) -> dict:
    """Render vs its pitch-only twin: deltas and post-pitch failures."""
    m, m0 = r["m"], r0["m"]

    def d(k):
        return None if m.get(k) is None or m0.get(k) is None else m[k] - m0[k]
    base = {"fails": r0["fails"], "metrics": m0}
    return {"body_vs_pitch_db": d("body_db"), "harm_vs_pitch_db": d("harm_db"), "h1_vs_pitch_db": d("h1_db"),
            "f0_cents": m.get("f0_cents"), "inharm_worse_db": m.get("inharm_worse_db"),
            "tail_db": m.get("tail_db"), "tail_late_db": m.get("tail_late_db"),
            "fails": r["fails"], "post": [f for f in r["fails"] if not classify.inherited(f, m, base)]}


def _residual_db(a, b) -> float | None:
    if a is None or b is None:
        return None
    n = min(len(a), len(b))
    a = np.asarray(a[:n], np.float64)
    b = np.asarray(b[:n], np.float64)
    e = float(np.sum((a - b) ** 2))
    return 10.0 * math.log10(e / max(1e-30, float(np.sum(a ** 2)))) if e > 0 else -300.0


# ---------------------------------------------------------------------------

def probe_b1() -> dict:
    """Cleanliness after a shift: loss vs the pitch-only render."""
    out: dict = {"rows": [], "cache_path": []}
    for name in ("harm_G3", "test_2s_C4"):
        for shift in cfg.SHIFTS:
            r0 = _render(name, "world_hard", shift)
            for clean in (50.0, 100.0):
                r = _render(name, "world_hard", shift, {"cleanliness_percent": clean})
                out["rows"].append({"fixture": name, "shift": shift, "target": r["target"], "clean": clean,
                                    **_vs(r, r0)})
    r0 = _render("harm_G3", "praat_soft", 5)
    for clean in (50.0, 100.0):
        for breath in (1.0, 0.5):
            r = _render("harm_G3", "praat_soft", 5, {"cleanliness_percent": clean, "breathiness": breath})
            out["cache_path"].append({"clean": clean, "breath": breath, **_vs(r, r0)})
    out["headline"] = next(x for x in out["rows"]
                           if x["fixture"] == "harm_G3" and x["shift"] == 5 and x["clean"] == 100.0)
    return out


def probe_b2() -> dict:
    """Mask design at shift 0 (right f0 either way), noise-free tones."""
    rows = []
    for name in ("pure_C2", "pure_G3", "pure_A4"):
        for mode in ("world_hard", "praat_soft"):
            r0 = _render(name, mode, 0)
            for clean in range(10, 101, 10):
                r = _render(name, mode, 0, {"cleanliness_percent": float(clean)})
                rows.append({"fixture": name, "mode": mode, "clean": clean,
                             "fwhm_hz": cfg.clean_fwhm_hz(clean), **_vs(r, r0),
                             "peak_dbfs": r["m"].get("peak_dbfs")})
    return {"rows": rows}


def probe_b3() -> dict:
    """Smart low cut on shifted renders: fundamental (H1) vs pitch-only."""
    rows = []
    for name in ("harm_C2", "harm_G3", "harm_A4", "vowel_D3"):
        for mode in ("praat_soft", "world_hard"):
            for shift in cfg.SHIFTS:
                r0 = _render(name, mode, shift)
                for pct in (50.0, 100.0):
                    r = _render(name, mode, shift, {"clean_lowcut_percent": pct})
                    rows.append({"fixture": name, "mode": mode, "shift": shift, "lowcut": pct,
                                 "detected_f0": fixtures.detected(name).get("freq_hz"),
                                 "target_f0": r["target_f0"], **_vs(r, r0)})
    return {"rows": rows}


@contextlib.contextmanager
def _log_pyworld(calls: list):
    import pyworld as pw
    names = ("dio", "harvest", "stonemask", "cheaptrick", "d4c", "synthesize")
    orig = {n: getattr(pw, n) for n in names}

    def wrap(n):
        def f(*a, **k):
            calls.append({"fn": n, "kwargs": {kk: vv for kk, vv in k.items()
                                              if kk in ("f0_floor", "f0_ceil", "frame_period")}})
            return orig[n](*a, **k)
        return f
    for n in names:
        setattr(pw, n, wrap(n))
    try:
        yield
    finally:
        for n in names:
            setattr(pw, n, orig[n])


def probe_b4() -> dict:
    out: dict = {"calls": [], "range": [], "identity": [], "div0": []}
    for mode in ("world_hard", "praat_soft"):
        for breath in (0.5, 1.0):
            calls: list = []
            with _log_pyworld(calls):
                _render("harm_G3", mode, 5, {"cleanliness_percent": 50.0, "breathiness": breath})
            out["calls"].append({"mode": mode, "breath": breath, "calls": calls})

    for name in ("harm_C2", "harm_G3", "harm_A4", "harm_A5"):
        for mode in ("world_hard", "praat_soft"):
            for shift in (-12, 0, 12):
                r0 = _render(name, mode, shift)
                r = _render(name, mode, shift, {"breathiness": 0.5})
                out["range"].append({"fixture": name, "mode": mode, "shift": shift,
                                     "target_f0": r["target_f0"], **_vs(r, r0)})

    for name in ("harm_G3", "test_2s_C4"):
        for clean in (0.0, 75.0):
            r1 = _render(name, "world_hard", 0, {"cleanliness_percent": clean})
            r2 = _render(name, "world_hard", 0, {"cleanliness_percent": clean, "breathiness": 0.99})
            out["identity"].append({"fixture": name, "clean": clean, "residual_db": _residual_db(r1["y"], r2["y"]),
                                    "inharm_db_b1": r1["m"].get("inharm_db"),
                                    "inharm_db_b099": r2["m"].get("inharm_db")})

    for name in ("harm_G3", "breathy_A3"):
        for mode in ("world_hard", "praat_soft"):
            ref = _render(name, mode, 0, {"breathiness": 0.01})
            for amount, hf_bias in ((0.0, 0.0), (0.0, 1.0)):
                r = _render(name, mode, 0, {"breathiness": amount, "hf_bias": hf_bias})
                out["div0"].append({"fixture": name, "mode": mode, "breath": amount, "hf_bias": hf_bias,
                                    "warnings": [w for w in r["warns"] if "divide" in w.lower()],
                                    "exception": r["exc"], "nonfinite": r["m"].get("nonfinite"),
                                    "residual_vs_0.01_db": _residual_db(ref["y"], r["y"])})
    return out


def probe_b5() -> dict:
    from server.routes import audio as routes
    from server.state import state
    out: dict = {"cases": []}
    a = fixtures.get("lead_G3")
    cases = [("world_hard", 5, {}), ("world_soft", 5, {}),
             ("praat_soft", 5, {"cleanliness_percent": 50.0, "breathiness": 0.5}),
             ("world_hard", 5, {"cleanliness_percent": 100.0})]
    for b_name in ("lead_A4", "nolead_A4"):
        b = fixtures.get(b_name)
        h_a = hashlib.md5(a.audio[:1000].tobytes()).hexdigest()
        h_b = hashlib.md5(b.audio[:1000].tobytes()).hexdigest()
        for mode, shift, post in cases:
            _render(a.name, mode, shift, post)                                   # warms the cache
            warm = _render(b_name, mode, shift, post, reset_cache=False)
            cold = _render(b_name, mode, shift, post)
            yw, yc = warm["y"], cold["y"]
            same = yw is not None and yc is not None and yw.shape == yc.shape
            out["cases"].append({
                "A": a.name, "B": b_name, "mode": mode, "shift": shift, **post,
                "first_1000_equal": h_a == h_b, "cache_hit": warm["timings"].get("world_analysis") == 0.0,
                "exception_warm": warm["exc"].strip().splitlines()[-1] if warm["exc"] else None,
                "len_warm": None if yw is None else int(len(yw)), "len_cold": None if yc is None else int(len(yc)),
                "max_abs_diff": float(np.max(np.abs(yw - yc))) if same else None,
                "residual_db": _residual_db(yc, yw),
                "fails_warm": warm["fails"], "fails_cold": cold["fails"],
                "f0_warm": warm["m"].get("f0_cents"), "f0_cold": cold["m"].get("f0_cents"),
            })
    state.world_cache = {"audio_hash": None}
    resets = {}
    for fn_name in ("load_audio", "load_audio_upload", "process_audio", "render_multisample"):
        src = inspect.getsource(getattr(routes, fn_name))
        resets[fn_name] = {"resets_cache": "state.world_cache = {'audio_hash': None}" in src,
                           "calls_cache": "_world_cache_for" in src or "_pipeline_wrapper" in src}
    out["reachability"] = resets
    return out


def probe_e1() -> dict:
    """Start-of-file peak with cleanliness on."""
    rows = []
    for name in ("harm_G3", "test_2s_C4", "lead_G3"):
        for mode in ("praat_soft", "world_hard"):
            r0 = _render(name, mode, 0)
            for clean in (25.0, 50.0, 75.0, 100.0):
                r = _render(name, mode, 0, {"cleanliness_percent": clean})
                y, fx = r["y"], r["fx"]
                i = int(np.argmax(np.abs(y)))
                first = int(0.05 * fx.sr)
                rows.append({"fixture": name, "mode": mode, "clean": clean,
                             "nola_warning": any("NOLA" in w for w in r["warns"]),
                             "peak_dbfs": r["m"].get("peak_dbfs"), "peak_at_ms": 1000.0 * i / fx.sr,
                             "peak_after_50ms_dbfs": 20.0 * math.log10(max(1e-15, float(np.max(np.abs(y[first:]))))),
                             "pitch_only_peak_dbfs": r0["m"].get("peak_dbfs"),
                             "post": _vs(r, r0)["post"]})
    return {"rows": rows}


PROBES = {"B1": probe_b1, "B2": probe_b2, "B3": probe_b3, "B4": probe_b4, "B5": probe_b5,
          "E1": probe_e1}


def run_probe(name: str) -> tuple[str, dict]:
    import time
    import traceback
    t0 = time.perf_counter()
    try:
        res = PROBES[name]()
    except Exception:
        res = {"error": traceback.format_exc()}
    res["elapsed_s"] = round(time.perf_counter() - t0, 1)
    return name, res
