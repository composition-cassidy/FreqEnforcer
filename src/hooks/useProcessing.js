import { useRef, useCallback, useEffect } from 'react';

import { API_BASE } from '../config/api';

// -- Settings to backend parameter mapping --
// Formulas verified against PyQt6 SettingsPanel.get_settings()

// Ensure a value is a finite number, falling back to a default.
function safeNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function settingsToBackend(settings) {
  // Harmonic compression amount (0-100 UI) maps to:
  //   Amount 0%   -> Knee 12 dB (soft), Release 200 ms (slow) -- gentlest
  //   Amount 100% -> Knee 0 dB  (hard), Release 10 ms  (fast) -- most aggressive
  const amount    = parseFloat(settings.harmonic_amount) || 0;
  const knee_db   = 12.0 - (amount / 100.0) * 12.0;
  const release_ms = 200.0 - (amount / 100.0) * 190.0;

  // Harmonic ceiling offsets: keys must be strings for JSON / FastAPI Dict[str, float]
  const ceilingOffsets = Object.fromEntries(
    Object.entries(settings.harmonic_ceiling_offsets_db ?? {}).map(([k, v]) => [String(k), Number(v)])
  );

  // formant_shift_cents must be an integer for the backend's Pydantic model;
  // the slider emits continuous floats, so round here.
  const formantCents = Math.round(safeNum(settings.formant_shift_cents, 0));

  return {
    target_note:              `${settings.targetNote ?? 'C'}${settings.octave ?? 4}`,
    pitch_mode:               settings.pitch_mode     ?? 'world_hard',
    pitch_amount:             safeNum(settings.pitch_amount, 1.0),
    retune_speed_ms:          safeNum(settings.retune_speed_ms, 40),
    preserve_vibrato:         safeNum(settings.preserve_vibrato, 1.0),
    preserve_formants:        formantCents === 0,
    normalize:                !!settings.normalize,
    formant_shift_cents:      formantCents,
    formant_shift_beta:       safeNum(settings.formant_shift_beta, 0.1),
    stretch_method:           settings.stretch_method  ?? 'audiotsm_wsola',
    stretch_factor:           safeNum(settings.stretch_factor, 1.0),
    cleanliness_percent:      safeNum(settings.cleanliness_percent, 0),
    clean_lowcut_percent:     safeNum(settings.clean_lowcut_percent, 0),
    clean_hf_rollback_percent: safeNum(settings.clean_hf_rollback_percent, 0),
    breathiness:              safeNum(settings.breathiness, 1.0),
    hf_bias:                  safeNum(settings.hf_bias, 0),
    harmonic_limiter_enabled: !!settings.harmonic_limiter_enabled,
    harmonic_knee_db:         knee_db,
    harmonic_release_ms:      release_ms,
    harmonic_ceiling_offsets_db: ceilingOffsets,
    // null keeps the backend's per-mode default (force / strict)
    voicing_mode:             settings.voicing_mode ?? null,
  };
}

// -- useProcessing --
/**
 * Manages the full processing pipeline lifecycle:
 *   - Prevents concurrent requests (queues the latest settings as pending)
 *   - Token-based stale-result detection (if superseded while in-flight, re-runs)
 *   - SSE progress stream from /api/process-progress
 *   - 60-second timeout on the processing request
 *
 * @param {{ onStart, onProgress, onComplete, onError }} callbacks
 * @returns {{ queueProcess(settings): void, cancelProcess(): void }}
 */
export function useProcessing({ onStart, onProgress, onComplete, onError }) {
  // Stable callback refs so queueProcess never needs to change identity
  const onStartRef    = useRef(onStart);
  const onProgressRef = useRef(onProgress);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef    = useRef(onError);

  useEffect(() => { onStartRef.current    = onStart;    }, [onStart]);
  useEffect(() => { onProgressRef.current = onProgress; }, [onProgress]);
  useEffect(() => { onCompleteRef.current = onComplete; }, [onComplete]);
  useEffect(() => { onErrorRef.current    = onError;    }, [onError]);

  // Internal mutable state (refs keep queueProcess stable)
  const tokenRef    = useRef(0);
  const inFlightRef = useRef(false);
  const pendingRef  = useRef(null);   // { settings } waiting to run after current finishes
  const sseRef      = useRef(null);

  const closeSse = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, []);

  // Cancel in-flight processing (best-effort token invalidation)
  const cancelProcess = useCallback(() => {
    tokenRef.current = tokenRef.current + 1; // stale-mark any in-flight result
    pendingRef.current = null;               // drop queued work
    closeSse();
  }, [closeSse]);

  // Core processing runner
  const runProcess = useCallback(async (settings, token) => {
    inFlightRef.current = true;
    onStartRef.current?.();

    // Open SSE for progress BEFORE sending POST
    closeSse();
    try {
      const sse = new EventSource(`${API_BASE}/api/process-progress`);
      sseRef.current = sse;
      sse.onmessage = (e) => {
        try {
          const payload = JSON.parse(e.data);
          if (typeof payload.progress === 'number') {
            onProgressRef.current?.(Math.round(payload.progress * 100), payload.stage ?? '');
          }
        } catch (_) { /* malformed event -- ignore */ }
      };
      sse.onerror = () => {
        closeSse();
        // SSE dropped mid-processing -- fall back to indeterminate progress
        onProgressRef.current?.(0);
      };
    } catch (_) {
      // EventSource not supported or URL bad -- proceed without progress
    }

    // Send the processing request with a 60-second timeout
    const backendSettings = settingsToBackend(settings);

    const fetchCtrl = new AbortController();
    const fetchTimeout = setTimeout(() => fetchCtrl.abort(), 60000);
    try {
      const res = await fetch(`${API_BASE}/api/process`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(backendSettings),
        signal:  fetchCtrl.signal,
      });
      clearTimeout(fetchTimeout);

      closeSse();

      // Check if our token is still current
      if (tokenRef.current !== token) {
        // A newer settings change arrived while we were waiting for the response.
        // Discard this result and kick off the pending run immediately.
        inFlightRef.current = false;
        if (pendingRef.current) {
          const { settings: nextSettings } = pendingRef.current;
          pendingRef.current = null;
          const nextToken = ++tokenRef.current;
          runProcess(nextSettings, nextToken);
        }
        return;
      }

      if (!res.ok) {
        // 409 = server-side superseded (shouldn't normally reach here, but handle gracefully)
        if (res.status === 409) {
          inFlightRef.current = false;
          if (pendingRef.current) {
            const { settings: nextSettings } = pendingRef.current;
            pendingRef.current = null;
            const nextToken = ++tokenRef.current;
            runProcess(nextSettings, nextToken);
          }
          return;
        }
        let detail = res.statusText;
        try {
          const body = await res.json();
          const d = body.detail;
          // Pydantic 422 returns detail as an array of error objects;
          // flatten them into a readable string.
          if (Array.isArray(d)) {
            detail = d.map((e) => {
              const loc = (e.loc || []).slice(1).join(' → ');
              return loc ? `${loc}: ${e.msg}` : (e.msg || String(e));
            }).join('; ');
          } else if (typeof d === 'string') {
            detail = d;
          } else if (d != null) {
            detail = JSON.stringify(d);
          }
        } catch (_) {}
        throw new Error(detail);
      }

      const data = await res.json();

      inFlightRef.current = false;
      onCompleteRef.current?.(data);

      // If new settings arrived during processing, run them now
      if (pendingRef.current) {
        const { settings: nextSettings } = pendingRef.current;
        pendingRef.current = null;
        const nextToken = ++tokenRef.current;
        runProcess(nextSettings, nextToken);
      }
    } catch (err) {
      clearTimeout(fetchTimeout);
      closeSse();
      inFlightRef.current = false;

      if (tokenRef.current === token) {
        // AbortError from our 60s timeout -> friendly message flagged with "timeout"
        const msg = err.name === 'AbortError'
          ? 'Processing timed out -- timeout'
          : (err.message ?? String(err));
        onErrorRef.current?.(msg);
      }

      // Still drain pending after an error
      if (pendingRef.current) {
        const { settings: nextSettings } = pendingRef.current;
        pendingRef.current = null;
        const nextToken = ++tokenRef.current;
        runProcess(nextSettings, nextToken);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closeSse]);

  // Public API:
  // Queue a new processing run. If already in flight, store as pending
  // (will be picked up automatically when the current request finishes).
  const queueProcess = useCallback((settings) => {
    if (inFlightRef.current) {
      // Bump token so the in-flight result will be discarded
      tokenRef.current = tokenRef.current + 1;
      pendingRef.current = { settings };
      return;
    }
    const token = ++tokenRef.current;
    runProcess(settings, token);
  }, [runProcess]);

  // Cleanup SSE on unmount
  useEffect(() => () => closeSse(), [closeSse]);

  return { queueProcess, cancelProcess };
}
