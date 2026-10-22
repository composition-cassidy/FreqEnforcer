// Audio settings model: defaults, mode table and which controls each mode uses.
// Keys mirror the backend ProcessRequest (see hooks/useProcessing.js for the mapping).

export const DEFAULT_SETTINGS = Object.freeze({
  targetNote: 'C', octave: 4,
  pitch_mode: 'world_hard',
  pitch_amount: 1.0,          // 0-1
  retune_speed_ms: 40,
  preserve_vibrato: 1.0,      // 0-1
  formant_shift_cents: 0,
  formant_shift_beta: 0.10,   // 0-1
  voicing_mode: null,         // null = backend default for the mode
  normalize: false,
  stretch_method: 'audiotsm_wsola',
  stretch_factor: 1.0,
  cleanliness_percent: 0,
  clean_lowcut_percent: 0,
  clean_hf_rollback_percent: 0,
  breathiness: 1.0,
  hf_bias: 0.0,
  harmonic_limiter_enabled: false,
  harmonic_amount: 50,
  harmonic_ceiling_offsets_db: {},
  loop_template_periods: 6,
  loop_min_periods: 10,
  loop_crossfade_periods: 2,
});

// Order matches the 1-7 shortcuts and the Mode select.
export const PITCH_MODE_GROUPS = [
  { key: 'world',        modes: ['world_hard', 'world_soft', 'world_vt', 'world_hnm'] },
  { key: 'psola',        modes: ['praat_soft'] },
  { key: 'experimental', modes: ['sine_spectral', 'stft_pitchshift'] },
];
export const PITCH_MODES = PITCH_MODE_GROUPS.flatMap((g) => g.modes);

export const STRETCH_METHODS = [
  'audiotsm_wsola', 'audiotsm_ola', 'audiotsm_phasevocoder',
  'rubberband_default_engine_faster', 'rubberband_default_engine_finer',
  'rubberband_percussive_engine_finer', 'tdpsola',
];

// Per-mode control visibility.
const SOFT    = new Set(['world_soft', 'praat_soft', 'world_vt', 'world_hnm', 'sine_spectral', 'stft_pitchshift']);
const FORMANT = new Set(['world_hard', 'world_soft', 'sine_spectral', 'stft_pitchshift']);
const VT      = new Set(['world_vt', 'world_hnm']);

export const VOICING_MODES = ['strict', 'force', 'dilate'];
// Backend default when voicing_mode is null; undefined = mode has no voicing.
export const VOICING_DEFAULT = { world_hard: 'force', world_soft: 'strict', world_vt: 'strict', world_hnm: 'strict' };

export function modeCaps(mode) {
  return {
    soft:    SOFT.has(mode),
    formant: FORMANT.has(mode),
    vt:      VT.has(mode),
    voicing: VOICING_DEFAULT[mode] ?? null,
  };
}

// Settings that are "advanced": used for the "N active" badge.
export function countActiveAdvanced(s) {
  let n = 0;
  if (s.cleanliness_percent > 0) n++;
  if (s.clean_lowcut_percent > 0) n++;
  if (s.clean_hf_rollback_percent > 0) n++;
  if (Math.abs(s.breathiness - 1) > 1e-6) n++;
  if (s.hf_bias > 0) n++;
  if (s.harmonic_limiter_enabled) n++;
  return n;
}

export const DEFAULT_PREFS = Object.freeze({
  theme: 'dark',          // 'dark' | 'light'
  language: 'en',
  notation: 'sharps',     // 'sharps' | 'flats'
  performance_mode: false,
  warmup: true,
});

export const LANGUAGES = ['en', 'es', 'pt_BR', 'ja', 'ru'];
