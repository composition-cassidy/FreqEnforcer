"""Targeted experiments, one per suspected bug (B1-B5).

Each probe returns a JSON-serialisable dict that report.py turns into the
evidence tables.  Probes call server functions directly with different
arguments (never edited code); the only intervention is B4's wrapping of
pyworld entry points to log which analyses run, restored afterwards.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import math
import warnings

import numpy as np

import counterfactual as cf
import fixtures
import metrics
import sweep_config as cfg
import worker


def _freq(note: str) -> float:
    from server.utils.note_utils import note_name_to_freq
    return float(note_name_to_freq(note))


def _ctx(name: str, mode: str, shift: int, stretch: float = 1.0, post: dict | None = None):
    fx = fixtures.get(name)
    tnote = fixtures.target_note(fx, shift)
    s = worker.make_settings(mode, tnote, stretch, dict(post or {}))
    return fx, s, fixtures.detected(name), tnote, _freq(tnote)


_PITCHED: dict[tuple, tuple] = {}


def _pitched(fx, s, det):
    from server.state import state
    key = (fx.name, s["pitch_mode"], s["target_note"], s["stretch_factor"])
    if key not in _PITCHED:
        state.detected_pitch = dict(det)
        with _quiet():
            _PITCHED[key] = cf.pitch_stage(fx.audio, fx.sr, s)
    return _PITCHED[key]


@contextlib.contextmanager
def _quiet():
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        yield


def _body_db(y, fx, stretch=1.0) -> float:
    a, b = metrics.regions(fx, stretch, len(y))["body"]
    p = float(np.mean(np.square(np.asarray(y[a:b], dtype=np.float64))))
    return 10.0 * math.log10(p) if p > 1e-30 else -300.0


def _m(y, fx, s, tf0):
    m, fails, _ex, _sev = worker.measure(y, fx, s["stretch_factor"], tf0, s)
    return m, fails


def _pick(m: dict, *keys) -> dict:
    return {k: m.get(k) for k in keys}


def _post(fx, s, det, tf0, fixes=frozenset(), diags=frozenset(), pitched=None, wc=None):
    if pitched is None:
        pitched, wc = _pitched(fx, s, det)
    span = metrics.regions(fx, s["stretch_factor"])["note"]
    with _quiet():
        return cf.post_stage(pitched, fx.sr, s, wc, det, tf0, span, frozenset(fixes), frozenset(diags))


# ---------------------------------------------------------------------------
# B1: cleanliness gets the ORIGINAL audio's f0
# ---------------------------------------------------------------------------

def probe_b1() -> dict:
    out: dict = {"stage_rows": [], "cache_path": []}
    for name in ("harm_G3", "test_2s_C4"):
        for shift in cfg.SHIFTS:
            for clean in (25.0, 50.0, 75.0, 100.0):
                fx, s, det, tnote, tf0 = _ctx(name, "world_hard", shift,
                                              post={"cleanliness_percent": clean})
                pitched, wc = _pitched(fx, s, det)
                before = _body_db(pitched, fx)
                y_app = _post(fx, s, det, tf0)
                y_fix = _post(fx, s, det, tf0, {"F1"})
                m_app, f_app = _m(y_app, fx, s, tf0)
                m_fix, f_fix = _m(y_fix, fx, s, tf0)
                out["stage_rows"].append({
                    "fixture": name, "shift": shift, "target": tnote, "clean": clean,
                    "cached_f0_median": float(np.median(wc["f0"][wc["f0"] > 0])),
                    "target_f0": tf0,
                    "stage_db_app": _body_db(y_app, fx) - before,
                    "stage_db_fix": _body_db(y_fix, fx) - before,
                    "f0_cents_app": m_app.get("f0_cents"), "f0_cents_fix": m_fix.get("f0_cents"),
                    "harm_db_app": m_app.get("harm_db"), "harm_db_fix": m_fix.get("harm_db"),
                    "fails_app": f_app, "fails_fix": f_fix,
                })
    # Non-WORLD mode: breathiness != 1 switches cleanliness from pyin to the cache
    for clean in (50.0, 100.0):
        for breath, path in ((1.0, "pyin (no cache)"), (0.5, "WORLD cache")):
            fx, s, det, tnote, tf0 = _ctx("harm_G3", "praat_soft", 5,
                                          post={"cleanliness_percent": clean, "breathiness": breath})
            y, _t, _w, exc = worker.run_pipeline_once(fx, s, det)
            m, fails = _m(y, fx, s, tf0)
            row = {"mode": "praat_soft", "shift": 5, "clean": clean, "breath": breath, "f0_source": path,
                   "fails": fails, **_pick(m, "rms_change_db", "f0_cents", "inharm_worse_db")}
            out["cache_path"].append(row)
            if breath != 1.0:
                y2 = _post(fx, s, det, tf0, {"F1"})
                m2, f2 = _m(y2, fx, s, tf0)
                out["cache_path"].append({**row, "f0_source": "WORLD cache + F1 (rescaled)", "fails": f2,
                                          **_pick(m2, "rms_change_db", "f0_cents", "inharm_worse_db")})
    head = next(r for r in out["stage_rows"]
                if r["fixture"] == "harm_G3" and r["shift"] == 5 and r["clean"] == 100.0)
    out["headline"] = head
    return out


# ---------------------------------------------------------------------------
# B2: mask FWHM vs STFT resolution, with the CORRECT f0
# ---------------------------------------------------------------------------

def _ideal_f0(fx, stretch=1.0) -> np.ndarray:
    n = int(round(len(fx.audio) * stretch))
    t = np.arange(int(1000.0 * n / fx.sr / 5.0) + 1) * 0.005
    on, off = fx.onset_s * stretch, fx.offset_s * stretch
    return np.where((t >= on) & (t < off), fx.truth_f0, 0.0)


def probe_b2() -> dict:
    from server.audio.cleanliness import apply_cleanliness
    rows = []
    for name in ("pure_C2", "pure_G3", "pure_A4"):
        fx = fixtures.get(name)
        inp = worker.input_metrics(fx)
        f0_ideal = _ideal_f0(fx)
        for clean in range(0, 101, 10):
            with _quiet():
                y = apply_cleanliness(fx.audio, fx.sr, float(clean), cached_f0=f0_ideal,
                                      cached_voiced=f0_ideal > 0)
                y_pyin = apply_cleanliness(fx.audio, fx.sr, float(clean))
            m = metrics.render_metrics(y, fx, 1.0, fx.truth_f0, inp)
            mp = metrics.render_metrics(y_pyin, fx, 1.0, fx.truth_f0, inp)
            rows.append({
                "fixture": name, "f0": fx.truth_f0, "clean": clean,
                "fwhm_hz": cfg.clean_fwhm_hz(clean), "fwhm_over_bin": cfg.clean_fwhm_hz(clean) / cfg.STFT_BIN_HZ,
                "harm_loss_db": m["harm_db"] - inp["harm_db"],
                "h1_loss_db": m["h1_db"] - inp["h1_db"],
                "harm_loss_db_pyin": mp["harm_db"] - inp["harm_db"],
                "inharm_db": m["inharm_db"], "in_inharm_db": inp["inharm_db"],
                "tail_db": m["tail_db"], "tail_late_db": m["tail_late_db"],
                "rms_change_db": m["rms_change_db"],
            })
    return {"rows": rows, "bin_hz": cfg.STFT_BIN_HZ, "hann_mainlobe_hz": 4 * cfg.STFT_BIN_HZ}


# ---------------------------------------------------------------------------
# B3: smart low cut keyed to state.detected_pitch (original f0)
# ---------------------------------------------------------------------------

def probe_b3() -> dict:
    from server.audio.cleanliness import compute_smart_lowcut
    rows = []
    for name in ("harm_C2", "harm_G3", "harm_A4", "vowel_D3"):
        for mode in ("praat_soft", "world_hard"):
            for shift in cfg.SHIFTS:
                fx, s0, det, tnote, tf0 = _ctx(name, mode, shift)
                pitched, wc = _pitched(fx, s0, det)
                m0, _ = _m(_post(fx, s0, det, tf0), fx, s0, tf0)
                det_f0 = float(det.get("freq_hz") or 50.0)
                for pct in (50.0, 100.0):
                    s = worker.make_settings(mode, tnote, 1.0, {"clean_lowcut_percent": pct})
                    m_app, f_app = _m(_post(fx, s, det, tf0), fx, s, tf0)
                    m_fix, f_fix = _m(_post(fx, s, det, tf0, {"F3"}), fx, s, tf0)
                    cut_app = compute_smart_lowcut(det_f0, pct)
                    cut_fix = compute_smart_lowcut(tf0, pct)
                    rows.append({
                        "fixture": name, "mode": mode, "shift": shift, "lowcut": pct,
                        "detected_f0": det_f0, "target_f0": tf0,
                        "cutoff_app": cut_app, "cutoff_fix": cut_fix, "cut_over_f0": cut_app / tf0,
                        "h1_db_app": m_app["h1_db"] - m0["h1_db"], "h1_db_fix": m_fix["h1_db"] - m0["h1_db"],
                        "rms_db_app": m_app["rms_change_db"] - m0["rms_change_db"],
                        "rms_db_fix": m_fix["rms_change_db"] - m0["rms_change_db"],
                        "fails_app": f_app, "fails_fix": f_fix,
                    })
    return {"rows": rows}


# ---------------------------------------------------------------------------
# B4: breathiness = second WORLD pass (harvest, default range); 1/0 at amount 0
# ---------------------------------------------------------------------------

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


def _dio_cache(x: np.ndarray, sr: int) -> dict:
    import pyworld as pw
    x64 = np.ascontiguousarray(x, dtype=np.float64)
    f0, t = pw.dio(x64, sr, f0_floor=50.0, f0_ceil=500.0)
    f0 = pw.stonemask(x64, f0, t, sr)
    return {"f0": f0, "timeaxis": t, "sp": pw.cheaptrick(x64, f0, t, sr), "ap": pw.d4c(x64, f0, t, sr), "sr": sr}


def _residual_db(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    a = np.asarray(a[:n], np.float64)
    b = np.asarray(b[:n], np.float64)
    e = float(np.sum((a - b) ** 2))
    return 10.0 * math.log10(e / max(1e-30, float(np.sum(a ** 2)))) if e > 0 else -300.0


def probe_b4() -> dict:
    import pyworld as pw
    from server.audio.autotuner import apply_breathiness
    out: dict = {"calls": [], "range": [], "identity": [], "div0": []}

    # (a) which WORLD analyses run per render
    for mode, post in (("world_hard", {"cleanliness_percent": 50.0, "breathiness": 0.5}),
                       ("praat_soft", {"cleanliness_percent": 50.0, "breathiness": 0.5}),
                       ("praat_soft", {"cleanliness_percent": 50.0, "breathiness": 1.0})):
        fx, s, det, tnote, tf0 = _ctx("harm_G3", mode, 5, post=post)
        calls: list = []
        with _log_pyworld(calls):
            worker.run_pipeline_once(fx, s, det)
        out["calls"].append({"mode": mode, **post, "calls": calls})

    # (b) analysis f0 range: app (harvest default) vs dio 50-500 vs correct f0 (F4)
    for name in ("harm_C2", "harm_G3", "harm_A4", "harm_A5"):
        for shift in (-12, 0, 12):
            fx, s, det, tnote, tf0 = _ctx(name, "praat_soft", shift, post={"breathiness": 0.5})
            pitched, wc = _pitched(fx, s, det)
            x64 = np.ascontiguousarray(pitched, dtype=np.float64)
            with _quiet():
                hf0, _t = pw.harvest(x64, fx.sr)
            hv = hf0[hf0 > 0]
            row = {"fixture": name, "shift": shift, "target_f0": tf0,
                   "harvest_median_f0": float(np.median(hv)) if hv.size else None,
                   "harvest_voiced_frac": float(hv.size / max(1, hf0.size))}
            s1 = dict(s, breathiness=1.0)
            m_ref, _ = _m(_post(fx, s1, det, tf0), fx, s1, tf0)
            row["ref_f0_cents"] = m_ref.get("f0_cents")
            span = metrics.regions(fx, 1.0)["note"]
            for label, wcache in (("app_harvest", None), ("dio_50_500", "dio"), ("correct_f0", "oracle")):
                with _quiet():
                    if wcache == "dio":
                        wcache = _dio_cache(pitched, fx.sr)
                    elif wcache == "oracle":
                        wcache = cf.oracle_world_cache(pitched, fx.sr, span, tf0)
                    y = apply_breathiness(pitched, fx.sr, amount=0.5, hf_bias=0.0, world_cache=wcache)
                m, fails = _m(y, fx, s, tf0)
                row[label] = {"fails": fails, **_pick(m, "f0_cents", "f0_voiced", "inharm_worse_db",
                                                       "rms_change_db", "tail_db")}
            out["range"].append(row)

    # (c) near-identity resynthesis: breath 0.99 vs 1.0 (skipped) after cleanliness.
    #     Shift 0 so the cached f0 is right and B1 does not interfere.
    for name in ("harm_G3", "test_2s_C4"):
        for clean in (0.0, 75.0):
            fx, s, det, tnote, tf0 = _ctx(name, "world_hard", 0, post={"cleanliness_percent": clean})
            y1, *_ = worker.run_pipeline_once(fx, s, det)
            s2 = dict(s, breathiness=0.99)
            y2, *_ = worker.run_pipeline_once(fx, s2, det)
            m1, _ = _m(y1, fx, s, tf0)
            m2, _ = _m(y2, fx, s2, tf0)
            out["identity"].append({"fixture": name, "clean": clean, "residual_db": _residual_db(y1, y2),
                                    "inharm_db_b1": m1["inharm_db"], "inharm_db_b099": m2["inharm_db"],
                                    "f0_cents_b1": m1["f0_cents"], "f0_cents_b099": m2["f0_cents"]})

    # (d) amount 0 -> effective_amount 0 -> ap ** (1/0)
    for name in ("harm_G3", "breathy_A3"):
        fx, s0, det, tnote, tf0 = _ctx(name, "praat_soft", 0)
        pitched, _wc = _pitched(fx, s0, det)
        sp_bins = 1025
        freq_axis = np.linspace(0.0, fx.sr / 2.0, sp_bins)
        ramp = np.clip((freq_axis - 1500.0) / 3000.0, 0.0, 1.0)
        ref = None
        for amount, hf_bias in ((0.01, 0.0), (0.0, 0.0), (0.0, 1.0)):
            bias = (1.0 - hf_bias) + ramp * hf_bias
            eff = 1.0 + (amount - 1.0) * bias
            s = worker.make_settings("praat_soft", tnote, 1.0, {"breathiness": amount, "hf_bias": hf_bias})
            y, _t, warns, exc = worker.run_pipeline_once(fx, s, det)
            m, fails = _m(y, fx, s, tf0)
            if ref is None:
                ref = y
            out["div0"].append({
                "fixture": name, "breath": amount, "hf_bias": hf_bias,
                "zero_exponent_bins": int(np.count_nonzero(eff == 0.0)),
                "warnings": warns, "exception": exc, "nonfinite": m.get("nonfinite"),
                "fails": fails, "residual_vs_0.01_db": _residual_db(ref, y) if y is not None else None,
                **_pick(m, "inharm_worse_db", "f0_cents", "rms_change_db"),
            })
    return out


# ---------------------------------------------------------------------------
# B5: _world_cache_for keys on md5(first 1000 samples)
# ---------------------------------------------------------------------------

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
            ta, tb = fixtures.target_note(a, shift), fixtures.target_note(b, shift)
            sa = worker.make_settings(mode, ta, 1.0, post)
            sb = worker.make_settings(mode, tb, 1.0, post)
            tf0 = _freq(tb)
            worker.run_pipeline_once(a, sa, fixtures.detected(a.name))            # warms the cache
            y_warm, t_warm, _w, exc_warm = worker.run_pipeline_once(b, sb, fixtures.detected(b.name),
                                                                     reset_cache=False)
            y_cold, t_cold, _w2, exc_cold = worker.run_pipeline_once(b, sb, fixtures.detected(b.name))
            m_w, f_w = _m(y_warm, b, sb, tf0)
            m_c, f_c = _m(y_cold, b, sb, tf0)
            same = (y_warm is not None and y_cold is not None and y_warm.shape == y_cold.shape)
            out["cases"].append({
                "A": a.name, "B": b_name, "mode": mode, "shift": shift, **post,
                "hash_equal": h_a == h_b, "cache_hit": t_warm.get("world_analysis") == 0.0,
                "exception_warm": exc_warm.strip().splitlines()[-1] if exc_warm else None,
                "exception_cold": exc_cold.strip().splitlines()[-1] if exc_cold else None,
                "len_warm": None if y_warm is None else int(len(y_warm)),
                "len_cold": None if y_cold is None else int(len(y_cold)),
                "max_abs_diff": float(np.max(np.abs(y_warm - y_cold))) if same else None,
                "residual_db": _residual_db(y_cold, y_warm) if y_warm is not None and y_cold is not None else None,
                "fails_warm": f_w, "fails_cold": f_c,
                "warm": _pick(m_w, "f0_cents", "rms_change_db", "inharm_worse_db", "length_delta_ms"),
                "cold": _pick(m_c, "f0_cents", "rms_change_db", "inharm_worse_db", "length_delta_ms"),
            })
    state.world_cache = {"audio_hash": None}

    # Reachability: which endpoints reset the cache before a new audio is processed
    resets = {}
    for fn_name in ("load_audio", "load_audio_upload", "process_audio", "render_multisample"):
        src = inspect.getsource(getattr(routes, fn_name))
        resets[fn_name] = {"resets_cache": "state.world_cache = {'audio_hash': None}" in src,
                           "calls_cache": "_world_cache_for" in src or "_run_pipeline" in src
                                          or "_pipeline_wrapper" in src}
    out["reachability"] = resets
    return out


# ---------------------------------------------------------------------------
# E1 (found by the sweep): cleanliness ISTFT edge blow-up at the file start
# ---------------------------------------------------------------------------

def probe_e1() -> dict:
    rows = []
    for name in ("harm_G3", "test_2s_C4", "lead_G3"):
        for clean in (25.0, 50.0, 75.0, 100.0):
            fx, s, det, tnote, tf0 = _ctx(name, "praat_soft", 0, post={"cleanliness_percent": clean})
            y, _t, warns, _exc = worker.run_pipeline_once(fx, s, det)
            y_pad = _post(fx, s, det, tf0, {"F5"})
            i = int(np.argmax(np.abs(y)))
            first = int(0.05 * fx.sr)
            rows.append({
                "fixture": name, "clean": clean,
                "nola_warning": any("NOLA" in w for w in warns),
                "peak_app": float(np.abs(y[i])), "peak_at_ms": 1000.0 * i / fx.sr,
                "peak_app_after_50ms": float(np.max(np.abs(y[first:]))),
                "peak_padded": float(np.max(np.abs(y_pad))),
                "input_peak": float(np.max(np.abs(fx.audio))),
                "first_nonzero_ms": 1000.0 * int(np.argmax(np.abs(fx.audio) > 0)) / fx.sr,
            })
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
