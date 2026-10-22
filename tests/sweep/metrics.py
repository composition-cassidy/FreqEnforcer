"""Per-render measurements and the pass/fail rule.

Regions (seconds, scaled by the stretch factor for outputs):
    body  = [onset + guard, offset - guard]   guard = min(50 ms, 20 % of the note)
    tail  = [offset, offset + TAIL_MS]         only when the fixture has a silent tail
    pre   = [onset - 200 ms, onset]            only when the note starts after >= 250 ms

Spectral measurements use a Welch average (Hann, 50 % overlap, the largest
power-of-two segment <= the body, capped at 16384) of the body.  Harmonic
bands are +-50 cents around k*f0, clamped to [2.5 bins, 0.3*f0]; the
inharmonic ratio is the power outside those bands over the power in
[f0/2, (K+0.5)*f0], K = min(40, 16 kHz / f0).  It is reported as N/A when the
Hann main lobe (+-2 bins) is wider than the widest allowed band, i.e. the
segment is too short to separate harmonics at that f0.
"""

from __future__ import annotations

import math

import numpy as np

import sweep_config as cfg


def _db(p: float) -> float:
    return float(10.0 * math.log10(p)) if p > 1e-30 else -300.0


def _mean_power(x: np.ndarray) -> float:
    return float(np.mean(np.square(x, dtype=np.float64))) if x.size else 0.0


def regions(fx, stretch: float, n_out: int | None = None) -> dict:
    """Sample-index regions for a render of *fx* stretched by *stretch*."""
    sr = fx.sr
    s = float(stretch)
    note_len = fx.offset_s - fx.onset_s
    guard = min(cfg.BODY_GUARD_S, 0.2 * note_len)
    n = n_out if n_out is not None else int(round(len(fx.audio) * s))

    def idx(t: float) -> int:
        return int(max(0, min(n, round(t * sr))))

    reg = {"body": (idx((fx.onset_s + guard) * s), idx((fx.offset_s - guard) * s)),
           "note": (idx(fx.onset_s * s), idx(fx.offset_s * s)),
           "tail": None, "pre": None}
    if fx.has_tail:
        a = idx(fx.offset_s * s)
        b = idx(fx.offset_s * s + cfg.TAIL_MS / 1000.0)
        if b - a >= int(0.05 * sr):
            reg["tail"] = (a, b)
    if fx.onset_s >= 0.25:
        reg["pre"] = (idx(fx.onset_s * s - 0.2), idx(fx.onset_s * s))
    return reg


def welch_power(seg: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, float] | None:
    from scipy.signal import welch
    n = int(seg.size)
    if n < 1024:
        return None
    nper = min(16384, 1 << int(math.floor(math.log2(n))))
    f, psd = welch(np.asarray(seg, dtype=np.float64), fs=sr, window="hann", nperseg=nper,
                   noverlap=nper // 2, detrend=False, scaling="density")
    df = float(sr) / nper
    return f, psd * df, df


def harmonic_split(f: np.ndarray, pw: np.ndarray, df: float, f0: float) -> dict | None:
    """Harmonic / inharmonic power split around harmonics of *f0*."""
    if not (np.isfinite(f0) and f0 > 0):
        return None
    hw_max = cfg.HARM_BAND_MAX_F0 * f0
    if 2.0 * df > hw_max:          # Hann main lobe wider than any band we may use
        return None
    k_max = int(max(1, min(cfg.INHARM_MAX_HARMONICS, cfg.INHARM_FMAX // f0)))
    lo, hi = 0.5 * f0, (k_max + 0.5) * f0
    in_range = (f >= lo) & (f <= hi)
    harm = np.zeros_like(f, dtype=bool)
    h1 = None
    for k in range(1, k_max + 1):
        c = k * f0
        hw = float(np.clip(c * cfg.HARM_BAND_REL, cfg.HARM_BAND_MIN_BINS * df, hw_max))
        band = np.abs(f - c) <= hw
        harm |= band
        if k == 1:
            h1 = float(np.sum(pw[band]))
    total = float(np.sum(pw[in_range]))
    harm_p = float(np.sum(pw[in_range & harm]))
    inharm_p = max(0.0, total - harm_p)
    return {"total": total, "harm": harm_p, "h1": h1 or 0.0,
            "inharm_db": _db(inharm_p) - _db(total) if total > 0 else None}


def measure_f0(x: np.ndarray, sr: int, body: tuple[int, int], note: tuple[int, int],
               target_f0: float) -> dict:
    """Median YIN f0 over the body (server.audio.pitch_yin.yin)."""
    from server.audio.pitch_yin import yin
    fmin = target_f0 / 2.2
    fmax = min(target_f0 * 2.2, sr / 4.0)
    frame = max(1024, 1 << int(math.ceil(math.log2(2.0 * sr / fmin))))
    a, b = body
    if b - a < frame:
        a, b = note
    if b - a < frame:
        return {"f0_hz": None, "f0_cents": None, "f0_voiced": None, "f0_measurable": False}
    seg = np.asarray(x[a:b], dtype=np.float64)
    n_avail = seg.size - frame
    hop = max(256, n_avail // max(1, cfg.F0_MAX_FRAMES - 1)) if n_avail > 0 else frame
    f0 = np.asarray(yin(seg, sr, fmin=fmin, fmax=fmax, frame_length=frame,
                        hop_length=hop, threshold=0.2), dtype=np.float64)
    voiced = f0[np.isfinite(f0) & (f0 > 0)]
    frac = float(voiced.size) / float(max(1, f0.size))
    if voiced.size == 0:
        return {"f0_hz": None, "f0_cents": None, "f0_voiced": frac, "f0_measurable": True}
    med = float(np.median(voiced))
    return {"f0_hz": med, "f0_cents": 1200.0 * math.log2(med / target_f0),
            "f0_voiced": frac, "f0_measurable": True}


def input_metrics(fx) -> dict:
    reg = regions(fx, 1.0, len(fx.audio))
    a, b = reg["body"]
    body = np.asarray(fx.audio[a:b], dtype=np.float64)
    out = {"body_power": _mean_power(body), "inharm_db": None, "harm_db": None, "h1_db": None}
    wp = welch_power(body, fx.sr)
    if wp is not None:
        hs = harmonic_split(*wp, fx.truth_f0)
        if hs is not None:
            out.update(inharm_db=hs["inharm_db"], harm_db=_db(hs["harm"]), h1_db=_db(hs["h1"]))
    return out


def render_metrics(out: np.ndarray, fx, stretch: float, target_f0: float, inp: dict) -> dict:
    sr = fx.sr
    y = np.asarray(out, dtype=np.float64).reshape(-1)
    n_exp = int(round(len(fx.audio) * float(stretch)))
    m: dict = {"n_out": int(y.size), "n_expected": n_exp,
               "length_delta_ms": 1000.0 * (y.size - n_exp) / sr}
    bad = ~np.isfinite(y)
    m["nonfinite"] = int(np.count_nonzero(bad))
    if m["nonfinite"]:
        return m
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    m["peak_dbfs"] = 20.0 * math.log10(peak) if peak > 1e-15 else -300.0

    reg = regions(fx, stretch, y.size)
    a, b = reg["body"]
    body = y[a:b]
    p_body = _mean_power(body)
    m["body_db"] = _db(p_body)
    m["rms_change_db"] = _db(p_body) - _db(inp["body_power"]) if body.size else None

    m.update(measure_f0(y, sr, reg["body"], reg["note"], target_f0))

    m["inharm_db"] = m["harm_db"] = m["h1_db"] = None
    wp = welch_power(body, sr)
    if wp is not None:
        hs = harmonic_split(*wp, target_f0)
        if hs is not None:
            m.update(inharm_db=hs["inharm_db"], harm_db=_db(hs["harm"]), h1_db=_db(hs["h1"]))
    m["in_inharm_db"] = inp["inharm_db"]
    m["inharm_worse_db"] = (m["inharm_db"] - inp["inharm_db"]
                            if m["inharm_db"] is not None and inp["inharm_db"] is not None else None)

    m["tail_db"] = m["tail_late_db"] = None
    if reg["tail"] is not None and p_body > 0:
        ta, tb = reg["tail"]
        if tb - ta >= int(0.05 * sr):
            m["tail_db"] = _db(_mean_power(y[ta:tb])) - _db(p_body)
            # Informational: skip the first 50 ms (release smear) to isolate sustained ringing
            la = ta + int(0.05 * sr)
            if tb - la >= int(0.05 * sr):
                m["tail_late_db"] = _db(_mean_power(y[la:tb])) - _db(p_body)
    m["pre_db"] = None
    if reg["pre"] is not None and p_body > 0:
        pa, pb = reg["pre"]
        if pb > pa:
            m["pre_db"] = _db(_mean_power(y[pa:pb])) - _db(p_body)
    return m


def evaluate(m: dict, settings: dict) -> tuple[list[str], dict, float]:
    """Return (failed metric names, per-metric exceedance ratio, severity)."""
    fails: list[str] = []
    ex: dict[str, float] = {}
    if m.get("exception"):
        return ["exception"], {"exception": 100.0}, 1000.0
    if m.get("nonfinite"):
        fails.append("nonfinite")
        ex["nonfinite"] = 100.0
    if abs(m.get("length_delta_ms", 0.0)) > cfg.LENGTH_TOL_MS:
        fails.append("length")
        ex["length"] = min(3.0, abs(m["length_delta_ms"]) / cfg.LENGTH_TOL_MS)
    if "nonfinite" in fails:
        return fails, ex, 500.0 + sum(ex.values())
    if m["peak_dbfs"] > cfg.PEAK_DBFS:
        fails.append("peak")
        ex["peak"] = 1.0 + (m["peak_dbfs"] - cfg.PEAK_DBFS) / 3.0
    if m.get("f0_measurable"):
        if m["f0_cents"] is None or (m.get("f0_voiced") or 0.0) < 0.5:
            fails.append("f0")
            ex["f0"] = 10.0
        elif abs(m["f0_cents"]) > cfg.F0_ERR_CENTS:
            fails.append("f0")
            ex["f0"] = min(20.0, abs(m["f0_cents"]) / cfg.F0_ERR_CENTS)
    if m.get("inharm_worse_db") is not None and m["inharm_worse_db"] > cfg.INHARM_WORSE_DB:
        fails.append("inharm")
        ex["inharm"] = m["inharm_worse_db"] / cfg.INHARM_WORSE_DB
    if m.get("tail_db") is not None and m["tail_db"] > cfg.TAIL_DB:
        fails.append("tail")
        ex["tail"] = 1.0 + (m["tail_db"] - cfg.TAIL_DB) / 10.0
    clean = float(settings.get("cleanliness_percent", 0.0))
    if (clean <= cfg.RMS_LOSS_MAX_CLEAN and m.get("rms_change_db") is not None
            and m["rms_change_db"] < -cfg.RMS_LOSS_DB):
        fails.append("rms")
        ex["rms"] = -m["rms_change_db"] / cfg.RMS_LOSS_DB
    return fails, ex, float(sum(ex.values()))


def metric_value(m: dict, metric: str):
    """Signed scalar used to compare a render against its baseline for *metric*."""
    return {
        "length": abs(m.get("length_delta_ms") or 0.0),
        "peak": m.get("peak_dbfs"),
        "f0": None if m.get("f0_cents") is None else abs(m["f0_cents"]),
        "inharm": m.get("inharm_worse_db"),
        "tail": m.get("tail_db"),
        "rms": None if m.get("rms_change_db") is None else -m["rms_change_db"],
    }.get(metric)


# Margin by which a render must be worse than its failing baseline before the
# post-pitch stages (rather than the pitch stage) are blamed.
WORSE_MARGIN = {"length": cfg.LENGTH_TOL_MS, "peak": 1.0, "f0": cfg.F0_ERR_CENTS,
                "inharm": cfg.INHARM_WORSE_DB, "tail": 6.0, "rms": cfg.RMS_LOSS_DB}
