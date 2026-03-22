"""
HNM (Harmonic + Noise Model) synthesizer for WORLD vocoder parameters.

Replaces pw.synthesize() with explicit sinusoidal + shaped-noise synthesis.
Reads WORLD's f0/sp/ap arrays directly.

Design:
  - Harmonics: direct time-domain cosine summation (no IRFFT artifacts).
  - Noise: FFT-filtered white noise with spectral shape from sp*ap.
  - Overlap-add with Hanning window at the WORLD hop size.
  - Post-synthesis RMS normalization matches the output level to the
    expected energy from the spectral envelope (empirically calibrated).
"""
from __future__ import annotations

import numpy as np

# CheapTrick sp -> sinusoidal amplitude calibration.
_SP_GAIN = 0.145

# Target RMS constant: pw_rms ≈ _RMS_K * sqrt(mean(sum(sp, axis=1)))
# Empirically stable at ~0.034 across multiple vocal samples.
_RMS_K = 0.034


def hnm_synthesize(
    f0: np.ndarray,
    sp: np.ndarray,
    ap: np.ndarray,
    fs: int,
    frame_period: float = 5.0,
    harmonic_amps_override: np.ndarray | None = None,
    harmonic_scale: np.ndarray | None = None,
) -> np.ndarray:
    """
    Synthesize audio from WORLD vocoder parameters using Harmonic + Noise Model.

    Parameters
    ----------
    f0 : (T,) float64 — fundamental frequency per frame. 0 = unvoiced.
    sp : (T, fft_size//2+1) float64 — CheapTrick linear power spectral envelope.
    ap : (T, fft_size//2+1) float64 — aperiodicity ratio 0..1.
    fs : int — sample rate.
    frame_period : float — frame period in milliseconds (default 5.0).
    harmonic_amps_override : (T, max_harmonics) float64 or None
        If provided, replaces the CheapTrick-derived per-harmonic magnitude
        (mag_interp) for each frame entirely.  Periodic weighting from *ap*
        is still applied on top.  Use for Approach A (direct STFT harmonics).
    harmonic_scale : (T, max_harmonics) float64 or None
        If provided, multiplies harm_amps (= mag_interp * periodic_w) after
        normal computation.  Use for Approach B (fine-structure correction).

    Returns
    -------
    (N,) float64 — synthesized audio.
    """
    f0 = np.asarray(f0, dtype=np.float64)
    sp = np.asarray(sp, dtype=np.float64)
    ap = np.asarray(ap, dtype=np.float64)

    n_frames = len(f0)
    n_bins = sp.shape[1]
    fft_size = (n_bins - 1) * 2

    hop_samples = int(fs * frame_period / 1000.0)
    output_len = (n_frames - 1) * hop_samples + fft_size
    output = np.zeros(output_len, dtype=np.float64)
    win_sum = np.zeros(output_len, dtype=np.float64)

    window = np.hanning(fft_size).astype(np.float64)

    max_harmonics = min(int(fs / 2.0 / 50.0) + 1, 500)
    phase_accum = np.random.uniform(0, 2.0 * np.pi, size=max_harmonics)

    mag_env = np.sqrt(np.maximum(sp, 0.0)) * _SP_GAIN

    # Noise scale: compensate for IRFFT's 1/N normalization.
    _noise_irfft_scale = fft_size / 2.0

    t_local = np.arange(fft_size, dtype=np.float64) / fs

    for i in range(n_frames):
        offset = i * hop_samples
        frame_f0 = f0[i]
        frame_mag = mag_env[i]
        frame_ap = ap[i]
        is_voiced = frame_f0 > 0

        # ------ HARMONIC COMPONENT (direct time-domain) ------
        harmonic = np.zeros(fft_size, dtype=np.float64)

        if is_voiced:
            n_harm = min(int(fs / (2.0 * frame_f0)), max_harmonics)
            k_arr = np.arange(1, n_harm + 1, dtype=np.float64)
            freq_arr = k_arr * frame_f0
            bin_arr = freq_arr * fft_size / fs

            bin_lo = np.floor(bin_arr).astype(np.intp)
            valid = bin_lo < (n_bins - 1)
            if np.any(valid):
                k_arr = k_arr[valid]
                freq_arr = freq_arr[valid]
                bin_arr = bin_arr[valid]
                bin_lo = bin_lo[valid]
                frac = bin_arr - bin_lo
                bin_hi = bin_lo + 1

                k_idx = (k_arr - 1).astype(np.intp)

                ap_interp = (1.0 - frac) * frame_ap[bin_lo] + frac * frame_ap[bin_hi]
                periodic_w = np.sqrt(np.maximum(0.0, 1.0 - ap_interp * ap_interp))

                if harmonic_amps_override is not None:
                    # Approach A: replace envelope-derived magnitudes entirely
                    mag_interp = harmonic_amps_override[i, k_idx]
                else:
                    mag_interp = (1.0 - frac) * frame_mag[bin_lo] + frac * frame_mag[bin_hi]

                harm_amps = mag_interp * periodic_w

                if harmonic_scale is not None:
                    # Approach B: modulate harm_amps by per-harmonic correction
                    harm_amps = harm_amps * harmonic_scale[i, k_idx]

                phases = phase_accum[k_idx]

                theta = np.outer(freq_arr, t_local) * (2.0 * np.pi)
                theta += phases[:, np.newaxis]
                harmonic = np.dot(harm_amps, np.cos(theta))

                phase_accum[k_idx] += 2.0 * np.pi * freq_arr * hop_samples / fs
                phase_accum[k_idx] %= (2.0 * np.pi)

        # ------ NOISE COMPONENT ------
        noise = np.random.randn(fft_size)
        noise_fft = np.fft.rfft(noise)

        if is_voiced:
            noise_target = frame_mag * frame_ap
        else:
            noise_target = frame_mag

        noise_abs = np.abs(noise_fft)
        noise_abs = np.maximum(noise_abs, 1e-16)
        noise_fft = noise_fft / noise_abs * (noise_target * _noise_irfft_scale)
        noise_out = np.fft.irfft(noise_fft, n=fft_size)

        # ------ COMBINE, WINDOW, OLA ------
        combined = (harmonic + noise_out) * window
        end = offset + fft_size
        output[offset:end] += combined
        win_sum[offset:end] += window

    # ------ OLA NORMALIZATION ------
    ws_max = win_sum.max()
    if ws_max > 0:
        threshold = 0.1 * ws_max
        safe = win_sum >= threshold
        output[safe] /= win_sum[safe]
        output[~safe] = 0.0

        fade_len = min(hop_samples, len(output) // 4)
        if fade_len > 1:
            output[:fade_len] *= np.linspace(0, 1, fade_len)
            output[-fade_len:] *= np.linspace(1, 0, fade_len)

    # Trim
    expected_len = (n_frames - 1) * hop_samples + 1
    if len(output) > expected_len:
        output = output[:expected_len]

    # ------ RMS NORMALIZATION ------
    # Match output level to the energy implied by sp.
    # Empirically: pw_rms ≈ _RMS_K * sqrt(mean(sum(sp, axis=1)))
    mean_sp_sum = np.mean(np.sum(sp, axis=1))
    target_rms = _RMS_K * np.sqrt(max(mean_sp_sum, 1e-10))
    actual_rms = np.sqrt(np.mean(output ** 2))
    if actual_rms > 1e-10:
        output *= target_rms / actual_rms

    return output
