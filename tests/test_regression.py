"""Golden-file regression tests for the FreqEnforcer DSP backend.

Every case in tests/golden/manifest.json is re-rendered by calling the DSP
functions directly (see tests/golden/matrix.py) and compared with its float32
reference WAV.

Pass criteria (either is sufficient):

1. Sample-exact-ish: same length and max |ref - new| < MAX_ABS_DIFF (1e-4,
   about -80 dBFS; float32 storage error is ~1e-7).
2. Fallback for cross-machine numeric drift: same length and the relative
   spectral-flux difference is below FLUX_REL_THRESHOLD (0.05 %).

   Spectral flux is computed on Hann-windowed STFT magnitudes
   (n_fft=2048, hop=512): flux[t] = sum_k max(0, |X[t,k]| - |X[t-1,k]|).
   metric = mean_t |flux_ref[t] - flux_new[t]| / mean_t flux_ref[t].

   Calibration (test_2s_C4, world_vt strict F4; see docs/PROFILE.md):
       float32-level noise (1e-6)          flux 0.000 %   -> must pass
       formant_shift_beta 0.10 -> 0.12     flux 0.114 %   -> must fail
       added noise at -60 dBFS             flux 0.489 %   -> must fail
       gain -0.5 dB                        flux 5.6 %     -> must fail
       wrong voicing / wrong target note   flux 4.7-4.8 % -> must fail
   0.05 % sits well above round-off (different BLAS/FFT builds, CPU ISAs)
   and below the smallest deliberate parameter change we tried.  On the
   reference machine every case is bit-exact, so the fallback never fires.

Length must always match exactly; a length change is a behaviour change.
To accept an intentional DSP change, re-run tests/golden/render_golden.py and
commit the new references with the change.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pytest
import soundfile as sf

import matrix
from conftest import REGRESSION_RESULTS

MAX_ABS_DIFF = 1e-4
FLUX_REL_THRESHOLD = 0.0005
FLUX_N_FFT = 2048
FLUX_HOP = 512


def _load_manifest() -> dict | None:
    if not matrix.MANIFEST_PATH.exists():
        return None
    return json.loads(matrix.MANIFEST_PATH.read_text())


MANIFEST = _load_manifest()
CASES = MANIFEST["cases"] if MANIFEST else []


def spectral_flux(x: np.ndarray, n_fft: int = FLUX_N_FFT, hop: int = FLUX_HOP) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n_fft:
        x = np.pad(x, (0, n_fft - x.size))
    n_frames = 1 + (x.size - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1))
    return np.maximum(np.diff(mag, axis=0), 0.0).sum(axis=1)


def flux_rel_diff(ref: np.ndarray, new: np.ndarray) -> float:
    f_ref, f_new = spectral_flux(ref), spectral_flux(new)
    return float(np.mean(np.abs(f_ref - f_new)) / max(np.mean(f_ref), 1e-12))


def _read_reference(entry: dict) -> tuple[np.ndarray, int]:
    path = matrix.GOLDEN_DIR / entry["file"]
    head = path.read_bytes()[:64]
    if head.startswith(b"version https://git-lfs"):
        pytest.fail(f"{path} is a Git LFS pointer; run `git lfs pull` first")
    ref, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return ref, sr


def _param(entry: dict):
    marks = [pytest.mark.slow] if "10s" in entry["fixture"] else []
    return pytest.param(entry, id=entry["id"], marks=marks)


@pytest.mark.skipif(MANIFEST is None, reason="no golden manifest; run tests/golden/render_golden.py")
@pytest.mark.parametrize("entry", [_param(e) for e in CASES])
def test_golden(entry):
    ref, ref_sr = _read_reference(entry)
    case = matrix.case_from_manifest(entry)
    new, sr, _extra = matrix.render(case)
    new = new.astype(np.float32)

    result = {"id": entry["id"], "mode": entry["mode"], "voicing": entry["voicing"],
              "target": entry["target_note"], "max_abs_diff": float("inf"),
              "flux_rel_diff": None, "passed": False, "reason": ""}
    REGRESSION_RESULTS.append(result)

    label = f"[mode={entry['mode']} voicing={entry['voicing']} target={entry['target_note']}]"
    if sr != ref_sr or new.size != ref.size:
        result["reason"] = f"shape changed: sr {ref_sr}->{sr}, n {ref.size}->{new.size}"
        pytest.fail(f"{label} {result['reason']}")

    max_diff = float(np.max(np.abs(ref.astype(np.float64) - new))) if ref.size else 0.0
    result["max_abs_diff"] = max_diff
    if max_diff < MAX_ABS_DIFF:
        result["passed"] = True
        return

    flux = flux_rel_diff(ref, new)
    result["flux_rel_diff"] = flux
    if flux < FLUX_REL_THRESHOLD:
        result["passed"] = True
        return

    result["reason"] = (f"max|diff|={max_diff:.3e} (limit {MAX_ABS_DIFF:g}), "
                        f"flux diff={flux:.3%} (limit {FLUX_REL_THRESHOLD:.2%})")
    pytest.fail(f"{label} {result['reason']}")


@pytest.mark.skipif(MANIFEST is None, reason="no golden manifest")
def test_manifest_covers_matrix():
    """The committed manifest must contain exactly the current matrix.

    Also catches pitch-detector changes: target notes are derived from the
    detected source note, so a detection change alters the expected case ids.
    """
    expected = {c.id for c in matrix.build_cases()}
    actual = {c["id"] for c in CASES}
    assert not expected - actual, f"missing from manifest: {sorted(expected - actual)}"
    assert not actual - expected, f"stale in manifest: {sorted(actual - expected)}"


def test_no_librosa_imported():
    """librosa was removed from the backend; no render path may pull it back in."""
    assert "librosa" not in sys.modules
