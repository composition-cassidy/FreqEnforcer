"""Spectral-domain DSP helpers shared by the pitch modes (moved verbatim from
autotuner.py): envelope shift/warp, WORLD artifact repair, RMS envelope
matching, HF rolloff, zero-padded STFT, Lanczos-3 resampling, cepstral lifter.
"""

from __future__ import annotations

import numpy as np


def _warp_spectral_envelope_fdep(
    sp_frame: np.ndarray,
    pitch_ratio: float,
    sr: int,
    beta: float,
    crossover_freq: float = 3000.0,
) -> np.ndarray:
    """
    Frequency-dependent spectral envelope warp.

    Warping strength decreases linearly from *beta* at 0 Hz to 0 at
    *crossover_freq*, so low formants (F1/F2) shift with pitch while
    high formants (F3 and above) stay fixed -- matching vocal-tract physics.

    For output bin k at frequency f_k:
        local_beta_k = beta * max(0, 1 - f_k / crossover_freq)
        src_index    = k / (pitch_ratio ** local_beta_k)
    """
    sp_arr = np.asarray(sp_frame, dtype=np.float64)
    n = len(sp_arr)
    if n <= 1:
        return sp_arr

    ratio_f = float(pitch_ratio)
    if not np.isfinite(ratio_f) or ratio_f <= 0.0:
        return sp_arr

    beta_f = float(beta)
    if beta_f <= 1e-9:
        return sp_arr

    xover = max(1.0, float(crossover_freq))
    bin_hz = (sr / 2.0) / (n - 1)               # Hz per bin

    k = np.arange(n, dtype=np.float64)
    freq_k = k * bin_hz                          # physical frequency of each bin
    local_beta = beta_f * np.maximum(0.0, 1.0 - freq_k / xover)
    local_warp = np.power(ratio_f, local_beta)   # vectorised; shape (n,)

    src_idx = k / local_warp
    src_idx = np.clip(src_idx, 0.0, n - 1.0)

    floor_idx = np.floor(src_idx).astype(int)
    ceil_idx  = np.minimum(floor_idx + 1, n - 1)
    weights   = src_idx - floor_idx

    warped = sp_arr[floor_idx] * (1.0 - weights) + sp_arr[ceil_idx] * weights
    return warped


def _shift_spectral_envelope(sp_frame: np.ndarray, ratio: float) -> np.ndarray:
    """
    Shift a single frame's spectral envelope by ratio.
    Used when preserve_formants is False.
    """
    ratio_f = float(ratio)
    if not np.isfinite(ratio_f) or ratio_f <= 0.0:
        return np.asarray(sp_frame)

    sp_arr = np.asarray(sp_frame)
    length = len(sp_arr)
    indices = np.arange(length) / ratio_f
    indices = np.clip(indices, 0, length - 1)

    # Linear interpolation
    floor_indices = np.floor(indices).astype(int)
    ceil_indices = np.minimum(floor_indices + 1, length - 1)
    weights = indices - floor_indices

    shifted = sp_arr[floor_indices] * (1 - weights) + sp_arr[ceil_indices] * weights
    return shifted


def _repair_world_artifacts(
    audio: np.ndarray,
    sr: int,
    fft_size: int = 2048,
    hop: int = 512,
    freq_lo: float = 100.0,
    freq_hi: float = 3000.0,
    neighbor_radius: int = 3,
    roughness_threshold: float = 1.5,
    world_f0: "np.ndarray | None" = None,
    world_time_axis: "np.ndarray | None" = None,
) -> np.ndarray:
    """
    Post-process WORLD synthesis output to suppress spectral splotch artifacts.

    Strategy:
      1. STFT the output.
      2. Compute per-frame temporal spectral flux: RMS of how much each frame's
         dB magnitude in [freq_lo, freq_hi] deviates from its local neighborhood
         median (±neighbor_radius frames).  This discriminates splotch frames
         (which look different from their neighbours) from the normally high-
         variance harmonic structure (which is consistent across neighbours).
      3. Flag frames whose flux exceeds roughness_threshold * median_flux.
      4. Cluster filter: only repair if flux_ratio > 2x OR a neighbour is flagged.
      5. Voiced gate: if world_f0 is provided, skip repair on unvoiced STFT frames
         (AP=1 regions have naturally high spectral flux — not synthesis artifacts).
      6. Replace flagged voiced frames' magnitude with interpolation of nearest
         clean neighbours.  Phase is kept unchanged.
      7. ISTFT back.

    Applied conservatively: only the most obvious outliers are repaired.
    """
    from scipy.signal import stft, istft

    audio_in = np.asarray(audio, dtype=np.float64)
    if audio_in.size == 0:
        return audio_in

    # --- STFT ---
    f_ax, t_ax, Z = stft(audio_in, fs=sr,
                          nperseg=fft_size, noverlap=fft_size - hop,
                          window="hann", boundary="zeros", padded=True)
    # Z shape: (n_bins, n_frames)
    mag   = np.abs(Z)                              # (n_bins, n_frames)
    phase = np.angle(Z)                            # (n_bins, n_frames)
    n_frames = mag.shape[1]

    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-10))

    band = (f_ax >= freq_lo) & (f_ax <= freq_hi)
    if not band.any():
        return audio_in
    band_db = mag_db[band, :]                      # (n_band_bins, n_frames)

    # --- Temporal spectral flux: RMS deviation from local neighbourhood median ---
    radius = int(neighbor_radius)
    flux = np.zeros(n_frames, dtype=np.float64)
    for fi in range(n_frames):
        lo = max(0, fi - radius)
        hi = min(n_frames, fi + radius + 1)
        neighbours = [j for j in range(lo, hi) if j != fi]
        if not neighbours:
            flux[fi] = 0.0
            continue
        local_med_spectrum = np.median(band_db[:, neighbours], axis=1)  # (n_band_bins,)
        flux[fi] = float(np.sqrt(np.mean((band_db[:, fi] - local_med_spectrum) ** 2)))

    # --- Flag frames whose flux exceeds threshold * median_flux ---
    median_flux = float(np.median(flux))
    threshold = float(roughness_threshold)
    flagged = flux > threshold * max(median_flux, 1e-12)

    # --- Cluster filter: only repair if clearly anomalous OR part of a cluster ---
    # A flagged frame is repaired if:
    #   (a) flux_ratio > 2.0x median  (unambiguous outlier), OR
    #   (b) at least one immediate neighbour (±1) is also flagged
    # Isolated frames at 1.5–2.0x are likely false positives and are skipped.
    SOLO_PASS_RATIO = 2.0
    repair_mask = np.zeros(n_frames, dtype=bool)
    for fi in np.where(flagged)[0]:
        ratio_fi = flux[fi] / max(median_flux, 1e-12)
        has_neighbour = (
            (fi > 0          and flagged[fi - 1]) or
            (fi < n_frames-1 and flagged[fi + 1])
        )
        if ratio_fi > SOLO_PASS_RATIO or has_neighbour:
            repair_mask[fi] = True

    # --- Voiced gate: skip repair on unvoiced STFT frames ---
    # Diagnostic shows all detected "splotch" frames have AP max > 0.5; most are
    # fully unvoiced (f0=0).  High spectral flux in noise regions is natural texture,
    # not a synthesis artifact.  Only repair frames that WORLD considers voiced.
    if world_f0 is not None and world_time_axis is not None:
        wf0 = np.asarray(world_f0, dtype=np.float64)
        wt  = np.asarray(world_time_axis, dtype=np.float64)
        world_hop_s = float(wt[1] - wt[0]) if len(wt) > 1 else 0.005
        stft_t = np.arange(n_frames, dtype=np.float64) * (hop / float(sr))
        world_idx = np.clip(
            np.round(stft_t / max(world_hop_s, 1e-9)).astype(int),
            0, len(wf0) - 1,
        )
        voiced_stft = wf0[world_idx] > 0
        repair_mask &= voiced_stft

    n_to_repair = int(repair_mask.sum())
    if n_to_repair == 0:
        _, audio_out = istft(Z, fs=sr, nperseg=fft_size, noverlap=fft_size - hop,
                              window="hann", boundary="zeros")
        return audio_out[:len(audio_in)].astype(np.float64)

    # --- Repair: interpolate magnitude from nearest clean neighbors ---
    # "Clean" for interpolation purposes = not in repair_mask
    clean = ~repair_mask
    clean_idx = np.where(clean)[0]

    mag_repaired = mag.copy()
    for fi in np.where(repair_mask)[0]:
        before = clean_idx[clean_idx < fi]
        after  = clean_idx[clean_idx > fi]

        if before.size == 0 and after.size == 0:
            continue  # no clean neighbors at all — leave as-is
        elif before.size == 0:
            mag_repaired[:, fi] = mag[:, after[0]]
        elif after.size == 0:
            mag_repaired[:, fi] = mag[:, before[-1]]
        else:
            b, a = int(before[-1]), int(after[0])
            span = float(a - b)
            w_b  = (float(a) - float(fi)) / span   # weight of before frame
            w_a  = 1.0 - w_b
            mag_repaired[:, fi] = w_b * mag[:, b] + w_a * mag[:, a]

    # --- Reconstruct: repaired magnitude + original phase ---
    Z_repaired = mag_repaired * np.exp(1j * phase)
    _, audio_out = istft(Z_repaired, fs=sr, nperseg=fft_size, noverlap=fft_size - hop,
                          window="hann", boundary="zeros")
    audio_out = audio_out[:len(audio_in)].astype(np.float64)
    return audio_out


def _apply_rms_envelope(
    original: np.ndarray,
    synthesized: np.ndarray,
    frame_len: int = 1024,
    hop: int = 128,
    gain_min: float = 0.0,
    gain_max: float = 8.0,
    smooth_sigma: float = 3.0,
) -> np.ndarray:
    """Match the per-frame RMS envelope of *synthesized* to *original*.

    The sinusoidal model drops unvoiced content (fricatives, noise floor,
    weak harmonics below threshold), causing the output's dynamic shape to
    diverge from the input.  This post-processing step computes a smooth
    per-sample gain curve that brings the synthesized energy envelope back
    into alignment with the original.

    Algorithm:
      1. Compute windowed RMS of *original* and *synthesized* at *hop*-spaced
         frames using a Hann window of *frame_len* samples.
      2. Per-frame gain = orig_rms / (synth_rms + 1e-8), clipped to
         [gain_min, gain_max].
      3. Smooth the gain curve with a Gaussian (sigma = smooth_sigma frames).
      4. Reconstruct a per-sample gain via linear interpolation between frame
         centres and multiply into *synthesized*.

    Parameters
    ----------
    original : 1-D float64 array
        Original (pre-shift) audio.
    synthesized : 1-D float64 array
        Output of sine_model_synth (may differ slightly in length).
    frame_len : int
        RMS analysis frame length in samples.
    hop : int
        RMS analysis hop size in samples.
    gain_min, gain_max : float
        Gain clipping bounds (default 0–8×, i.e., 0 to +18 dB).
    smooth_sigma : float
        Gaussian smoothing sigma in frames.

    Returns
    -------
    corrected : 1-D float64 array, same length as *synthesized*.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal.windows import hann

    orig = np.asarray(original, dtype=np.float64)
    synth = np.asarray(synthesized, dtype=np.float64)

    # Work over the shorter of the two to avoid index errors
    n = min(len(orig), len(synth))
    if n < frame_len:
        # Audio too short to apply correction — return as-is
        return synth

    win = hann(frame_len, sym=True).astype(np.float64)
    win_rms = float(np.sqrt(np.mean(win ** 2)))  # normalise RMS by window energy

    # Pad both arrays so the last frame is complete
    n_frames = 1 + (n - frame_len) // hop
    orig_padded = np.pad(orig[:n], (0, frame_len), mode='constant')
    synth_padded = np.pad(synth[:n], (0, frame_len), mode='constant')

    orig_rms = np.zeros(n_frames, dtype=np.float64)
    synth_rms = np.zeros(n_frames, dtype=np.float64)
    centers = np.zeros(n_frames, dtype=np.float64)

    for i in range(n_frames):
        s = i * hop
        e = s + frame_len
        o_seg = orig_padded[s:e] * win
        sy_seg = synth_padded[s:e] * win
        orig_rms[i] = float(np.sqrt(np.mean(o_seg ** 2))) / (win_rms + 1e-12)
        synth_rms[i] = float(np.sqrt(np.mean(sy_seg ** 2))) / (win_rms + 1e-12)
        centers[i] = s + frame_len / 2.0

    gain = orig_rms / (synth_rms + 1e-8)
    gain = np.clip(gain, gain_min, gain_max)

    # Smooth the gain curve to avoid amplitude modulation artefacts
    gain_smooth = gaussian_filter1d(gain.astype(np.float64), sigma=smooth_sigma,
                                    mode='reflect')

    # Per-sample gain via linear interpolation between frame centres
    sample_indices = np.arange(len(synth), dtype=np.float64)
    per_sample_gain = np.interp(sample_indices, centers, gain_smooth,
                                left=gain_smooth[0], right=gain_smooth[-1])

    return synth * per_sample_gain


def _apply_micro_rms_envelope(
    original: np.ndarray,
    synthesized: np.ndarray,
    window_size: int = 128,
    hop: int = 64,
    gain_min: float = 0.0,
    gain_max: float = 4.0,
    smooth_sigma: float = 2.0,
) -> np.ndarray:
    """Transfer the original audio's micro-scale amplitude texture onto the synthesized output.

    The HNM synthesizer generates perfectly steady sinusoids shaped by
    CheapTrick's smoothed spectral envelope, which strips away the natural
    cycle-to-cycle energy fluctuations (shimmer, glottal breathiness, consonant
    micro-attacks) that make voice sound alive.  This function restores that
    texture by matching the RMS envelope at very fine resolution — one window
    per ~pitch period (~2.7 ms at 48 kHz) — so the synthesized output gains the
    original's dynamic "breathing" without affecting pitch or spectral shape.

    Algorithm mirrors _apply_rms_envelope() but at much shorter window/hop:
      1. Hann-windowed RMS of original and synthesized at hop-spaced frames.
      2. Per-frame gain = orig_rms / (synth_rms + eps), clipped to [gain_min, gain_max].
      3. Short Gaussian smooth (sigma=2 windows) to suppress window-boundary clicks.
      4. Per-sample linear interpolation then multiply into synthesized.

    Parameters
    ----------
    original : 1-D float64
        Original (pre-correction) audio.
    synthesized : 1-D float64
        HNM synthesizer output.
    window_size : int
        RMS window in samples (default 128 ≈ 2.7 ms at 48 kHz, ~1 pitch period
        at 370 Hz — keeps gain variation at sub-pitch-period resolution).
    hop : int
        Analysis hop in samples (default 64, 50% overlap).
    gain_min, gain_max : float
        Gain bounds (default 0–4× = 0 to +12 dB, conservative to avoid pumping).
    smooth_sigma : float
        Gaussian smoothing sigma in frames (default 2 ≈ 4 ms — just enough to
        eliminate window-boundary discontinuities without blurring the texture).

    Returns
    -------
    corrected : 1-D float64, same length as synthesized.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal.windows import hann

    orig = np.asarray(original, dtype=np.float64)
    synth = np.asarray(synthesized, dtype=np.float64)

    n = min(len(orig), len(synth))
    if n < window_size:
        return synth

    win = hann(window_size, sym=True).astype(np.float64)
    win_rms = float(np.sqrt(np.mean(win ** 2)))

    n_frames = 1 + (n - window_size) // hop
    orig_padded = np.pad(orig[:n], (0, window_size), mode='constant')
    synth_padded = np.pad(synth[:n], (0, window_size), mode='constant')

    orig_rms = np.zeros(n_frames, dtype=np.float64)
    synth_rms = np.zeros(n_frames, dtype=np.float64)
    centers = np.zeros(n_frames, dtype=np.float64)

    for i in range(n_frames):
        s = i * hop
        e = s + window_size
        orig_rms[i] = float(np.sqrt(np.mean((orig_padded[s:e] * win) ** 2))) / (win_rms + 1e-12)
        synth_rms[i] = float(np.sqrt(np.mean((synth_padded[s:e] * win) ** 2))) / (win_rms + 1e-12)
        centers[i] = s + window_size / 2.0

    gain = orig_rms / (synth_rms + 1e-8)
    gain = np.clip(gain, gain_min, gain_max)
    gain_smooth = gaussian_filter1d(gain, sigma=smooth_sigma, mode='reflect')

    sample_indices = np.arange(len(synth), dtype=np.float64)
    per_sample_gain = np.interp(sample_indices, centers, gain_smooth,
                                left=gain_smooth[0], right=gain_smooth[-1])

    return synth * per_sample_gain


def _apply_hf_rolloff(E: np.ndarray, sr: int, fft_size: int) -> np.ndarray:
    """
    Apply high-frequency rolloff to spectral envelope to match natural voice.

    Below 4kHz: flat (0 dB)
    4-8kHz: linear rolloff (-6 dB/octave)
    Above 8kHz: steep rolloff (-12 dB/octave)

    This prevents synthetic "sparkle" from harmonics extending to Nyquist.
    """
    n_bins = len(E)
    freqs = np.arange(n_bins, dtype=np.float64) * sr / fft_size
    rolloff = np.ones(n_bins, dtype=np.float64)

    # 4-8 kHz: -6 dB/octave rolloff
    mask_4_8 = (freqs >= 4000.0) & (freqs < 8000.0)
    if np.any(mask_4_8):
        octaves_from_4k = np.log2(freqs[mask_4_8] / 4000.0)
        rolloff[mask_4_8] = 10.0 ** (-6.0 * octaves_from_4k / 20.0)

    # Above 8 kHz: -12 dB/octave rolloff
    mask_above_8 = freqs >= 8000.0
    if np.any(mask_above_8):
        octaves_from_8k = np.log2(freqs[mask_above_8] / 8000.0)
        rolloff[mask_above_8] = 10.0 ** (-12.0 * octaves_from_8k / 20.0)

    return E * rolloff


def _zp_stft(audio: np.ndarray, window_size: int, fft_size: int,
             hop_size: int) -> np.ndarray:
    """Zero-padded STFT.  Uses a *window_size*-sample Hann window but
    computes an *fft_size*-point FFT (zero-padded), giving 4x frequency
    oversampling when fft_size == 4 * window_size."""
    from numpy.lib.stride_tricks import sliding_window_view
    window = 0.5 - 0.5 * np.cos(
        2.0 * np.pi * np.arange(window_size) / window_size)
    chunks = sliding_window_view(audio, window_size)[::hop_size]  # (F, W)
    windowed = chunks * window[np.newaxis, :]
    return np.fft.rfft(windowed, n=fft_size, axis=-1, norm='forward')


def _zp_istft(frames: np.ndarray, window_size: int, fft_size: int,
              hop_size: int) -> np.ndarray:
    """Inverse of :func:`_zp_stft`.  IRFFT to *fft_size* samples, keep only
    the first *window_size*, apply synthesis window, overlap-add."""
    n_frames = len(frames)
    # Zero DC and Nyquist (same as library)
    frames = frames.copy()
    frames[:, 0] = 0
    frames[:, -1] = 0

    time_frames = np.fft.irfft(frames, n=fft_size, axis=-1, norm='forward')
    time_frames = time_frames[:, :window_size]          # discard zero-pad tail

    window = 0.5 - 0.5 * np.cos(
        2.0 * np.pi * np.arange(window_size) / window_size)
    W = window * hop_size / np.sum(window * window)
    time_frames *= W[np.newaxis, :]

    out_len = n_frames * hop_size + window_size
    output = np.zeros(out_len, dtype=np.float64)
    for i in range(n_frames):
        s = i * hop_size
        output[s:s + window_size] += time_frames[i]
    return output


def _lanczos3_resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Lanczos-3 (6-tap windowed sinc) spectral resampling.

    Given an input spectrum *x* of length *n*, produces an output of the same
    length where the first ``min(n, int(n*factor))`` bins are filled via
    Lanczos-3 interpolation and the rest are zero.
    """
    if factor == 1.0:
        return x.copy()

    n = len(x)
    m = int(n * factor)
    valid = min(n, m)
    q = n / m                               # step through input per output bin

    y = np.zeros(n, dtype=x.dtype)
    positions = np.arange(valid, dtype=np.float64) * q   # (valid,)

    base = np.floor(positions).astype(np.intp)           # (valid,)
    offsets = np.arange(-2, 4)                           # 6 taps

    # tap_indices (valid, 6) — clamped to [0, n-1]
    tap_idx = base[:, None] + offsets[None, :]
    tap_idx = np.clip(tap_idx, 0, n - 1)

    # distances from each tap to the ideal position
    d = positions[:, None] - (base[:, None] + offsets[None, :].astype(np.float64))

    # Lanczos-3 kernel
    weights = np.zeros_like(d)
    near_zero = np.abs(d) < 1e-7
    in_range = (~near_zero) & (np.abs(d) < 3.0)

    weights[near_zero] = 1.0
    pi_d = np.pi * d[in_range]
    pi_d3 = np.pi * d[in_range] / 3.0
    weights[in_range] = (
        3.0 * np.sin(pi_d) * np.sin(pi_d3) / (np.pi * np.pi * d[in_range] ** 2)
    )

    values = x[tap_idx]                    # (valid, 6)
    y[:valid] = np.sum(values * weights, axis=1)
    return y


def _improved_lifter(mag: np.ndarray, f0_per_frame: np.ndarray | None,
                     sr: int) -> np.ndarray:
    """Cepstral envelope estimation with three improvements over the library:

    a) Magnitude floor before log (prevents cepstral corruption from tiny bins).
    b) Hamming-windowed lifter instead of hard rectangular cutoff (removes Gibbs
       ringing in the envelope).
    c) Adaptive cepstral order: ``quefrency = round(sr / (2.5 * f0))`` so the
       lifter tracks the harmonic spacing; fall back to ``round(0.001 * sr)``
       when f0 is unknown.

    Args:
        mag:            (n_frames, n_bins) magnitude array (linear, positive).
        f0_per_frame:   (n_frames,) detected F0 in Hz; NaN/0 for unvoiced.
        sr:             Sample rate.

    Returns:
        envelopes:      (n_frames, n_bins) smooth spectral envelopes (linear).
    """
    n_frames, n_bins = mag.shape
    envelopes = np.zeros_like(mag)
    default_q = int(round(0.001 * sr))     # 1 ms fallback

    for i in range(n_frames):
        frame_mag = mag[i]

        # (a) floor before log — at least -80 dB below peak
        peak = np.max(np.abs(frame_mag))
        floor_val = max(peak * 1e-4, 1e-30)
        log_mag = np.log(np.maximum(np.abs(frame_mag), floor_val))

        # (c) adaptive quefrency
        f0_i = 0.0 if f0_per_frame is None else float(f0_per_frame[i])
        if np.isfinite(f0_i) and f0_i > 50.0:
            q = int(round(sr / (2.5 * f0_i)))
        else:
            q = default_q
        q = max(4, min(q, n_bins // 2))

        # cepstrum
        cepstrum = np.fft.irfft(log_mag, norm='forward')

        # (b) Hamming-windowed lifter (instead of rectangular)
        hamming = np.hamming(2 * q + 1)
        lifter_win = np.zeros(len(cepstrum))
        apply_len = min(q + 1, len(cepstrum))
        # right half of Hamming (indices q..2q mapped to cepstrum 0..q)
        lifter_win[:apply_len] = hamming[q:q + apply_len]
        envelopes[i] = np.exp(np.real(np.fft.rfft(
            cepstrum * lifter_win, norm='forward')))

    return envelopes
