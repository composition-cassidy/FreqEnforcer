// Note names, MIDI, frequency and display formatting helpers.

export const NOTE_NAMES_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
export const NOTE_NAMES_FLAT  = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
const BLACK = new Set([1, 3, 6, 8, 10]);

const NOTE_TO_PC = {
  C: 0, 'B#': 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, Fb: 4, 'E#': 5, F: 5,
  'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11, Cb: 11,
};

export function noteNameToPC(note) { return NOTE_TO_PC[note] ?? null; }
export function isBlackKey(pc) { return BLACK.has(pc % 12); }
export function toMidi(octave, pc) { return (octave + 1) * 12 + pc; }
export function midiToFreq(midi) { return 440 * Math.pow(2, (midi - 69) / 12); }
export function noteToFreq(note, octave) { return midiToFreq(toMidi(octave, noteNameToPC(note) ?? 0)); }

/** Backend-style note name (always sharps): "C#4". */
export function noteLabel(note, octave) { return `${note}${octave}`; }

/** Pitch class index -> display name in the user's notation. */
export function pcName(pc, notation = 'sharps') {
  const names = notation === 'flats' ? NOTE_NAMES_FLAT : NOTE_NAMES_SHARP;
  return names[((pc % 12) + 12) % 12].replace('#', '♯').replace('b', '♭');
}

/** MIDI -> { note (sharp name), octave }. */
export function midiToNote(midi) {
  return { note: NOTE_NAMES_SHARP[((midi % 12) + 12) % 12], octave: Math.floor(midi / 12) - 1 };
}

/** "F#3" / "Gb3" / "f#3" -> { note (sharp name), octave } or null. */
export function parseNoteName(str) {
  const m = /^([A-Ga-g])([#b]?)(-?\d)$/.exec(str ?? '');
  if (!m) return null;
  const pc = NOTE_TO_PC[m[1].toUpperCase() + m[2]];
  if (pc == null) return null;
  return { note: NOTE_NAMES_SHARP[pc], octave: parseInt(m[3], 10) };
}

/** Hz -> semitones relative to refHz (float). */
export function hzToSemitones(hz, refHz) { return 12 * Math.log2(hz / refHz); }

export function formatHz(hz, digits = 2) {
  return hz == null || !Number.isFinite(hz) ? '—' : hz.toFixed(digits);
}
export function formatCents(cents) {
  if (cents == null || !Number.isFinite(cents)) return '—';
  return `${cents > 0 ? '+' : ''}${cents.toFixed(1)}`;
}
/** Seconds -> "m:ss.mmm" */
export function formatTime(s) {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}
export function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
