import { useRef, useState, useCallback, useEffect } from 'react';

import { API_BASE } from '../config/api';

// ── useAudioPlayer ─────────────────────────────────────────────────────────
/**
 * Manages audio playback with one HTMLAudioElement streaming the backend's
 * temp WAVs (GET /api/audio-file/{name}).
 *
 * Uses HTMLAudioElement instead of Web Audio API's decodeAudioData to avoid
 * a Chromium renderer crash (ACCESS_VIOLATION) on some Windows systems.
 *
 * Exposed API:
 *   play()            start or resume
 *   stop()            stop and reset position to 0
 *   reset()           stop + forget both sources + duration → 0
 *   loadOriginal(name)           original side = /api/audio-file/<name>
 *   loadProcessedFromFile(name)  processed side = /api/audio-file/<name>
 *   switchBuffer(which)  change active side; restarts if playing
 *   subscribe(fn)     fn(positionSec, durationSec) on every animation frame
 *                     while playing, and once after stop/seek/reset; returns
 *                     an unsubscribe function. The playhead and time readout
 *                     draw from this, so playback never re-renders React.
 *   isPlaying         boolean (React state)
 *   duration          number  (React state, seconds; 0 when nothing loaded)
 */
export function useAudioPlayer() {
  // ── React state (drives renders) ──────────────────────────────────────
  const [isPlaying,        setIsPlaying]        = useState(false);
  const [duration,         setDuration]         = useState(0);

  // ── Internal mutable refs ───────────────────────────────────────────
  const audioElRef        = useRef(null);         // HTMLAudioElement
  const originalUrlRef    = useRef(null);          // Blob URL for original
  const processedUrlRef   = useRef(null);          // Blob URL for processed
  const activeBufferRef   = useRef('original');    // 'original' | 'processed'
  const isPlayingRef      = useRef(false);
  const rafRef            = useRef(null);
  const listenersRef      = useRef(new Set());

  /** Push the current position to every frame listener. */
  function emit(pos) {
    const el = audioElRef.current;
    const p = pos ?? el?.currentTime ?? 0;
    const d = el && Number.isFinite(el.duration) ? el.duration : 0;
    for (const fn of listenersRef.current) fn(p, d);
  }

  // ── Get or create the <audio> element ───────────────────────────────
  function getAudioEl() {
    if (!audioElRef.current) {
      const el = new Audio();
      el.preload = 'auto';

      // When playback reaches end naturally
      el.addEventListener('ended', () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        cancelRaf();
        emit(0);
      });

      // Track duration when metadata loads
      el.addEventListener('loadedmetadata', () => {
        if (Number.isFinite(el.duration)) {
          setDuration(el.duration);
          emit();
        }
      });

      audioElRef.current = el;
    }
    return audioElRef.current;
  }

  function cancelRaf() {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }

  // ── One rAF loop while playing: engine time -> listeners ────────────
  // Every frame, unthrottled and unsmoothed: the playhead shows where the
  // audio element actually is. No React state is touched per frame.
  function startRaf() {
    cancelRaf();
    function tick() {
      if (!isPlayingRef.current || !audioElRef.current) return;
      emit();
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
  }

  /** Get the Blob URL for the currently active side. */
  function getActiveUrl() {
    return activeBufferRef.current === 'processed'
      ? processedUrlRef.current
      : originalUrlRef.current;
  }

  /** Forget a side's URL (the backend deletes the temp file when replaced). */
  function revokeUrl(ref) { ref.current = null; }

  /**
   * Point one side at a temp WAV the backend serves from /api/audio-file
   * (the loaded original or the latest processed result); streamed, no base64.
   */
  function setSource(which, filename) {
    const ref = which === 'original' ? originalUrlRef : processedUrlRef;
    ref.current = filename ? `${API_BASE}/api/audio-file/${encodeURIComponent(filename)}` : null;
    if (which === activeBufferRef.current && ref.current) {
      const el = getAudioEl();
      el.src = ref.current;
      el.load();
    }
  }

  // ── Public API ─────────────────────────────────────────────────────

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadOriginal = useCallback((filename) => setSource('original', filename), []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadProcessedFromFile = useCallback((filename) => setSource('processed', filename), []);

  /** Start or resume playback. */
  const play = useCallback(() => {
    const el = getAudioEl();
    const url = getActiveUrl();
    if (!url) return; // nothing loaded

    const wasCached = el.src === url;

    // If src doesn't match the active URL, switch
    if (!wasCached) {
      const savedTime = el.currentTime || 0;
      el.src = url;
      el.load();
      el.currentTime = savedTime;
    }

    el.play().then(() => {
      isPlayingRef.current = true;
      setIsPlaying(true);
      startRaf();
    }).catch((err) => {
      console.warn('useAudioPlayer: play() rejected:', err.message);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Jump to a position (seconds) on the active side; keeps playing if it was. */
  const seek = useCallback((seconds) => {
    const el = audioElRef.current;
    if (!el || !getActiveUrl()) return;
    const dur = Number.isFinite(el.duration) ? el.duration : 0;
    el.currentTime = Math.max(0, Math.min(dur || seconds, seconds));
    emit();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Stop playback and reset position to the beginning. */
  const stop = useCallback(() => {
    const el = audioElRef.current;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    isPlayingRef.current = false;
    setIsPlaying(false);
    cancelRaf();
    emit(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Stop, release both Blob URLs, and reset duration.
   * Call on New Sample to free memory.
   */
  const reset = useCallback(() => {
    const el = audioElRef.current;
    if (el) {
      el.pause();
      el.removeAttribute('src');
      el.load(); // reset the element
    }
    revokeUrl(originalUrlRef);
    revokeUrl(processedUrlRef);
    activeBufferRef.current = 'original';
    isPlayingRef.current = false;
    setIsPlaying(false);
    setDuration(0);
    cancelRaf();
    for (const fn of listenersRef.current) fn(0, 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Switch the active audio side.
   * If currently playing: restart from the same position on the new side.
   * If the target side is not loaded yet: stop cleanly.
   */
  const switchBuffer = useCallback((which) => {
    activeBufferRef.current = which;
    const url = which === 'processed'
      ? processedUrlRef.current
      : originalUrlRef.current;

    const el = getAudioEl();
    const wasPlaying = isPlayingRef.current;
    const savedTime  = el.currentTime || 0;

    if (!url) {
      // Target not loaded — stop
      stop();
      return;
    }

    // Switch the audio source
    el.pause();
    el.src = url;
    el.load();

    // loadedmetadata will update duration automatically.
    // Restore position and resume if was playing.
    const onReady = () => {
      el.removeEventListener('canplay', onReady);
      if (Number.isFinite(savedTime) && savedTime < el.duration) {
        el.currentTime = savedTime;
      }
      if (wasPlaying) {
        el.play().then(() => {
          isPlayingRef.current = true;
          setIsPlaying(true);
          startRaf();
        }).catch(() => {});
      }
    };
    el.addEventListener('canplay', onReady);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop]);

  const subscribe = useCallback((fn) => {
    listenersRef.current.add(fn);
    return () => listenersRef.current.delete(fn);
  }, []);

  // ── Cleanup on unmount ──────────────────────────────────────────────
  useEffect(() => {
    return () => {
      cancelRaf();
      const el = audioElRef.current;
      if (el) {
        el.pause();
        el.removeAttribute('src');
      }
      revokeUrl(originalUrlRef);
      revokeUrl(processedUrlRef);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    play,
    stop,
    seek,
    reset,
    loadOriginal,
    loadProcessedFromFile,
    switchBuffer,
    subscribe,
    isPlaying,
    duration,
  };
}
