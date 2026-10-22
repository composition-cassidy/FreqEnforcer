"""Shared failure classification for sweep rows.

One rule set, used by report.py, freeze_baseline.py and
tests/test_pipeline_combos.py:

  inherited        the group's pitch-only render fails the metric too and the
                   render is not worse by more than metrics.WORSE_MARGIN
  pitch_miss       the pitch-only render already misses the target note, so
                   f0 / inharm (both measured against the target) say nothing
                   about the post-pitch stages
  breath_intended  breathiness > 1 adds aperiodicity on purpose; the failure
                   clears with breathiness 1
  anything else    a post-pitch failure

Pass rates:
  raw       no failed metric at all
  post      no post-pitch failure
  post_ex   no post-pitch failure other than breath_intended
"""

from __future__ import annotations

import metrics

NON_POST = ("inherited", "pitch_miss")


def gkey(r) -> tuple:
    return (r["fixture"], r["mode"], r["shift"], r["stretch"])


def expand(c: str) -> list[str]:
    """Root-cause labels named by one attribution entry."""
    if c.startswith("joint:") or c.startswith("multi:"):
        return [cause_key(x) for x in c.split(":", 1)[1].split("+")]
    return [cause_key(c)]


def cause_key(c: str) -> str:
    return "clean_mask" if c.startswith("clean_mask_") else c


def inherited(metric: str, m: dict, base: dict) -> bool:
    """Render fails *metric* only as much as its pitch-only render does."""
    if metric not in base["fails"]:
        return False
    if metric in ("exception", "nonfinite"):
        return True
    v, vb = metrics.metric_value(m, metric), metrics.metric_value(base["metrics"], metric)
    return v is None or vb is None or v - vb <= metrics.WORSE_MARGIN[metric]


class Classifier:
    def __init__(self, rows):
        self.base = {gkey(r): r for r in rows if "baseline" in r["sets"]}

    def causes(self, row, metric) -> list[str]:
        if "baseline" in row["sets"]:          # the pitch-only render itself
            return ["inherited"]
        att = row["attribution"].get(metric, ["unexplained"])
        base = self.base.get(gkey(row))
        if (metric in ("f0", "inharm") and att != ["inherited"] and base is not None
                and "f0" in base["fails"]):
            return ["pitch_miss"]
        return att

    def is_post(self, row, metric) -> bool:
        return not all(c in NON_POST for c in self.causes(row, metric))

    def post_fails(self, row) -> list[str]:
        return [m for m in row["fails"] if self.is_post(row, m)]

    def intended(self, row, metric) -> bool:
        labels = {x for c in self.causes(row, metric) for x in expand(c)}
        return labels == {"breath_intended"}

    def post_ex_fails(self, row) -> list[str]:
        return [m for m in self.post_fails(row) if not self.intended(row, m)]

    def post_exceed(self, row) -> dict:
        ex = row.get("exceed") or {}
        pf = set(self.post_fails(row))
        return {m: v for m, v in ex.items() if m in pf}

    def post_severity(self, row) -> float:
        return float(sum(self.post_exceed(row).values()))

    def dominant(self, row) -> str:
        ex = self.post_exceed(row)
        return max(ex, key=ex.get) if ex else "-"

    def pass_rates(self, rows) -> dict:
        n = len(rows)
        raw = sum(1 for r in rows if not r["fails"])
        post = sum(1 for r in rows if not self.post_fails(r))
        post_ex = sum(1 for r in rows if not self.post_ex_fails(r))
        return {"n": n, "raw": raw, "post": post, "post_ex": post_ex,
                "raw_pct": 100.0 * raw / max(1, n), "post_pct": 100.0 * post / max(1, n),
                "post_ex_pct": 100.0 * post_ex / max(1, n)}
