"""Shared pytest setup for FreqEnforcer tests."""

from __future__ import annotations

import sys
import warnings
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Mirror the runtime import roots: repo root (server.*) and server/ (bare audio.*).
for _p in (str(ROOT / "server"), str(ROOT), str(ROOT / "tests" / "golden")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=r"pkg_resources is deprecated")

# Filled by tests/test_regression.py: one dict per compared case.
REGRESSION_RESULTS: list[dict] = []


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: renders a 10 s fixture (runs by default)")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not REGRESSION_RESULTS:
        return
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for r in REGRESSION_RESULTS:
        by_mode[r["mode"]].append(r)

    tr = terminalreporter
    tr.section("golden regression by mode")
    tr.write_line(f"{'mode':<22}{'pass':>6}{'fail':>6}{'exact':>7}{'worst max|diff|':>18}{'worst flux':>12}")
    for mode in sorted(by_mode):
        rows = by_mode[mode]
        n_pass = sum(r["passed"] for r in rows)
        n_exact = sum(r["max_abs_diff"] == 0.0 for r in rows)
        worst_diff = max(r["max_abs_diff"] for r in rows)
        fluxes = [r["flux_rel_diff"] for r in rows if r["flux_rel_diff"] is not None]
        worst_flux = f"{max(fluxes):.2e}" if fluxes else "-"
        tr.write_line(f"{mode:<22}{n_pass:>6}{len(rows) - n_pass:>6}{n_exact:>7}"
                      f"{worst_diff:>18.3e}{worst_flux:>12}")
    failed = [r for r in REGRESSION_RESULTS if not r["passed"]]
    for r in failed:
        tr.write_line(f"FAIL {r['id']}: {r['reason']}")
