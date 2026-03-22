# Changelog

## Unreleased

## 1.1.0 - 2026-03-22

### Added
- **WORLD Vocal Tract** pitch mode — pitch-adaptive vocal tract modeling with frequency-dependent spectral envelope warping; F1/F2 shift naturally with pitch while F3+ remain fixed.
- **HNM (Harmonic + Noise Model) synthesizer** — replaces pw.synthesize() with explicit sinusoidal + shaped-noise synthesis for cleaner output; includes overlap-add with Hanning window and RMS normalization.
- **Sinusoidal analysis/synthesis engine** — clean-room implementation based on Serra (1989) and McAulay-Quatieri (1986) for deterministic + stochastic decomposition.
- **Custom Knob widget** — drag-to-adjust rotary knob with snap points, theme support, and double-click reset; used for Retune Speed and Preserve Vibrato.
- **Custom Slider widget** — horizontal/vertical slider with snap-to-zero, value labels, and theme support; replaces raw QSliders for Formant Shift, Stretch Factor, Cleanliness, Low Cut, and High Shelf.
- **Mini Piano widget** — compact single-octave keyboard for target note selection with sharp/flat notation support.
- **Preferences dialog** — consolidated preferences with tabs for general settings and theme editor access.
- **Sharp / Flat notation toggle** — note names can be displayed as sharps (C#) or flats (Db) throughout the UI and piano roll.
- **Formant Adapt (Vocal Tract Model) slider** — controls vocal tract adaptation strength in WORLD VT mode.
- Cleanliness harmonic isolation processing with a full-band harmonic mask.
- Cleanliness Advanced Mode toggle (auto-driven vs manual Low Cut / High Shelf).
- Low Cut cleanup stage (sub removal).
- High Shelf cleanup stage (high-end noise shaping).
- Sample-rate aware shelf automation using Nyquist.
- Double-click reset on Pitch Amount, Stretch Factor, and Cleanliness sliders.
- `tools/make_ico.py` helper to regenerate ICON.ico from ICON.png.

### Changed
- Settings panel redesigned: tabs removed, all controls on a single scrollable page with knobs and custom sliders.
- Cleanliness default behavior now covers the full spectrum (no longer hard-bypasses high frequencies).
- Piano roll supports both sharp and flat note names.

### Fixed
- Cleanliness at very low values (e.g. 1%) no longer removes all high frequencies.
- Advanced Mode UI now hides advanced controls when not enabled.
- WORLD vocoder artifact repair for cleaner output on pitch-shifted audio.
