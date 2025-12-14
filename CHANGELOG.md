# Changelog

## Unreleased

### Added
- Cleanliness harmonic isolation processing with a full-band harmonic mask.
- Cleanliness Advanced Mode toggle.
  - When Advanced Mode is off, cleanup parameters are auto-driven by the Cleanliness Amount.
  - When Advanced Mode is on, manual Low Cut and High Shelf controls are available.
- Low Cut cleanup stage (sub removal).
- High Shelf cleanup stage (high-end noise shaping).
- Sample-rate aware shelf automation using Nyquist.
- `tools/make_ico.py` helper to regenerate `spartan_tuner/ICON.ico` from `spartan_tuner/ICON.png`.

### Changed
- Cleanliness default behavior no longer hard-bypasses high frequencies; processing now covers the full spectrum by default.

### Fixed
- Cleanliness at very low values (e.g. 1%) no longer removes all high frequencies (mask generation now preserves harmonics up to Nyquist).
- Advanced Mode UI now hides advanced controls when not enabled.
