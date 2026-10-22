"""Single source of truth for the post-pitch combination sweep.

Every pass/fail threshold and every swept value lives here.  Named
``sweep_config`` (not ``config``) because ``server/`` is on sys.path for the
bare ``audio.*`` imports and would shadow a module called ``config``.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SWEEP_DIR = Path(__file__).resolve().parent

# Runtime import roots (repo root for server.*, server/ for the bare audio.*
# imports in sine_spectral/stft), placed after this directory so local module
# names win.  Spawned pool workers inherit sys.path.
for _p in (str(ROOT / "server"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(1, _p)
warnings.filterwarnings("ignore", message=r"pkg_resources is deprecated")
OUT_DIR = SWEEP_DIR / "out"
REPORT_PATH = ROOT / "docs" / "SWEEP_REPORT.md"
REAL_FIXTURE_DIR = ROOT / "tests" / "fixtures"

SR = 44100
RNG_SEED = 0          # np.random.seed before every render (hnm_synth draws unseeded noise)
WORKERS = max(1, (os.cpu_count() or 2) - 2)

# ---------------------------------------------------------------------------
# Pass / fail thresholds
# ---------------------------------------------------------------------------
F0_ERR_CENTS = 15.0          # |median output f0 - target| in cents
INHARM_WORSE_DB = 6.0        # output inharmonic ratio minus input inharmonic ratio
TAIL_DB = -40.0              # energy after source offset, dB re note body
TAIL_MS = 200.0              # length of the tail window
RMS_LOSS_DB = 6.0            # body RMS drop vs input ...
RMS_LOSS_MAX_CLEAN = 50.0    # ... only checked when cleanliness <= this
LENGTH_TOL_MS = 10.0         # |len(out) - round(len(in) * stretch)|; WORLD rounds to 5 ms frames
PEAK_DBFS = 0.0              # peak above this is a failure (clipping on export)

# Metric names as they appear in results (order = report column order)
METRICS = ["exception", "nonfinite", "length", "peak", "f0", "inharm", "tail", "rms"]

# ---------------------------------------------------------------------------
# Swept parameters (keys are ProcessRequest field names)
# ---------------------------------------------------------------------------
PITCH_MODES = ["world_hard", "world_soft", "world_vt", "world_hnm",
               "praat_soft", "sine_spectral", "stft_pitchshift"]
SHIFTS = [-12, -7, 0, 5, 12]
STRETCHES = [1.0, 1.5]
LOWCUTS = [0.0, 50.0, 100.0]
CLEANS = [0.0, 25.0, 50.0, 75.0, 100.0]
HF_ROLLBACKS = [0.0, 50.0]
BREATHS = [0.0, 0.5, 1.0, 2.0, 5.0]
HF_BIASES = [0.0, 1.0]

# Pairwise factor order: (short name, ProcessRequest key, values)
PAIRWISE_FACTORS = [
    ("mode", "pitch_mode", PITCH_MODES),
    ("shift", "_shift", SHIFTS),
    ("stretch", "stretch_factor", STRETCHES),
    ("lowcut", "clean_lowcut_percent", LOWCUTS),
    ("clean", "cleanliness_percent", CLEANS),
    ("hfrb", "clean_hf_rollback_percent", HF_ROLLBACKS),
    ("breath", "breathiness", BREATHS),
    ("hfbias", "hf_bias", HF_BIASES),
]
PAIRWISE_SEED = 1
PAIRWISE_CANDIDATES = 60

# Post-pitch settings that make a render "pitch-only"
NEUTRAL_POST = {"clean_lowcut_percent": 0.0, "cleanliness_percent": 0.0,
                "clean_hf_rollback_percent": 0.0, "breathiness": 1.0, "hf_bias": 0.0}

# ---------------------------------------------------------------------------
# Metric analysis parameters
# ---------------------------------------------------------------------------
BODY_GUARD_S = 0.05          # trim this much from both ends of the note body
F0_MAX_FRAMES = 40           # YIN frames per measurement (spread over the body)
HARM_BAND_REL = 2 ** (50.0 / 1200.0) - 1.0   # +-50 cents around each harmonic ...
HARM_BAND_MIN_BINS = 2.5     # ... but at least this many FFT bins ...
HARM_BAND_MAX_F0 = 0.3       # ... and at most this fraction of f0
INHARM_FMAX = 16000.0
INHARM_MAX_HARMONICS = 40
STFT_BIN_HZ = SR / 2048.0    # cleanliness STFT bin width (n_fft 2048)

# Cleanliness mask FWHM as implemented (cleanliness.py: 200 Hz -> 10 Hz)
def clean_fwhm_hz(clean_pct: float) -> float:
    return 200.0 - (float(clean_pct) / 100.0) * (200.0 - 10.0)


# Number of worst renders saved as WAV, and the per-mode cap for variety
N_WORST_WAVS = 10
WORST_PER_MODE_CAP = 3
N_WORST_TABLE = 20
