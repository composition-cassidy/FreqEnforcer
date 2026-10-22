"""Counterfactual replica of _run_pipeline steps 0-6 (server/routes/audio.py).

It calls the same server functions in the same order with the same
arguments; a toggle only changes an *argument*, never server code:

    F1  cleanliness gets the cached WORLD f0 rescaled to the target note
        (cached_f0 * target / median voiced cached_f0) - same voicing flags
        and time mapping as the app, only the frequency is corrected.
    F3  smart low cut is computed from the target f0 instead of
        state.detected_pitch (the original audio's f0).
    F4  breathiness gets a world_cache analysed on the signal it receives
        with the correct f0 (target over the note, 0 elsewhere) instead of
        running harvest with its default 71-800 Hz range.
    F5  cleanliness gets its input pre-padded with n_fft zeros (cached f0
        padded with matching unvoiced frames) and the padding is cut off
        afterwards.  apply_cleanliness pads only the END; at the start the
        ISTFT divides by a near-zero window sum (scipy's NOLA warning), so
        this isolates that edge blow-up (root cause "E1", not one of B1-B5).
    F6  when there is no WORLD cache (non-WORLD mode, breathiness 1)
        cleanliness runs its own pyin (50-500 Hz) on the processed audio;
        F6 hands it the correct f0 instead (target over the note, 0
        elsewhere) - root cause "E2", e.g. targets outside 50-500 Hz.

Diagnostics switch one stage off: no_clean, no_breath, no_lowcut.

With no toggles the replica must be bit-identical to _run_pipeline; the
worker checks that per group (fidelity).
"""

from __future__ import annotations

import numpy as np

import sweep_config as cfg

FIXES = ("F1", "F3", "F4", "F5", "F6")
FIX_LABEL = {"F1": "B1", "F3": "B3", "F4": "B4", "F5": "E1", "F6": "E2"}
CLEAN_N_FFT = 2048          # cleanliness.py STFT size
WORLD_FRAME_S = 0.005


def pitch_stage(audio: np.ndarray, sr: int, settings: dict) -> tuple[np.ndarray, dict | None]:
    """Steps 0-2. Returns (pitch-corrected + stretched audio, full WORLD analysis
    of the input or None when neither the mode nor any breathiness needs it)."""
    from server.audio.modes import render_pitch_mode, MODES
    from server.audio.time_stretch import STRETCHERS
    from server.routes.audio import _world_cache_for
    from server.state import state

    # Analyse whenever the mode or *some* combo needs it; _world_cache_for is
    # deterministic, so the analysis equals what the app computes for any
    # combo that has one.  Callers pass it on only when the app would.
    probe = dict(settings, breathiness=0.5)
    state.world_cache = {"audio_hash": None}
    world_cache = _world_cache_for(audio, sr, probe, {})
    state.world_cache = {"audio_hash": None}

    mode = str(settings.get("pitch_mode", "world_hard"))
    uses_cache = mode in MODES and MODES[mode].USES_WORLD_CACHE
    np.random.seed(cfg.RNG_SEED)
    result = render_pitch_mode(mode, audio.copy(), sr, settings,
                               world_cache=world_cache if uses_cache else None)
    stretch = float(settings.get("stretch_factor", 1.0))
    if abs(stretch - 1.0) > 1e-6:
        result = STRETCHERS[str(settings.get("stretch_method", "audiotsm_wsola"))](result, int(sr), stretch)
    return result, world_cache


def app_has_cache(settings: dict) -> bool:
    """Whether _run_pipeline builds a WORLD cache for these settings."""
    from server.audio.modes import MODES
    mode = str(settings.get("pitch_mode", "world_hard"))
    return (mode in MODES and MODES[mode].USES_WORLD_CACHE) or float(settings.get("breathiness", 1.0)) != 1.0


def oracle_world_cache(x: np.ndarray, sr: int, note_span: tuple[int, int], target_f0: float) -> dict:
    import pyworld as pw
    x64 = np.ascontiguousarray(x, dtype=np.float64)
    period = 5.0
    n_frames = int(1000.0 * len(x64) / sr / period) + 1
    t = np.arange(n_frames, dtype=np.float64) * period / 1000.0
    a, b = note_span
    f0 = np.where((t * sr >= a) & (t * sr < b), float(target_f0), 0.0)
    sp = pw.cheaptrick(x64, f0, t, sr)
    ap = pw.d4c(x64, f0, t, sr)
    return {"f0": f0, "timeaxis": t, "sp": sp, "ap": ap, "sr": sr}


def post_stage(pitched: np.ndarray, sr: int, settings: dict, world_cache: dict | None,
               detected_pitch: dict | None, target_f0: float, note_span: tuple[int, int],
               fixes: frozenset = frozenset(), diags: frozenset = frozenset()) -> np.ndarray:
    """Steps 3-6 of _run_pipeline with optional toggles / disabled stages."""
    from server.audio.autotuner import apply_breathiness
    from server.audio.cleanliness import apply_cleanliness, apply_low_cut, compute_smart_lowcut

    result = pitched
    cache = world_cache if app_has_cache(settings) else None

    # 3. Smart low cut
    f0_hz = float((detected_pitch or {}).get("freq_hz", 0.0))
    if not np.isfinite(f0_hz) or f0_hz <= 0.0:
        f0_hz = 50.0
    if "F3" in fixes:
        f0_hz = float(target_f0)
    lowcut_pct = float(settings.get("clean_lowcut_percent", 0.0))
    if "no_lowcut" not in diags and np.isfinite(lowcut_pct) and lowcut_pct > 0.0:
        lowcut_hz = compute_smart_lowcut(f0_hz, lowcut_pct)
        if lowcut_hz > 0.0:
            result = apply_low_cut(result, int(sr), float(lowcut_hz))

    # 4. Cleanliness + HF rollback
    clean = float(settings.get("cleanliness_percent", 0.0))
    hfrb = float(settings.get("clean_hf_rollback_percent", 0.0))
    if "no_clean" not in diags and np.isfinite(clean) and clean > 0.0:
        cached_f0 = cache["f0"] if cache and cache.get("f0") is not None else None
        if "F1" in fixes and cached_f0 is not None:
            cached_f0 = rescaled_f0(cached_f0, target_f0)
        if "F6" in fixes and cached_f0 is None:
            n_frames = int(1000.0 * len(result) / sr / (1000.0 * WORLD_FRAME_S)) + 1
            t = np.arange(n_frames) * WORLD_FRAME_S * sr
            a, b = note_span
            cached_f0 = np.where((t >= a) & (t < b), float(target_f0), 0.0)
        pad = 0
        x_in = result
        if "F5" in fixes:
            pad = CLEAN_N_FFT
            x_in = np.concatenate([np.zeros(pad, dtype=np.asarray(result).dtype), result])
            if cached_f0 is not None:
                k = int(round(pad / sr / WORLD_FRAME_S))
                cached_f0 = np.concatenate([np.zeros(k), cached_f0])
        cached_voiced = (cached_f0 > 0) if cached_f0 is not None else None
        result = apply_cleanliness(
            x_in, int(sr), float(clean),
            hf_rollback_percent=float(hfrb) if np.isfinite(hfrb) else 0.0,
            cached_f0=cached_f0, cached_voiced=cached_voiced)
        if pad:
            result = result[pad:]

    # 6. Breathiness
    breath = float(settings.get("breathiness", 1.0))
    hf_bias = float(settings.get("hf_bias", 0.0))
    if ("no_breath" not in diags and np.isfinite(breath) and np.isfinite(hf_bias)
            and breath != 1.0):
        wc = oracle_world_cache(result, sr, note_span, target_f0) if "F4" in fixes else None
        result = apply_breathiness(result, int(sr), amount=breath, hf_bias=hf_bias, world_cache=wc)
    return result


def rescaled_f0(cached_f0: np.ndarray, target_f0: float) -> np.ndarray:
    voiced = cached_f0[cached_f0 > 0]
    if voiced.size == 0:
        return cached_f0
    return cached_f0 * (float(target_f0) / float(np.median(voiced)))


def relevant_fixes(settings: dict) -> list[str]:
    out = []
    if float(settings.get("cleanliness_percent", 0.0)) > 0.0 and app_has_cache(settings):
        out.append("F1")
    if float(settings.get("clean_lowcut_percent", 0.0)) > 0.0:
        out.append("F3")
    if float(settings.get("breathiness", 1.0)) != 1.0:
        out.append("F4")
    if float(settings.get("cleanliness_percent", 0.0)) > 0.0:
        out.append("F5")
        if not app_has_cache(settings):
            out.append("F6")
    return out


def active_stages(settings: dict) -> list[str]:
    out = []
    if float(settings.get("cleanliness_percent", 0.0)) > 0.0:
        out.append("no_clean")
    if float(settings.get("breathiness", 1.0)) != 1.0:
        out.append("no_breath")
    if float(settings.get("clean_lowcut_percent", 0.0)) > 0.0:
        out.append("no_lowcut")
    return out


def diag_label(diag: str, settings: dict) -> str:
    if diag == "no_clean":
        clean = float(settings["cleanliness_percent"])
        return "B2" if cfg.clean_fwhm_hz(clean) < cfg.STFT_BIN_HZ else f"clean_mask_{int(clean)}"
    if diag == "no_breath":
        return "breath_intended" if float(settings["breathiness"]) > 1.0 else "breath_resynth"
    return "lowcut_design"
