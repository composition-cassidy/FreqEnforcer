import numpy as np


def find_pitch_period(audio, sr, f0_hint=None):
    """
    Find the true pitch period using autocorrelation.
    Returns period in samples, or a default if unpitched.
    """
    start = int(len(audio) * 0.2)
    end = int(len(audio) * 0.5)
    region = audio[start:end]

    if len(region) < 2000:
        return sr // 200  # default ~200 Hz

    chunk = region[:2000]
    autocorr = np.correlate(chunk, chunk, mode='full')
    autocorr = autocorr[len(chunk):]

    if f0_hint and f0_hint > 20:
        expected = sr / f0_hint
        min_lag = max(1, int(expected * 0.8))
        max_lag = min(len(autocorr) - 1, int(expected * 1.2))
    else:
        min_lag = sr // 2000
        max_lag = min(len(autocorr) - 1, sr // 50)

    if max_lag <= min_lag or max_lag >= len(autocorr):
        return sr // 200

    search = autocorr[min_lag:max_lag]
    if len(search) == 0:
        return sr // 200

    period = min_lag + np.argmax(search)

    if autocorr[period] < autocorr[0] * 0.2:
        return sr // 200  # not periodic

    return period


def find_loop_by_template_matching(audio, sr, pitch_period,
                                    template_periods=6,
                                    min_loop_periods=10,
                                    search_step_divisor=4):
    """
    TEMPLATE MATCHING LOOP FINDER

    Takes a template chunk from the sustain center and slides it across
    the rest of the sample, finding where the waveform pattern repeats
    most closely. The two matching positions become loop boundaries.

    This produces dramatically better seams than RMS-based or correlation-
    based methods because the waveform at loop_end literally looks like
    the waveform at loop_start.

    Args:
        audio: float32 mono array
        sr: sample rate
        pitch_period: pitch period in samples
        template_periods: template length in pitch periods (default 6)
        min_loop_periods: minimum loop length in pitch periods (default 10)
        search_step_divisor: search resolution = pitch_period / this (default 4)

    Returns:
        (loop_start, loop_end, match_correlation) or (None, None, 0)
    """
    template_len = pitch_period * template_periods
    min_loop_len = pitch_period * min_loop_periods

    # Pick template from the center of the sustain region (most stable area)
    sustain_start = int(len(audio) * 0.20)
    sustain_end = int(len(audio) * 0.80)
    sustain_center = (sustain_start + sustain_end) // 2

    # Ensure template fits
    if sustain_center + template_len > len(audio):
        return (None, None, 0)
    if sustain_end - sustain_start < min_loop_len + template_len:
        return (None, None, 0)

    template = audio[sustain_center : sustain_center + template_len]

    # Normalize template for amplitude-invariant matching
    tmpl_norm = template - np.mean(template)
    tmpl_energy = np.sqrt(np.sum(tmpl_norm ** 2))

    if tmpl_energy < 1e-8:
        return (None, None, 0)  # silent template

    # Slide template across the sustain region
    step = max(1, pitch_period // search_step_divisor)
    search_positions = range(sustain_start, sustain_end - template_len, step)

    matches = []
    for pos in search_positions:
        candidate = audio[pos : pos + template_len]
        cand_norm = candidate - np.mean(candidate)
        cand_energy = np.sqrt(np.sum(cand_norm ** 2))

        if cand_energy < 1e-8:
            continue

        # Normalized cross-correlation (amplitude invariant)
        ncc = np.sum(tmpl_norm * cand_norm) / (tmpl_energy * cand_energy)

        # Also check RMS similarity (we want matched dynamics)
        rms_tmpl = np.sqrt(np.mean(template ** 2))
        rms_cand = np.sqrt(np.mean(candidate ** 2))
        rms_ratio = min(rms_tmpl, rms_cand) / max(rms_tmpl, rms_cand) if max(rms_tmpl, rms_cand) > 0 else 0

        matches.append((pos, ncc, rms_ratio))

    if not matches:
        return (None, None, 0)

    # Sort by correlation (best shape match first)
    matches.sort(key=lambda x: -x[1])

    # Find the best match that's far enough from the template to make a usable loop
    for pos, ncc, rms_ratio in matches:
        distance = abs(pos - sustain_center)
        if distance >= min_loop_len:
            # Determine loop start and end
            if pos < sustain_center:
                lp_start = pos
                lp_end = sustain_center + template_len
            else:
                lp_start = sustain_center
                lp_end = pos + template_len

            # Clamp to audio bounds
            lp_start = max(0, lp_start)
            lp_end = min(len(audio) - 1, lp_end)

            return (lp_start, lp_end, ncc)

    return (None, None, 0)


def fine_tune_loop_end(audio, loop_start, loop_end, pitch_period):
    """
    Fine-tune loop_end by searching sample-by-sample within one pitch
    period to find the exact position where the seam discontinuity
    (sample value jump) is minimized.

    This finds the precise phase-aligned position where the waveform
    at loop_end matches the waveform at loop_start most closely.

    Returns:
        adjusted loop_end
    """
    best_jump = abs(audio[loop_end - 1] - audio[loop_start])
    best_offset = 0

    search_range = pitch_period  # search ±1 pitch period

    for offset in range(-search_range, search_range + 1):
        test_end = loop_end + offset
        if test_end <= loop_start + pitch_period or test_end >= len(audio):
            continue

        jump = abs(audio[test_end - 1] - audio[loop_start])
        if jump < best_jump:
            best_jump = jump
            best_offset = offset

    return loop_end + best_offset


def apply_safety_crossfade(audio, loop_start, loop_end, pitch_period, xfade_periods=2):
    """
    Apply a SHORT equal-power crossfade as a safety net.

    Because template matching already produces a near-perfect seam,
    we only need a very short crossfade (2 pitch periods instead of 6)
    to smooth over any remaining micro-differences.

    Includes gain compensation for decaying sounds.

    Returns:
        modified audio (copy)
    """
    result = audio.copy()

    xfade_len = pitch_period * xfade_periods
    loop_len = loop_end - loop_start

    # Crossfade can't exceed 15% of loop (it's a safety net, not the fix)
    xfade_len = min(xfade_len, loop_len // 7)

    if xfade_len < 16:
        return result

    end_region = result[loop_end - xfade_len : loop_end].copy()
    start_region = result[loop_start : loop_start + xfade_len].copy()

    # Gain compensation: scale end to match start energy
    rms_end = np.sqrt(np.mean(end_region ** 2))
    rms_start = np.sqrt(np.mean(start_region ** 2))

    if rms_end > 1e-6 and rms_start > 1e-6:
        gain = rms_start / rms_end
        gain = min(gain, 2.0)  # cap at +6 dB
        end_region *= gain

    # Equal-power crossfade
    t = np.linspace(0, 1, xfade_len, dtype=np.float32)
    blended = end_region * np.sqrt(1 - t) + start_region * np.sqrt(t)

    result[loop_end - xfade_len : loop_end] = blended
    return result


def process_with_loop(audio, sr, f0_hz=None,
                       template_periods=6,
                       min_loop_periods=10,
                       crossfade_periods=2):
    """
    Full pipeline:
    1. Detect pitch period
    2. Template-match to find where the waveform pattern repeats
    3. Fine-tune loop_end for exact phase alignment
    4. Apply short safety crossfade with gain compensation

    Args:
        audio: float32 mono array
        sr: sample rate
        f0_hz: detected fundamental (from FreqEnforcer pitch detector)
        template_periods: template length in pitch periods (default 6)
        min_loop_periods: minimum loop length in pitch periods (default 10)
        crossfade_periods: safety crossfade length in pitch periods (default 2)

    Returns:
        (processed_audio, loop_start, loop_end)
        Returns (audio, None, None) if no suitable loop found.
    """
    # Step 1: Find pitch period
    period = find_pitch_period(audio, sr, f0_hint=f0_hz)

    # Step 2: Template matching — find where the waveform pattern repeats
    lp_start, lp_end, _corr = find_loop_by_template_matching(
        audio, sr, period,
        template_periods=template_periods,
        min_loop_periods=min_loop_periods,
    )

    if lp_start is None:
        return (audio, None, None)

    # Step 3: Fine-tune loop_end for minimal seam discontinuity
    lp_end = fine_tune_loop_end(audio, lp_start, lp_end, period)

    # Step 4: Apply short gain-compensated safety crossfade
    result = apply_safety_crossfade(audio, lp_start, lp_end, period, crossfade_periods)

    return (result, lp_start, lp_end)
