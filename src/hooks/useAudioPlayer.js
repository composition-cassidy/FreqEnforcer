import { useRef, useState, useCallback, useEffect } from 'react';

import { API_BASE } from '../config/api';

// ── useAudioPlayer ─────────────────────────────────────────────────────────
/**
 * Manages audio playback using HTMLAudioElement + Blob URLs.
 *
 * Uses HTMLAudioElement instead of Web Audio API's decodeAudioData to avoid
 * a Chromium renderer crash (ACCESS_VIOLATION) on some Windows systems.
 *
 * Exposed API:
 *   play()            start or resume
 *   stop()            stop and reset position to 0
 *   reset()           stop + release both audio URLs + duration → 0
 *   loadOriginal()    fetch /api/get-audio { which: "original" }, create Blob URL
 *   loadProcessed()   fetch /api/get-audio { which: "processed" }, create Blob URL
 *   switchBuffer(which)  change active side; restarts if playing
 *   isPlaying         boolean (React state)
 *   playbackPosition  number  (React state, seconds)
 *   duration          number  (React state, seconds; 0 when nothing loaded)
 */
export function useAudioPlayer() {
  // ── React state (drives renders) ──────────────────────────────────────
  const [isPlaying,        setIsPlaying]        = useState(false);
  const [playbackPosition, setPlaybackPosition] = useState(0);
  const [duration,         setDuration]         = useState(0);

  // ── Internal mutable refs ───────────────────────────────────────────
  const audioElRef        = useRef(null);         // HTMLAudioElement
  const originalUrlRef    = useRef(null);          // Blob URL for original
  const processedUrlRef   = useRef(null);          // Blob URL for processed
  const activeBufferRef   = useRef('original');    // 'original' | 'processed'
  const isPlayingRef      = useRef(false);
  const rafRef            = useRef(null);
  const lastFrameRef      = useRef(0);

  // ── Get or create the <audio> element ───────────────────────────────
  function getAudioEl() {
    if (!audioElRef.current) {
      const el = new Audio();
      el.preload = 'auto';

      // When playback reaches end naturally
      el.addEventListener('ended', () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        setPlaybackPosition(0);
        cancelRaf();
      });

      // Track duration when metadata loads
      el.addEventListener('loadedmetadata', () => {
        if (Number.isFinite(el.duration)) {
          setDuration(el.duration);
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

  // ── rAF position tracking (throttled to ~15 fps) ────────────────────
  function startRaf() {
    cancelRaf();
    function tick() {
      if (!isPlayingRef.current) return;
      const el = audioElRef.current;
      if (!el) return;

      const now = performance.now();
      if (now - lastFrameRef.current >= 66) {
        lastFrameRef.current = now;
        setPlaybackPosition(el.currentTime);
      }
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

  /** Revoke a Blob URL if it exists. */
  function revokeUrl(ref) {
    if (ref.current) {
      URL.revokeObjectURL(ref.current);
      ref.current = null;
    }
  }

  // ── fetchAndStore ───────────────────────────────────────────────────
  /**
   * Fetch audio from /api/get-audio, convert base64 → Blob URL,
   * and store in the appropriate ref.
   */
  const fetchAndStore = useCallback(async (which) => {
    const fetchStart = performance.now();
    const res = await fetch(`${API_BASE}/api/get-audio`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ which }),
    });

    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail ?? detail; } catch (_) {}
      throw new Error(`get-audio (${which}) failed: ${detail}`);
    }

    const { audio_base64 } = await res.json();
    const fetchTime = performance.now() - fetchStart;
    if (!audio_base64) {
      throw new Error(`get-audio (${which}): no audio_base64 in response`);
    }

    // Base64 → Uint8Array → Blob → URL
    const decodeStart = performance.now();
    const binary = atob(audio_base64);
    const bytes  = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const blob = new Blob([bytes], { type: 'audio/wav' });
    const url  = URL.createObjectURL(blob);
    const decodeTime = performance.now() - decodeStart;

    console.log(`%c=== AUDIO FETCH (${which}) ===`, 'color: #4EDE83; font-weight: bold');
    console.log(`  Fetch + JSON:    ${fetchTime.toFixed(1)} ms`);
    console.log(`  Base64 decode:   ${decodeTime.toFixed(1)} ms`);
    console.log(`  TOTAL:           ${(performance.now() - fetchStart).toFixed(1)} ms`);

    // Store URL (revoke old one first)
    if (which === 'original') {
      revokeUrl(originalUrlRef);
      originalUrlRef.current = url;
    } else {
      revokeUrl(processedUrlRef);
      processedUrlRef.current = url;
    }

    // If this is the active side, load it into the audio element
    if (which === activeBufferRef.current) {
      const el = getAudioEl();
      el.src = url;
      el.load();
    }
  }, []);

  // ── Public API ─────────────────────────────────────────────────────

  const loadOriginal  = useCallback(() => fetchAndStore('original'),  [fetchAndStore]);
  const loadProcessed = useCallback(() => fetchAndStore('processed'), [fetchAndStore]);

  /** Load processed audio directly from a temp filename (skips base64). */
  const loadProcessedFromFile = useCallback((filename) => {
    const loadStart = performance.now();
    const url = `${API_BASE}/api/audio-file/${filename}`;

    revokeUrl(processedUrlRef);
    processedUrlRef.current = url;

    if (activeBufferRef.current === 'processed') {
      const el = getAudioEl();
      el.src = url;
      el.load();
    }

    console.log(`%c=== AUDIO LOAD (direct file) ===`, 'color: #4EDE83; font-weight: bold');
    console.log(`  URL set in: ${(performance.now() - loadStart).toFixed(1)} ms`);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Start or resume playback. */
  const play = useCallback(() => {
    const playStart = performance.now();
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
      const totalPlay = performance.now() - playStart;
      console.log(`%c=== PLAYBACK START ===`, 'color: #ffb340; font-weight: bold');
      console.log(`  Cached: ${wasCached}`);
      console.log(`  Time to play: ${totalPlay.toFixed(1)} ms`);
    }).catch((err) => {
      console.warn('useAudioPlayer: play() rejected:', err.message);
    });
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
    setPlaybackPosition(0);
    cancelRaf();
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
    setPlaybackPosition(0);
    setDuration(0);
    cancelRaf();
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
    pause: stop,   // pause = stop for our ■ model (stop-to-beginning)
    stop,
    reset,
    loadOriginal,
    loadProcessed,
    loadProcessedFromFile,
    switchBuffer,
    isPlaying,
    playbackPosition,
    duration,
  };
}
