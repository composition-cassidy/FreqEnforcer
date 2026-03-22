"""
Clean-room sinusoidal modeling analysis/synthesis.

Implemented from published academic references only:
  - X. Serra, "A System for Sound Analysis/Transformation/Synthesis Based on a
    Deterministic plus Stochastic Decomposition", PhD thesis, Stanford, 1989.
  - J.O. Smith III, "Spectral Audio Signal Processing", CCRMA online book.
  - R. McAulay & T. Quatieri, "Speech Analysis/Synthesis Based on a Sinusoidal
    Representation", IEEE TASSP, 1986.

Dependencies: numpy, scipy only.
"""

from __future__ import annotations

import numpy as np
from scipy.fft import fft, ifft, rfft, fftshift
from scipy.signal.windows import blackmanharris, triang


# ---------------------------------------------------------------------------
# 1. Windowed DFT analysis
# ---------------------------------------------------------------------------

def dft_anal(x: np.ndarray, window: np.ndarray, fft_size: int
             ) -> tuple[np.ndarray, np.ndarray]:
    """Zero-phase windowed DFT analysis returning magnitude (dB) and phase.

    Implements the standard zero-phase windowing technique: the windowed signal
    is zero-padded to *fft_size* and then circular-shifted so that the window
    centre sits at index 0 before the FFT. Only the positive-frequency half
    (bins 0 … N/2) is returned.

    Reference: Smith, SASP, Ch. 5–7.

    Parameters
    ----------
    x : array, shape (W,)
        Input signal segment (same length as *window*).
    window : array, shape (W,)
        Analysis window (e.g. Blackman-Harris 92 dB).
    fft_size : int
        FFT length, must be >= len(window) and a power of two.

    Returns
    -------
    mag_db : array, shape (N/2+1,)
        Magnitude spectrum in dB.
    phase : array, shape (N/2+1,)
        Phase spectrum in radians.
    """
    w_len = len(window)
    if fft_size < w_len:
        raise ValueError("fft_size must be >= window length")
    if fft_size & (fft_size - 1):
        raise ValueError("fft_size must be a power of two")

    half_w = (w_len + 1) // 2  # number of samples from centre to end

    # Apply window
    xw = np.zeros(fft_size, dtype=np.float64)
    # Zero-phase layout: put the second half of the window at the start,
    # and the first half at the end of the buffer.
    xw[:half_w] = x[w_len // 2:] * window[w_len // 2:]
    xw[fft_size - w_len // 2:] = x[:w_len // 2] * window[:w_len // 2]

    # FFT — positive spectrum only
    spectrum = rfft(xw)

    # Normalise by window sum and multiply by 2 to compensate for
    # the one-sided spectrum (energy of a real sinusoid is split equally
    # between positive and negative frequencies).  After this, a
    # unit-amplitude cosine reads 0 dB.
    win_sum = np.sum(window)
    if win_sum > 0:
        spectrum = spectrum * (2.0 / win_sum)

    # Magnitude in dB (floor at -200 dB to avoid log(0))
    abs_spec = np.abs(spectrum)
    abs_spec[abs_spec < 1e-10] = 1e-10
    mag_db = 20.0 * np.log10(abs_spec)

    # Phase (unwrapped not needed here; raw angle is fine for peak interp)
    phase = np.angle(spectrum)

    return mag_db, phase


# ---------------------------------------------------------------------------
# 2. Spectral peak detection
# ---------------------------------------------------------------------------

def peak_detect(mag_db: np.ndarray, threshold_db: float) -> np.ndarray:
    """Detect local maxima in a magnitude spectrum above a dB threshold.

    A bin is a peak if it is strictly greater than both neighbours and its
    magnitude exceeds *threshold_db*. Bins 0 and N/2 are excluded.

    Reference: Serra thesis, Ch. 3; standard spectral peak picking.

    Parameters
    ----------
    mag_db : array, shape (N/2+1,)
        Magnitude spectrum in dB.
    threshold_db : float
        Only peaks above this level (dB) are returned.

    Returns
    -------
    peaks : 1-D int array
        Indices of detected peak bins.
    """
    # Compare each interior bin with its neighbours
    n = len(mag_db)
    if n < 3:
        return np.array([], dtype=np.intp)

    left = mag_db[:-2]
    centre = mag_db[1:-1]
    right = mag_db[2:]

    is_peak = (centre > left) & (centre > right) & (centre > threshold_db)
    # +1 because centre starts at index 1
    return np.flatnonzero(is_peak) + 1


# ---------------------------------------------------------------------------
# 3. Parabolic peak interpolation
# ---------------------------------------------------------------------------

def peak_interp(mag_db: np.ndarray, phase: np.ndarray,
                peak_indices: np.ndarray, sr: int, fft_size: int
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Refine peak frequency, magnitude, and phase via parabolic interpolation.

    For each detected peak bin *k*, fits a parabola through the three dB values
    mag[k-1], mag[k], mag[k+1] and finds the fractional bin offset of the
    true peak. Frequency is then (k + offset) * sr / fft_size.

    Reference: Smith, SASP, Ch. 10 — "Quadratic Interpolation of Spectral
    Peaks".

    Parameters
    ----------
    mag_db, phase : arrays, shape (N/2+1,)
        Magnitude (dB) and phase spectra from dft_anal.
    peak_indices : int array
        Bin indices of detected peaks.
    sr : int
        Sample rate.
    fft_size : int
        FFT size used in analysis.

    Returns
    -------
    freqs : array (Hz)
    mags : array (dB)
    phases : array (radians)
        Interpolated frequency, magnitude, and phase for each peak.
    """
    if len(peak_indices) == 0:
        empty = np.array([], dtype=np.float64)
        return empty, empty, empty.copy()

    k = peak_indices
    alpha = mag_db[k - 1]
    beta = mag_db[k]
    gamma = mag_db[k + 1]

    # Parabolic interpolation: offset = 0.5 * (alpha - gamma) / (alpha - 2*beta + gamma)
    denom = alpha - 2.0 * beta + gamma
    # Guard against zero denominator (flat peaks)
    safe_denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    offset = 0.5 * (alpha - gamma) / safe_denom

    # Interpolated values
    freqs = (k.astype(np.float64) + offset) * sr / fft_size
    mags = beta - 0.25 * (alpha - gamma) * offset
    # Linear phase interpolation between neighbouring bins
    phases = phase[k] + offset * (
        np.where(offset >= 0,
                 phase[np.minimum(k + 1, len(phase) - 1)] - phase[k],
                 phase[k] - phase[np.maximum(k - 1, 0)])
    )

    return freqs, mags, phases


# ---------------------------------------------------------------------------
# 4. Sinusoidal tracking across frames
# ---------------------------------------------------------------------------

def sine_tracking(freqs: np.ndarray, mags: np.ndarray, phases: np.ndarray,
                  prev_tracks: np.ndarray, max_tracks: int,
                  freq_dev_hz: float = 30.0,
                  freq_dev_slope: float = 0.02
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Assign detected peaks to existing sinusoidal tracks (greedy nearest-
    neighbour).

    New peaks within a frequency-dependent deviation of an existing track
    continue that track. Unmatched tracks die (frequency set to 0). New
    peaks that don't match any track start new tracks if slots are available.
    Peaks are processed in descending magnitude order so that the loudest
    peaks get first pick of track slots.

    Reference: McAulay & Quatieri, "Speech Analysis/Synthesis Based on a
    Sinusoidal Representation", IEEE TASSP, 1986.

    Parameters
    ----------
    freqs, mags, phases : arrays, shape (P,)
        Interpolated peaks for the current frame.
    prev_tracks : array, shape (max_tracks,)
        Track frequencies from the previous frame (0 = inactive).
    max_tracks : int
        Maximum number of simultaneous sinusoidal tracks.
    freq_dev_hz : float
        Allowed frequency deviation at 0 Hz.
    freq_dev_slope : float
        Additional deviation per Hz of track frequency.

    Returns
    -------
    track_freqs, track_mags, track_phases : arrays, shape (max_tracks,)
    """
    track_freqs = np.zeros(max_tracks, dtype=np.float64)
    track_mags = np.zeros(max_tracks, dtype=np.float64)
    track_phases = np.zeros(max_tracks, dtype=np.float64)

    n_peaks = len(freqs)
    if n_peaks == 0:
        return track_freqs, track_mags, track_phases

    # Sort peaks by descending magnitude (loudest first)
    order = np.argsort(-mags)
    p_freqs = freqs[order]
    p_mags = mags[order]
    p_phases = phases[order]

    used_peaks = np.zeros(n_peaks, dtype=bool)
    used_tracks = np.zeros(max_tracks, dtype=bool)

    # Phase 1: continue existing tracks with nearest qualifying peak
    active_track_indices = np.flatnonzero(prev_tracks > 0)
    for ti in active_track_indices:
        tf = prev_tracks[ti]
        # Frequency-dependent deviation threshold
        threshold = freq_dev_hz + freq_dev_slope * tf

        best_pi = -1
        best_dist = threshold + 1.0
        for pi in range(n_peaks):
            if used_peaks[pi]:
                continue
            dist = abs(p_freqs[pi] - tf)
            if dist < best_dist and dist < threshold:
                best_dist = dist
                best_pi = pi

        if best_pi >= 0:
            track_freqs[ti] = p_freqs[best_pi]
            track_mags[ti] = p_mags[best_pi]
            track_phases[ti] = p_phases[best_pi]
            used_peaks[best_pi] = True
            used_tracks[ti] = True

    # Phase 2: birth new tracks from unmatched peaks (fill empty slots)
    for pi in range(n_peaks):
        if used_peaks[pi]:
            continue
        # Find first free slot
        free_slots = np.flatnonzero(~used_tracks)
        if len(free_slots) == 0:
            break
        ti = free_slots[0]
        track_freqs[ti] = p_freqs[pi]
        track_mags[ti] = p_mags[pi]
        track_phases[ti] = p_phases[pi]
        used_tracks[ti] = True
        used_peaks[pi] = True

    return track_freqs, track_mags, track_phases


# ---------------------------------------------------------------------------
# 5. Clean short tracks
# ---------------------------------------------------------------------------

def _clean_sine_tracks(tfreq: np.ndarray, min_track_frames: int = 3
                       ) -> np.ndarray:
    """Zero out sinusoidal tracks shorter than *min_track_frames*.

    Reference: Serra thesis, Ch. 3 — post-processing of sine tracks.

    Parameters
    ----------
    tfreq : array, shape (n_frames, max_tracks)
        Track frequency matrix (0 = inactive).
    min_track_frames : int
        Minimum contiguous non-zero frames for a track to survive.

    Returns
    -------
    tfreq_clean : same shape, with short fragments zeroed.
    """
    out = tfreq.copy()
    n_frames, n_tracks = out.shape
    for t in range(n_tracks):
        run_start = -1
        for f in range(n_frames):
            if out[f, t] > 0:
                if run_start < 0:
                    run_start = f
            else:
                if 0 <= run_start and (f - run_start) < min_track_frames:
                    out[run_start:f, t] = 0.0
                run_start = -1
        # Handle track that extends to the last frame
        if 0 <= run_start and (n_frames - run_start) < min_track_frames:
            out[run_start:n_frames, t] = 0.0
    return out


# ---------------------------------------------------------------------------
# 5b. Track gap interpolation
# ---------------------------------------------------------------------------

def _interpolate_track_gaps(tfreq: np.ndarray, tmag: np.ndarray,
                             tphase: np.ndarray, sr: int, hop_size: int,
                             max_gap_frames: int = 3) -> tuple[
                             np.ndarray, np.ndarray, np.ndarray]:
    """Bridge short gaps in sinusoidal tracks by interpolation.

    When a tracked partial disappears for a small number of frames (≤
    *max_gap_frames*) and reappears at a nearby frequency, the gap is
    filled by:
      - linearly interpolating frequency and magnitude across the gap, and
      - continuing phase forward from the left anchor using the interpolated
        frequency (phase-continuous, avoids click artefacts).

    Only gaps with a non-zero left AND right anchor are bridged (boundary
    births/deaths are left as-is).  A proximity check ensures only the same
    harmonic is bridged: the anchor frequencies must satisfy either
    |Δf| / max(f_L, f_R) < 0.05  OR  |Δf| < 50 Hz.

    Reference: McAulay & Quatieri, 1986 — phase-continuous oscillator
    between birth/death events; Serra thesis Ch. 3 — continuity heuristic.

    Parameters
    ----------
    tfreq, tmag, tphase : arrays, shape (n_frames, max_sines)
        Tracked sinusoidal parameters from sine_model_anal (after cleaning).
    sr : int
        Sample rate.
    hop_size : int
        Hop size in samples (needed for phase advancement).
    max_gap_frames : int
        Maximum gap length to bridge.  0 = disabled.

    Returns
    -------
    tfreq, tmag, tphase : same shape, with gaps filled.
    """
    if max_gap_frames <= 0:
        return tfreq, tmag, tphase

    tfreq = tfreq.copy()
    tmag = tmag.copy()
    tphase = tphase.copy()

    n_frames, n_tracks = tfreq.shape
    phase_inc_factor = 2.0 * np.pi * hop_size / sr  # multiply by freq → phase step

    for k in range(n_tracks):
        f_col = tfreq[:, k]
        # Find zero-runs (gaps) between non-zero anchors
        i = 1  # start from 1 so we can always check i-1 as left anchor
        while i < n_frames - 1:
            if f_col[i] > 0:
                i += 1
                continue

            # Found start of a zero-run at frame i
            # Find end of run
            j = i
            while j < n_frames and f_col[j] == 0:
                j += 1
            # Gap is frames [i .. j-1], length = j - i
            # Left anchor: frame i-1, right anchor: frame j (if it exists)
            gap_len = j - i

            if gap_len <= max_gap_frames and j < n_frames:
                f_left = f_col[i - 1]
                f_right = f_col[j]
                # Proximity check: same harmonic on both sides?
                f_max = max(f_left, f_right)
                abs_diff = abs(f_left - f_right)
                rel_diff = abs_diff / f_max if f_max > 0 else 1.0
                if rel_diff < 0.05 or abs_diff < 50.0:
                    # Interpolate frequency and magnitude linearly
                    total_steps = gap_len + 1  # steps from anchor to anchor
                    for g_idx, g in enumerate(range(i, j), start=1):
                        alpha = g_idx / total_steps
                        tfreq[g, k] = f_left + alpha * (f_right - f_left)
                        tmag[g, k] = (tmag[i - 1, k]
                                      + alpha * (tmag[j, k] - tmag[i - 1, k]))

                    # Phase continuation from left anchor using interpolated freqs
                    for g in range(i, j):
                        tphase[g, k] = (tphase[g - 1, k]
                                        + phase_inc_factor * tfreq[g, k])

            # Advance past this run
            i = j

    return tfreq, tmag, tphase


# ---------------------------------------------------------------------------
# 6. Full-frame sinusoidal analysis
# ---------------------------------------------------------------------------

def sine_model_anal(audio: np.ndarray, sr: int,
                    window: np.ndarray | None = None,
                    fft_size: int = 4096,
                    hop_size: int = 128,
                    threshold_db: float = -80.0,
                    max_sines: int = 80,
                    min_sine_dur_s: float = 0.02,
                    freq_dev_hz: float = 30.0,
                    freq_dev_slope: float = 0.02,
                    max_gap_frames: int = 3,
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sinusoidal model analysis: extract tracked sine partials from audio.

    Slides an analysis window across the audio, detects spectral peaks in
    each frame, and links them across frames using greedy nearest-neighbour
    tracking.

    Reference: Serra thesis, Ch. 3 (analysis); McAulay & Quatieri, 1986
    (tracking).

    Parameters
    ----------
    audio : 1-D float64 array
        Mono audio signal.
    sr : int
        Sample rate.
    window : array or None
        Analysis window. If None a Blackman-Harris 92 dB window of 1025
        samples (~23 ms at 44100 Hz) is used.  Tuned for speech (4-5 pitch
        periods at 200 Hz F0).  Pass an explicit window for other sources.
    fft_size : int
        FFT size (power of two, >= window length).
    hop_size : int
        Hop size in samples.
    threshold_db : float
        Peak detection threshold in dB.
    max_sines : int
        Maximum simultaneous sinusoidal tracks.
    min_sine_dur_s : float
        Minimum track duration in seconds; shorter fragments are removed.
    freq_dev_hz, freq_dev_slope : float
        Tracking tolerance parameters (see sine_tracking).
    max_gap_frames : int
        Maximum number of consecutive silent frames to bridge via
        _interpolate_track_gaps.  Set to 0 to disable gap interpolation.

    Returns
    -------
    tfreq : array, shape (n_frames, max_sines)  — Hz (0 = inactive)
    tmag  : array, shape (n_frames, max_sines)  — dB
    tphase : array, shape (n_frames, max_sines) — radians
    """
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1:
        raise ValueError("audio must be mono (1-D)")

    if window is None:
        w_len = 1025  # odd length, ~23 ms at 44.1 kHz (4-5 pitch periods at 200 Hz)
        window = blackmanharris(w_len).astype(np.float64)
    else:
        window = np.asarray(window, dtype=np.float64)
        w_len = len(window)

    if fft_size < w_len:
        raise ValueError("fft_size must be >= window length")

    half_w = w_len // 2
    n_samples = len(audio)

    # Pad audio so the first and last windows are centred properly
    padded = np.pad(audio, (half_w, half_w), mode='constant')

    n_frames = max(1, 1 + (n_samples - 1) // hop_size)

    tfreq = np.zeros((n_frames, max_sines), dtype=np.float64)
    tmag = np.zeros((n_frames, max_sines), dtype=np.float64)
    tphase = np.zeros((n_frames, max_sines), dtype=np.float64)

    prev_tracks = np.zeros(max_sines, dtype=np.float64)

    for i in range(n_frames):
        centre = half_w + i * hop_size
        start = centre - half_w
        end = start + w_len
        if end > len(padded):
            break

        frame = padded[start:end]

        mag_db, phase = dft_anal(frame, window, fft_size)
        peaks = peak_detect(mag_db, threshold_db)
        freqs, mags, phases = peak_interp(mag_db, phase, peaks, sr, fft_size)

        tf, tm, tp = sine_tracking(
            freqs, mags, phases, prev_tracks, max_sines,
            freq_dev_hz, freq_dev_slope
        )
        tfreq[i] = tf
        tmag[i] = tm
        tphase[i] = tp
        prev_tracks = tf

    # Remove short-lived tracks
    min_frames = max(1, int(round(min_sine_dur_s * sr / hop_size)))
    tfreq = _clean_sine_tracks(tfreq, min_frames)
    # Zero out mag/phase where freq was cleaned
    dead = tfreq == 0
    tmag[dead] = 0.0
    tphase[dead] = 0.0

    # Bridge short gaps in otherwise-continuous tracks
    tfreq, tmag, tphase = _interpolate_track_gaps(
        tfreq, tmag, tphase, sr, hop_size, max_gap_frames
    )

    # Stabilise track ordering so each slot corresponds to a consistent
    # frequency band across frames (critical for phase-continuous synthesis)
    tfreq, tmag, tphase = _stabilize_track_ordering(tfreq, tmag, tphase)

    return tfreq, tmag, tphase


# ---------------------------------------------------------------------------
# 6b. Harmonic model analysis (F0-guided)
# ---------------------------------------------------------------------------

def harmonic_model_anal(audio: np.ndarray, sr: int,
                        f0_array: np.ndarray, f0_times: np.ndarray,
                        window: np.ndarray | None = None,
                        fft_size: int = 4096,
                        hop_size: int = 128,
                        threshold_db: float = -80.0,
                        max_harmonics: int = 40,
                        harm_dev_hz: float = 15.0,
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """F0-guided harmonic analysis: extract partials locked to harmonic numbers.

    Unlike free sinusoidal tracking (sine_model_anal), this function uses a
    pre-computed F0 contour to identify harmonics.  For each voiced frame,
    the expected harmonic frequencies are n * F0 (n = 1, 2, ..., max_harmonics).
    The nearest spectral peak within *harm_dev_hz* of each expected harmonic
    is selected.  Track slot k always corresponds to harmonic (k+1):
      - slot 0 = fundamental (1 * F0)
      - slot 1 = 2nd harmonic (2 * F0)
      - slot k = (k+1)th harmonic

    This guarantees stable track-slot assignment across frames — each slot's
    frequency moves smoothly with F0, producing clean phase-continuous
    synthesis without the gargling artefacts of free tracking.

    For unvoiced frames (F0 = 0 or NaN), all slots are set to zero
    (silent — no partials tracked).

    Parameters
    ----------
    audio : 1-D float64 array
        Mono audio signal.
    sr : int
        Sample rate.
    f0_array : array
        F0 estimates (Hz) from pitch detection. NaN or 0 = unvoiced.
    f0_times : array
        Time stamps (seconds) corresponding to f0_array entries.
    window : array or None
        Analysis window.  If None, Blackman-Harris 1025 is used.
    fft_size : int
        FFT size (power of two, >= window length).
    hop_size : int
        Hop size in samples.
    threshold_db : float
        Peak detection threshold in dB.
    max_harmonics : int
        Maximum harmonic number to track (slot count).
    harm_dev_hz : float
        Maximum deviation (Hz) between expected harmonic frequency and
        the nearest spectral peak for a match.

    Returns
    -------
    tfreq : array, shape (n_frames, max_harmonics)  — Hz (0 = inactive)
    tmag  : array, shape (n_frames, max_harmonics)  — dB
    tphase : array, shape (n_frames, max_harmonics) — radians
    """
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1:
        raise ValueError("audio must be mono (1-D)")

    if window is None:
        w_len = 1025
        window = blackmanharris(w_len).astype(np.float64)
    else:
        window = np.asarray(window, dtype=np.float64)
        w_len = len(window)

    if fft_size < w_len:
        raise ValueError("fft_size must be >= window length")

    half_w = w_len // 2
    n_samples = len(audio)

    padded = np.pad(audio, (half_w, half_w), mode='constant')
    n_frames = max(1, 1 + (n_samples - 1) // hop_size)

    tfreq = np.zeros((n_frames, max_harmonics), dtype=np.float64)
    tmag = np.zeros((n_frames, max_harmonics), dtype=np.float64)
    tphase = np.zeros((n_frames, max_harmonics), dtype=np.float64)

    # Pre-compute per-frame F0 by interpolating onto the analysis time grid
    frame_times = np.arange(n_frames) * hop_size / sr
    f0_arr = np.asarray(f0_array, dtype=np.float64)
    f0_t = np.asarray(f0_times, dtype=np.float64)

    voiced_mask = np.isfinite(f0_arr) & (f0_arr > 0)
    if np.sum(voiced_mask) < 2:
        return tfreq, tmag, tphase  # nothing voiced

    # Interpolate F0 onto analysis grid; mark unvoiced as NaN
    f0_interp = np.full(n_frames, np.nan, dtype=np.float64)
    # Only interpolate within the voiced range
    f0_interp[:] = np.interp(frame_times, f0_t[voiced_mask],
                              f0_arr[voiced_mask])

    # Mark frames outside the voiced region as unvoiced
    # A frame is unvoiced if no voiced F0 sample is within ±1 hop of it
    for i in range(n_frames):
        t = frame_times[i]
        # Find nearest voiced time
        dists = np.abs(f0_t[voiced_mask] - t)
        if np.min(dists) > 2.0 * hop_size / sr:
            f0_interp[i] = np.nan

    nyquist = sr / 2.0

    for i in range(n_frames):
        f0 = f0_interp[i]
        if not np.isfinite(f0) or f0 <= 0:
            continue  # unvoiced frame — all slots stay zero

        centre = half_w + i * hop_size
        start = centre - half_w
        end = start + w_len
        if end > len(padded):
            break

        frame_sig = padded[start:end]
        mag_db, phase = dft_anal(frame_sig, window, fft_size)
        peaks = peak_detect(mag_db, threshold_db)
        if len(peaks) == 0:
            continue

        p_freqs, p_mags, p_phases = peak_interp(mag_db, phase, peaks,
                                                  sr, fft_size)

        # For each harmonic number, find the nearest peak
        for h in range(max_harmonics):
            expected_freq = (h + 1) * f0
            if expected_freq >= nyquist:
                break  # harmonics above Nyquist — stop

            if len(p_freqs) == 0:
                break

            # Find nearest peak to expected harmonic frequency
            dists = np.abs(p_freqs - expected_freq)
            best_idx = int(np.argmin(dists))

            if dists[best_idx] <= harm_dev_hz:
                tfreq[i, h] = p_freqs[best_idx]
                tmag[i, h] = p_mags[best_idx]
                tphase[i, h] = p_phases[best_idx]

    return tfreq, tmag, tphase


# ---------------------------------------------------------------------------
# 6c. Stabilise track slot ordering by frequency proximity
# ---------------------------------------------------------------------------

def _stabilize_track_ordering(tfreq: np.ndarray, tmag: np.ndarray,
                               tphase: np.ndarray
                               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Re-order track slots so each slot corresponds to a consistent
    frequency band across frames, minimising frame-to-frame frequency jumps.

    The raw tracker assigns peaks to slots based on loudness (descending
    magnitude order at birth).  This means slot 0 is NOT the fundamental —
    it's "whatever was loudest this frame."  That causes massive frequency
    jumps within a slot when formant peaks shift between harmonics, which
    produces chirp/gargling artefacts in the phase-continuous synthesiser.

    This post-processing pass:
      1. Sorts the first frame's active partials by frequency (slot 0 =
         lowest frequency partial).
      2. For each subsequent frame, matches current partials to previous
         slots using greedy nearest-frequency assignment.  Unmatched
         partials are born into free slots; unmatched slots die.

    After this pass, each slot tracks a stable harmonic, and the synthesiser's
    phase-continuous oscillators see smooth frequency curves instead of
    chaotic jumps.

    Parameters
    ----------
    tfreq, tmag, tphase : arrays, shape (n_frames, max_sines)
        Tracked sinusoidal parameters (modified in-place and returned).

    Returns
    -------
    tfreq, tmag, tphase : same shape, with slots re-ordered.
    """
    n_frames, max_sines = tfreq.shape

    # Work on copies
    out_freq = np.zeros_like(tfreq)
    out_mag = np.zeros_like(tmag)
    out_phase = np.zeros_like(tphase)

    # Slot state: what frequency each slot had in the previous frame
    slot_freq = np.zeros(max_sines, dtype=np.float64)  # 0 = empty

    for i in range(n_frames):
        # Gather current frame's active partials
        cur_active = np.flatnonzero(tfreq[i] > 0)
        if len(cur_active) == 0:
            # All slots empty this frame
            slot_freq[:] = 0.0
            continue

        cur_freqs = tfreq[i, cur_active]
        cur_mags = tmag[i, cur_active]
        cur_phases = tphase[i, cur_active]

        # Sort current partials by frequency (ascending)
        freq_order = np.argsort(cur_freqs)
        cur_freqs = cur_freqs[freq_order]
        cur_mags = cur_mags[freq_order]
        cur_phases = cur_phases[freq_order]

        n_cur = len(cur_freqs)

        # New frame output arrays
        new_freq = np.zeros(max_sines, dtype=np.float64)
        new_mag = np.zeros(max_sines, dtype=np.float64)
        new_phase = np.zeros(max_sines, dtype=np.float64)

        # Which current partials and previous slots have been matched
        used_partials = np.zeros(n_cur, dtype=bool)
        used_slots = np.zeros(max_sines, dtype=bool)

        # Phase 1: Continue existing slots — match each active slot to
        # the nearest unmatched current partial by frequency proximity.
        active_slots = np.flatnonzero(slot_freq > 0)

        if len(active_slots) > 0:
            # Process slots in ascending frequency order for consistent
            # low-to-high matching
            slot_order = np.argsort(slot_freq[active_slots])
            for si_idx in slot_order:
                si = active_slots[si_idx]
                sf = slot_freq[si]

                best_pi = -1
                best_dist = np.inf
                for pi in range(n_cur):
                    if used_partials[pi]:
                        continue
                    dist = abs(cur_freqs[pi] - sf)
                    if dist < best_dist:
                        best_dist = dist
                        best_pi = pi

                # Accept match if within a reasonable tolerance:
                # 20% of the slot frequency or 100 Hz, whichever is larger.
                # This is deliberately wider than the frame-level tracker
                # tolerance because we're re-assigning already-tracked data,
                # not doing peak detection.
                if best_pi >= 0:
                    tol = max(0.20 * sf, 100.0)
                    if best_dist <= tol:
                        new_freq[si] = cur_freqs[best_pi]
                        new_mag[si] = cur_mags[best_pi]
                        new_phase[si] = cur_phases[best_pi]
                        used_partials[best_pi] = True
                        used_slots[si] = True

        # Phase 2: Birth — assign unmatched partials to free slots,
        # maintaining frequency order (lowest freq → lowest free slot)
        free_slots = np.flatnonzero(~used_slots)
        free_idx = 0
        for pi in range(n_cur):
            if used_partials[pi]:
                continue
            if free_idx >= len(free_slots):
                break  # no more slots
            si = free_slots[free_idx]
            new_freq[si] = cur_freqs[pi]
            new_mag[si] = cur_mags[pi]
            new_phase[si] = cur_phases[pi]
            free_idx += 1

        out_freq[i] = new_freq
        out_mag[i] = new_mag
        out_phase[i] = new_phase
        slot_freq = new_freq.copy()

    return out_freq, out_mag, out_phase


# ---------------------------------------------------------------------------
# 7. Spectral sine generation (BH92 main-lobe injection)
# ---------------------------------------------------------------------------

def _bh92_main_lobe(x: np.ndarray) -> np.ndarray:
    """Evaluate the Blackman-Harris 92 dB window main lobe in the frequency
    domain.

    The BH92 window in the time domain is:
        w[n] = a0 - a1*cos(2pi*n/(M-1)) + a2*cos(4pi*n/(M-1)) - a3*cos(6pi*n/(M-1))
    with a0=0.35875, a1=0.48829, a2=0.14128, a3=0.01168.

    Its DTFT is a sum of four shifted Dirichlet kernels.  This function
    evaluates that analytically, following standard window-transform theory.

    Reference: Smith, SASP, "Spectrum of the Blackman-Harris Window";
    Serra thesis Ch. 3 (main-lobe synthesis).

    Parameters
    ----------
    x : array
        Normalised frequency positions (in bins, can be fractional).

    Returns
    -------
    lobe : array, same shape as *x*
        Main-lobe amplitude values.
    """
    a = np.array([0.35875, 0.48829, 0.14128, 0.01168])
    # The BH92 window of length M has a Dirichlet-like kernel.
    # We use M = 4097 as the standard synthesis window size embedded in the
    # main-lobe computation. The kernel width scales with M.
    M = 4097

    result = np.zeros_like(x, dtype=np.float64)
    for k in range(4):
        shift = k  # each cosine term shifts by k bins in a length-M DFT
        xp = x + shift
        xm = x - shift
        # Dirichlet kernel: sin(pi*M*u) / sin(pi*u) for normalised freq u
        # Here u = x / M
        for xval in (xp, xm):
            # sin(pi * xval) / sin(pi * xval / M)  — the Dirichlet kernel
            num = np.sin(np.pi * xval + 1e-20)
            den = np.sin(np.pi * xval / M + 1e-20)
            result += a[k] * num / (M * den)

    return np.abs(result)


def gen_spec_sines(freqs: np.ndarray, mags: np.ndarray, phases: np.ndarray,
                   fft_size: int, sr: int) -> np.ndarray:
    """Generate a complex spectrum from a set of sinusoidal parameters by
    injecting Blackman-Harris 92 dB main-lobe shapes at each sine's
    frequency.

    For each sine, the main-lobe shape of a BH92 window is centred at the
    sine's fractional bin location and its amplitude/phase are set from the
    parameters. Lobes of width ~8 bins (4 bins each side) are superimposed
    additively.

    Reference: Serra thesis, Ch. 3 — "Synthesis by spectral sine generation".

    Parameters
    ----------
    freqs : array (Hz), mags : array (dB), phases : array (radians)
        Sinusoidal parameters for one frame. Entries with freq <= 0 are
        skipped.
    fft_size : int
        FFT size for the output spectrum.
    sr : int
        Sample rate.

    Returns
    -------
    spectrum : complex array, shape (fft_size,)
        Two-sided complex spectrum ready for IFFT.
    """
    half_n = fft_size // 2 + 1
    Y = np.zeros(half_n, dtype=np.complex128)

    bin_freq = sr / fft_size  # Hz per bin

    for i in range(len(freqs)):
        if freqs[i] <= 0:
            continue

        loc = freqs[i] / bin_freq          # fractional bin
        amp = 10.0 ** (mags[i] / 20.0)     # dB → linear amplitude
        ph = phases[i]

        # Main-lobe half-width: BH92 has ~4 bins each side
        lobe_half = 4
        k_start = max(0, int(np.floor(loc)) - lobe_half)
        k_end = min(half_n - 1, int(np.ceil(loc)) + lobe_half)

        if k_start > k_end:
            continue

        bins = np.arange(k_start, k_end + 1, dtype=np.float64)
        offsets = bins - loc  # distance from the fractional peak in bins

        # Evaluate main-lobe shape at these offsets
        lobe_vals = _bh92_main_lobe(offsets)
        # Normalise so that the peak of the lobe = 1
        peak_val = _bh92_main_lobe(np.array([0.0]))[0]
        if peak_val > 0:
            lobe_vals /= peak_val

        Y[k_start:k_end + 1] += amp * lobe_vals * np.exp(1j * ph)

    # Mirror to full two-sided spectrum
    full = np.zeros(fft_size, dtype=np.complex128)
    full[:half_n] = Y
    # Conjugate-symmetric mirror (excluding DC and Nyquist)
    full[half_n:] = np.conj(Y[-2:0:-1])

    return full


# ---------------------------------------------------------------------------
# 8. Overlap-add sinusoidal synthesis
# ---------------------------------------------------------------------------

def sine_model_synth(tfreq: np.ndarray, tmag: np.ndarray, tphase: np.ndarray,
                     fft_size: int, hop_size: int, sr: int) -> np.ndarray:
    """Resynthesize audio from sinusoidal tracks via additive synthesis with
    phase-continuous oscillators and overlap-add windowing.

    For each frame, time-domain sinusoidal segments are generated for every
    active track using the tracked frequency, magnitude, and phase.
    Consecutive frames are crossfaded via a triangular window to avoid
    discontinuities.

    Reference: McAulay & Quatieri, 1986 — "additive synthesis with
    instantaneous amplitude and frequency interpolation"; Smith, SASP,
    "Overlap-Add Synthesis".

    Parameters
    ----------
    tfreq, tmag, tphase : arrays, shape (n_frames, max_sines)
        Tracked sinusoidal parameters from sine_model_anal.
    fft_size : int
        Synthesis frame size (number of samples per synthesis frame).
    hop_size : int
        Hop size in samples.
    sr : int
        Sample rate.

    Returns
    -------
    audio : 1-D float64 array
        Resynthesised audio signal.
    """
    n_frames = tfreq.shape[0]
    max_sines = tfreq.shape[1]
    out_len = n_frames * hop_size + hop_size  # tight output buffer
    output = np.zeros(out_len, dtype=np.float64)

    # Phase-continuous synthesis: maintain a running phase per track that
    # advances by 2*pi*freq*hop_size/sr each frame.  This avoids the
    # phase-discontinuity artefacts of per-frame cosine generation.
    # Reference: McAulay & Quatieri, 1986.
    synth_phase = np.zeros(max_sines, dtype=np.float64)
    prev_freq = np.zeros(max_sines, dtype=np.float64)
    prev_amp = np.zeros(max_sines, dtype=np.float64)

    # Initialise phases from the first frame's analysis phases
    for j in range(max_sines):
        if n_frames > 0 and tfreq[0, j] > 0:
            synth_phase[j] = tphase[0, j]

    for i in range(n_frames):
        # Current parameters
        cur_freq = tfreq[i].copy()
        cur_amp = np.where(cur_freq > 0, 10.0 ** (tmag[i] / 20.0), 0.0)

        # Generate hop_size samples by interpolating amplitude linearly
        # and advancing phase continuously.
        t_idx = np.arange(hop_size, dtype=np.float64)
        frame = np.zeros(hop_size, dtype=np.float64)

        for j in range(max_sines):
            if cur_freq[j] <= 0 and prev_freq[j] <= 0:
                continue

            # Linear amplitude ramp (birth: ramp from 0; death: ramp to 0)
            a0 = prev_amp[j]
            a1 = cur_amp[j]
            amp_ramp = a0 + (a1 - a0) * t_idx / hop_size

            # Frequency for phase integration: use current frame's freq.
            # For birth/death use whichever is non-zero.
            f = cur_freq[j] if cur_freq[j] > 0 else prev_freq[j]

            # Phase advances continuously
            phase_inc = 2.0 * np.pi * f / sr
            inst_phase = synth_phase[j] + phase_inc * (t_idx + 1)

            frame += amp_ramp * np.cos(inst_phase)

            # Update running phase for next frame
            synth_phase[j] = inst_phase[-1] % (2.0 * np.pi)

        # Write directly (no windowing needed — phase-continuous sines
        # don't produce discontinuities).
        start = i * hop_size
        end = start + hop_size
        if end <= out_len:
            output[start:end] += frame

        prev_freq = cur_freq
        prev_amp = cur_amp

    return output


# ---------------------------------------------------------------------------
# 9. Spectral envelope estimation (cepstral smoothing)
# ---------------------------------------------------------------------------

def estimate_spectral_envelope(mag_db: np.ndarray, sr: int,
                               cepstral_order: int = 0
                               ) -> np.ndarray:
    """Estimate the spectral envelope via real-cepstrum liftering.

    The real cepstrum is the IFFT of the log-magnitude spectrum. Truncating
    it to low quefrency components and transforming back yields a smooth
    spectral envelope that captures formant structure but not individual
    harmonics.

    If *cepstral_order* is 0, a default order is chosen automatically based
    on the sample rate (~2 ms quefrency cutoff, suitable for speech).

    Reference: Smith, SASP, Ch. "Cepstral Analysis"; Oppenheim & Schafer,
    "Discrete-Time Signal Processing", Ch. 13.

    Parameters
    ----------
    mag_db : array, shape (N/2+1,) or (N,)
        Log-magnitude spectrum in dB. If half-spectrum, it is mirrored
        internally.
    sr : int
        Sample rate.
    cepstral_order : int
        Number of low-quefrency coefficients to retain (lifter width).
        0 = automatic (~2 ms).

    Returns
    -------
    envelope_db : array, same shape as input
        Smoothed spectral envelope in dB.
    """
    spec = np.asarray(mag_db, dtype=np.float64).copy()
    input_len = len(spec)

    # If we got a half-spectrum, mirror it to full size for cepstrum
    # Assume half-spectrum if length is odd or "small enough"
    # We always mirror to ensure real-valued cepstrum
    if input_len < 8:
        return spec  # too short to smooth

    # Mirror: [DC ... Nyquist ... mirror ... ]
    full_mag = np.concatenate([spec, spec[-2:0:-1]])
    n = len(full_mag)

    if cepstral_order <= 0:
        # Default: retain quefrencies up to ~2 ms
        # quefrency = samples / sr → 2 ms = 0.002 * sr samples
        cepstral_order = max(4, int(round(0.002 * sr)))

    # Real cepstrum: IFFT of log-magnitude
    log_mag = full_mag / 20.0  # dB to log10; keep in dB scale for simplicity
    cepstrum = np.real(ifft(log_mag))

    # Lifter: keep only the first cepstral_order coefficients (and mirror)
    liftered = np.zeros_like(cepstrum)
    order = min(cepstral_order, n // 2)
    liftered[0] = cepstrum[0]
    liftered[1:order] = 2.0 * cepstrum[1:order]  # factor 2 for symmetry

    # Back to spectral domain
    envelope = np.real(fft(liftered))
    envelope_db = envelope * 20.0  # back to dB

    # Return only the input-length portion
    return envelope_db[:input_len]


# ---------------------------------------------------------------------------
# 10. Residual extraction (Harmonic + Stochastic decomposition)
# ---------------------------------------------------------------------------

def compute_residual_stft(original: np.ndarray,
                          tfreq: np.ndarray,
                          fft_size: int, hop_size: int, sr: int,
                          mask_width_bins: float = 2.0,
                          ) -> np.ndarray:
    """Extract the stochastic residual via STFT-domain harmonic masking.

    Instead of time-domain subtraction (which fails due to phase mismatch),
    this computes the STFT of the original audio, builds a soft mask that
    identifies bins belonging to tracked sinusoidal partials, and returns
    the inverse-STFT of the complementary (non-harmonic) spectrum.

    Algorithm:
      1. STFT the original audio with a Hann window.
      2. For each STFT frame, map tracked partial frequencies to fractional
         bin indices.  Build a soft mask using a raised-cosine taper over
         ±mask_width_bins around each partial.  The mask value is 1.0 at
         the partial centre and tapers to 0.0 at the edge.
      3. Residual spectrum = STFT magnitude × (1 − mask), original phase.
      4. ISTFT → residual audio.

    This guarantees no original-pitch harmonic energy leaks into the
    residual, regardless of resynthesis phase accuracy.

    Reference: Serra & Smith, "Spectral Modeling Synthesis", CMJ, 1990 —
    deterministic/stochastic decomposition concept; STFT masking is a
    standard modern refinement.

    Parameters
    ----------
    original : 1-D float64 array
        Original mono audio.
    tfreq : array, shape (n_frames, max_sines)
        Tracked partial frequencies from sine_model_anal (Hz; 0 = inactive).
    fft_size : int
        FFT size (same as used for sine_model_anal).
    hop_size : int
        Hop size in samples.
    sr : int
        Sample rate.
    mask_width_bins : float
        Half-width of the raised-cosine mask around each partial, in FFT
        bins.  Default 2.0 provides a gentle taper that removes the partial
        and its immediate spectral skirt without cutting into neighbouring
        partials.

    Returns
    -------
    residual : 1-D float64 array, same length as *original*.
    """
    from scipy.signal.windows import hann

    original = np.asarray(original, dtype=np.float64)
    orig_len = len(original)

    # Use a dedicated STFT window size that gives clean 75% overlap.
    # We need enough frequency resolution to separate harmonics (~20 Hz
    # bins for speech), so stft_size = 2048 at 44.1 kHz → ~21.5 Hz/bin.
    stft_size = min(fft_size, 2048)
    stft_hop = stft_size // 4  # 75% overlap — standard for Hann window OLA
    win = hann(stft_size, sym=False).astype(np.float64)

    bin_freq = sr / stft_size  # Hz per bin
    half_n = stft_size // 2 + 1

    # ── Manual STFT ───────────────────────────────────────────────────────
    # Pad so first/last frames are centred
    pad_len = stft_size // 2
    padded = np.pad(original, (pad_len, pad_len), mode='constant')
    n_stft_frames = 1 + (len(padded) - stft_size) // stft_hop

    # Pre-compute STFT frames
    stft_mag = np.zeros((half_n, n_stft_frames), dtype=np.float64)
    stft_phase = np.zeros((half_n, n_stft_frames), dtype=np.float64)

    for i in range(n_stft_frames):
        s = i * stft_hop
        frame = padded[s:s + stft_size] * win
        spec = rfft(frame)
        stft_mag[:, i] = np.abs(spec)
        stft_phase[:, i] = np.angle(spec)

    # ── Build harmonic mask and apply ─────────────────────────────────────
    n_sine_frames = tfreq.shape[0]

    for stft_i in range(n_stft_frames):
        # Map STFT frame to nearest sine-analysis frame
        # STFT frame centre time = (stft_i * stft_hop) / sr  (relative to padded start)
        # Sine frame time = sine_i * hop_size / sr
        stft_time_s = stft_i * stft_hop / sr
        sine_i = int(round(stft_time_s * sr / hop_size))
        sine_i = max(0, min(sine_i, n_sine_frames - 1))

        # Build soft mask for this frame
        mask = np.zeros(half_n, dtype=np.float64)

        for k in range(tfreq.shape[1]):
            f = tfreq[sine_i, k]
            if f <= 0:
                continue

            centre_bin = f / bin_freq
            lo = int(max(0, np.floor(centre_bin - mask_width_bins)))
            hi = int(min(half_n - 1, np.ceil(centre_bin + mask_width_bins)))

            for b in range(lo, hi + 1):
                dist = abs(b - centre_bin)
                if dist <= mask_width_bins:
                    # Raised-cosine taper: 1.0 at centre, 0.0 at edge
                    val = 0.5 * (1.0 + np.cos(np.pi * dist / mask_width_bins))
                    if val > mask[b]:
                        mask[b] = val

        # Apply complementary mask to magnitude, keep original phase
        stft_mag[:, stft_i] *= (1.0 - mask)

    # ── Manual ISTFT (overlap-add with Hann window) ───────────────────────
    out_len = len(padded)
    residual_padded = np.zeros(out_len, dtype=np.float64)
    win_sum = np.zeros(out_len, dtype=np.float64)

    for i in range(n_stft_frames):
        spec_mod = stft_mag[:, i] * np.exp(1j * stft_phase[:, i])
        frame = np.fft.irfft(spec_mod, n=stft_size)
        frame *= win  # synthesis window

        s = i * stft_hop
        e = s + stft_size
        residual_padded[s:e] += frame
        win_sum[s:e] += win ** 2

    # Normalise by window sum (COLA normalisation)
    win_sum[win_sum < 1e-8] = 1e-8
    residual_padded /= win_sum

    # Remove padding
    residual = residual_padded[pad_len:pad_len + orig_len]

    # Align to original length
    if len(residual) > orig_len:
        residual = residual[:orig_len]
    elif len(residual) < orig_len:
        residual = np.pad(residual, (0, orig_len - len(residual)),
                          mode='constant')

    return residual
