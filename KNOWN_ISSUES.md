# FreqEnforcer v2.0.0 — Known Issues

## Functional Issues

- [Severity: Low] **Undo/Redo not implemented** — Ctrl+Z and Ctrl+Shift+Z are reserved but do nothing. Changing a setting cannot be reversed except by manually adjusting the control back.

- [Severity: Low] **Cleanliness DSP intentionally differs from PyQt6 v1** — The cleanliness system was redesigned for v2. The original high-shelf gain + Hz-based low-cut has been replaced with a percentage-based smart low-cut and HF rollback system. Output from cleanliness processing will not be sample-identical to the PyQt6 version; this is by design.

- [Severity: Low] **Detected pitch display requires backend** — If the Python backend is slow to start, the pitch detection result may not appear until after the first processing pass completes.

- [Severity: Low] **Stretch factor snap-to-1.0** — The stretch factor slider snaps to exactly 1.0 in a small deadband near center. Users who want values like 0.99x or 1.01x need to use the manual text input.

- [Severity: High] **`sine_spectral` lands on the wrong pitch** — Output pitch does not follow the target note. On the C4 test fixtures, targets F3 / F4 / C5 are detected at ~346 Hz / ~58 Hz / ~55 Hz. Recorded as-is in the golden regression references (`tests/golden`), so a fix will need regenerated references.

- [Severity: Medium] **TD-PSOLA stretch shifts pitch** — `tdpsola` at ×1.5 on a voice tuned to F4 (349 Hz) comes out detected at ~120 Hz.

- [Severity: Low] **`world_hnm` output is not repeatable** — The HNM synthesizer uses unseeded random phases and noise, so two renders of the same settings differ slightly. (The regression tests seed the RNG.)

## Visual Issues

- [Severity: Low] **Harmonic limiter spectrum may show stale nodes briefly** — After loading a new file, the harmonic limiter spectrum can briefly display the previous file's harmonic nodes until the first processing pass completes.

- [Severity: Low] **Waveform canvas does not anti-alias on very low-resolution displays** — On sub-1080p screens, the waveform blob edges may appear slightly jagged.

- [Severity: Low] **Theme editor color picker requires exact hex input for precise colors** — The native color picker provided by the browser may vary slightly in precision across operating systems.

## Platform-Specific

- [Windows] **DPI scaling above 150%** — At very high DPI scaling (175–200%), some fixed-size canvas elements (harmonic limiter, waveform) may appear smaller than intended. The app is optimized for 100–125% DPI.

- [Windows] **File paths with non-ASCII characters** — Unicode file paths (Japanese, Russian, Arabic, etc.) are generally supported but have not been exhaustively tested. If a load fails, try moving the file to a path with ASCII characters only.

## Limitations

- Multi-sample rendering runs notes in parallel on all but one CPU core (24 notes from a 2 s sample: ~3 s on a 24-thread CPU). Each worker uses ~75–100 MB of RAM, and long sources with high-quality stretch settings still take a while on low-core machines. Cancelling (by changing a setting) drops pending notes, but notes already in progress finish and are written.
- Crossfade loop quality depends heavily on the source material. Highly transient or non-periodic sounds (drums, one-shots) may not loop cleanly regardless of crossfade duration.
- The Python backend must be running for all audio processing, export, and detection features. The UI will load but show errors if the backend is not available.
- `world_hnm` and `sine_spectral` pitch modes are experimental and may produce artifacts on some source material, particularly at extreme pitch shifts (>±12 semitones).
- SFZ export is formatted for DirectWave (FL Studio). Compatibility with other samplers (Kontakt, HALion, etc.) has not been tested.
- Loop point embedding (smpl chunk) is only supported in WAV export. MP3/OGG/FLAC exports do not carry loop metadata.
- The app requires Python 3.11+ and all dependencies in `requirements.txt`. It is not self-contained — the Python environment must be set up separately before first launch.
