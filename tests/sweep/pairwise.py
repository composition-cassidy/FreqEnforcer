"""Seeded greedy (AETG-style) pairwise covering array, no dependencies.

Each new row starts from the factor value that appears in the most uncovered
pairs, then fills the remaining factors in random order, picking per factor
the value that covers the most still-uncovered pairs with the values already
chosen.  The best of N candidate rows is kept.  Deterministic for a seed.
"""

from __future__ import annotations

import itertools
import random


def _pairs_of(row: list[int]) -> set[tuple[int, int, int, int]]:
    return {(i, row[i], j, row[j]) for i, j in itertools.combinations(range(len(row)), 2)}


def covering_array(sizes: list[int], seed: int = 1, candidates: int = 60) -> list[list[int]]:
    """Rows of value indices covering every value pair of every factor pair."""
    rng = random.Random(seed)
    k = len(sizes)
    uncovered = {(i, a, j, b) for i, j in itertools.combinations(range(k), 2)
                 for a in range(sizes[i]) for b in range(sizes[j])}
    rows: list[list[int]] = []
    while uncovered:
        # Factor value with the most uncovered pairs seeds every candidate
        counts: dict[tuple[int, int], int] = {}
        for i, a, j, b in uncovered:
            counts[(i, a)] = counts.get((i, a), 0) + 1
            counts[(j, b)] = counts.get((j, b), 0) + 1
        top = max(counts.values())
        seeds = sorted(fv for fv, c in counts.items() if c == top)

        best_row, best_gain = None, -1
        for _ in range(candidates):
            f0, v0 = rng.choice(seeds)
            row = [-1] * k
            row[f0] = v0
            order = [f for f in range(k) if f != f0]
            rng.shuffle(order)
            for f in order:
                gains = []
                for v in range(sizes[f]):
                    g = 0
                    for g_f in range(k):
                        if row[g_f] < 0 or g_f == f:
                            continue
                        key = (g_f, row[g_f], f, v) if g_f < f else (f, v, g_f, row[g_f])
                        g += key in uncovered
                    gains.append(g)
                m = max(gains)
                row[f] = rng.choice([v for v, g in enumerate(gains) if g == m])
            gain = len(_pairs_of(row) & uncovered)
            if gain > best_gain:
                best_row, best_gain = row, gain
        rows.append(best_row)
        uncovered -= _pairs_of(best_row)
    return rows


def coverage(rows: list[list[int]], sizes: list[int]) -> float:
    k = len(sizes)
    need = {(i, a, j, b) for i, j in itertools.combinations(range(k), 2)
            for a in range(sizes[i]) for b in range(sizes[j])}
    have = set().union(*(_pairs_of(r) for r in rows)) if rows else set()
    return len(need & have) / len(need)


def build(factors: list[tuple[str, str, list]], seed: int, candidates: int) -> tuple[list[dict], float]:
    """Pairwise rows as {param_key: value} dicts, plus verified pair coverage."""
    sizes = [len(vals) for _, _, vals in factors]
    rows = covering_array(sizes, seed=seed, candidates=candidates)
    cov = coverage(rows, sizes)
    return [{key: vals[r[i]] for i, (_, key, vals) in enumerate(factors)} for r in rows], cov
