from __future__ import annotations


def parse_harmonic_ceiling_arg(raw: str | None) -> dict[int, float]:
    txt = str(raw or "").strip()
    if not txt:
        return {}
    out: dict[int, float] = {}
    parts = [p.strip() for p in txt.split(",") if str(p).strip()]
    for p in parts:
        if ":" not in p:
            raise ValueError(f"Invalid harmonic ceiling pair: {p}")
        k_txt, v_txt = p.split(":", 1)
        k = int(k_txt.strip())
        v = float(v_txt.strip())
        if k <= 0:
            raise ValueError(f"Harmonic index must be >= 1: {k}")
        out[int(k)] = float(v)
    return out
