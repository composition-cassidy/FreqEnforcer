"""Post-pitch pipeline combinations that failed worst in the sweep.

The 30 combinations below are the worst renders of the pre-fix sweep
(tests/sweep/, ranked by post-pitch severity; see docs/SWEEP_REPORT.md).
Each is rendered through _run_pipeline with the sweep's fixtures and metrics,
next to its pitch-only twin, and must have no post-pitch failure under the
sweep's unchanged thresholds (tests/sweep/sweep_config.py):

- a failure the pitch-only render has too, and that the post stages don't
  make worse beyond the metric's margin, belongs to the pitch stage;
- f0/inharm failures are the pitch stage's when its own render already
  misses the target note (both are measured against that target);
- breathiness > 1 may fail the inharmonic/tail rules: adding aperiodic
  energy is what it is for, provided the failure clears at breathiness 1.

Also: two files that share their first samples (leading digital silence)
must not share a WORLD analysis.

Combination id: fixture | mode | shift | stretch | lowcut | cleanliness |
hf_rollback | breathiness | hf_bias.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "sweep"))
import classify  # noqa: E402
import fixtures  # noqa: E402
import worker  # noqa: E402

WORST_30 = [
    "harm_A4|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0",
    "harm_A5|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0",
    "vowel_D3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1",
    "vowel_D3|praat_soft|+0|x1|lc0|cl100|rb0|br1|hb0",
    "vowel_D3|praat_soft|+12|x1|lc0|cl100|rb0|br1|hb0",
    "breathy_A3|praat_soft|-12|x1|lc0|cl100|rb0|br1|hb0",
    "harm_A5|praat_soft|-7|x1|lc0|cl75|rb0|br1|hb0",
    "vowel_D3|stft_pitchshift|+0|x1|lc0|cl100|rb0|br1|hb0",
    "harm_A5|sine_spectral|+0|x1|lc0|cl75|rb0|br1|hb0",
    "harm_G3|sine_spectral|+0|x1|lc0|cl100|rb0|br1|hb0",
    "harm_G3|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1",
    "harm_A4|praat_soft|+5|x1|lc0|cl100|rb0|br1|hb0",
    "harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br5|hb0",
    "harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br0.5|hb0",
    "harm_A4|stft_pitchshift|-12|x1|lc0|cl25|rb0|br2|hb0",
    "harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br5|hb0",
    "harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br5|hb0",
    "harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br2|hb0",
    "harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0.5|hb0",
    "harm_A4|world_vt|+5|x1|lc0|cl25|rb0|br0|hb0",
    "harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br2|hb0",
    "harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br0.5|hb0",
    "harm_A4|world_soft|+5|x1|lc0|cl25|rb0|br0|hb0",
    "harm_A4|stft_pitchshift|-12|x1|lc0|cl50|rb0|br5|hb0",
    "harm_A4|world_soft|+5|x1|lc50|cl25|rb0|br0.5|hb1",
    "harm_A4|stft_pitchshift|-7|x1|lc0|cl100|rb0|br0|hb0",
    "harm_A4|praat_soft|+12|x1|lc50|cl100|rb50|br1|hb1",
    "harm_A4|stft_pitchshift|-7|x1|lc0|cl100|rb0|br0.5|hb0",
    "harm_A4|world_hnm|+5|x1.5|lc0|cl50|rb50|br0|hb0",
    "harm_A5|praat_soft|+0|x1|lc0|cl75|rb0|br1|hb0",
]


def parse(cid: str):
    p = cid.split("|")
    post = {"clean_lowcut_percent": float(p[4][2:]), "cleanliness_percent": float(p[5][2:]),
            "clean_hf_rollback_percent": float(p[6][2:]), "breathiness": float(p[7][2:]),
            "hf_bias": float(p[8][2:])}
    return p[0], p[1], int(p[2]), float(p[3][1:]), post


def render(fixture: str, mode: str, shift: int, stretch: float, post: dict, reset_cache: bool = True):
    from server.utils.note_utils import note_name_to_freq
    fx = fixtures.get(fixture)
    tnote = fixtures.target_note(fx, shift)
    settings = worker.make_settings(mode, tnote, stretch, post)
    out, timings, _warns, exc = worker.run_pipeline_once(fx, settings, fixtures.detected(fixture),
                                                         reset_cache=reset_cache)
    m, fails, _ex, _sev = worker.measure(out, fx, stretch, float(note_name_to_freq(tnote)), settings, exc)
    return {"out": out, "m": m, "fails": fails, "timings": timings, "exc": exc}


@pytest.mark.parametrize("cid", WORST_30)
def test_no_post_pitch_failure(cid):
    fixture, mode, shift, stretch, post = parse(cid)
    r = render(fixture, mode, shift, stretch, post)
    assert r["exc"] is None, r["exc"]
    base = render(fixture, mode, shift, stretch, {})
    base_row = {"fails": base["fails"], "metrics": base["m"]}
    unexplained = {}
    for metric in r["fails"]:
        if classify.inherited(metric, r["m"], base_row):
            continue
        if metric in ("f0", "inharm") and "f0" in base["fails"]:
            continue                                           # pitch stage missed the note
        if post["breathiness"] > 1.0 and metric in ("inharm", "tail"):
            plain = render(fixture, mode, shift, stretch, dict(post, breathiness=1.0, hf_bias=0.0))
            if metric not in plain["fails"] or classify.inherited(metric, plain["m"], base_row):
                continue                                       # intended aperiodicity
        unexplained[metric] = {k: r["m"].get(k) for k in ("peak_dbfs", "f0_cents", "inharm_worse_db",
                                                          "tail_db", "rms_change_db", "length_delta_ms")}
    assert not unexplained, f"{cid}: post-pitch failures {unexplained}"


@pytest.mark.parametrize("mode,post", [
    ("world_hard", {}),
    ("world_soft", {}),
    ("world_hard", {"cleanliness_percent": 100.0}),
    ("praat_soft", {"cleanliness_percent": 50.0, "breathiness": 0.5}),
])
def test_cache_does_not_collide_on_shared_leading_silence(mode, post):
    a, b = fixtures.get("lead_G3"), fixtures.get("lead_A4")
    assert np.array_equal(a.audio[:1000], b.audio[:1000])     # same first samples (300 ms of zeros)
    render("lead_G3", mode, 5, 1.0, post)                     # leaves A's WORLD analysis cached
    warm = render("lead_A4", mode, 5, 1.0, post, reset_cache=False)
    cold = render("lead_A4", mode, 5, 1.0, post)
    assert warm["timings"].get("world_analysis") != 0.0, "B reused A's WORLD analysis"
    assert warm["out"].shape == cold["out"].shape
    assert np.array_equal(warm["out"], cold["out"])
