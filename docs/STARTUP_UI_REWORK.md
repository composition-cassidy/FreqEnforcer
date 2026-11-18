# Startup and UI rework: before / after

Measured 2026-11-18 on the packaged app (`dist-electron/win-unpacked`), same
machine as PROFILE.md (i7-13700KF, 24 threads, Windows 11). "Before" is HEAD
`46d975e` built the same way. Warm disk cache; the median of runs 2..n is
reported (run 1 is the first launch).

Reproduce:

```
node tests/profiling/startup_bench.mjs --exe dist-electron/win-unpacked/FreqEnforcer.exe --runs 7 --label idle
node tests/profiling/startup_bench.mjs --exe dist-electron/win-unpacked/FreqEnforcer.exe --runs 7 --label open --open tests/fixtures/test_2s_C4.wav
node tests/profiling/startup_bench.mjs --exe dist-electron/win-unpacked/FreqEnforcer.exe --runs 6 --label play --open tests/fixtures/test_10s_C4.wav
py -3.14 tests/profiling/backend_start_bench.py source 6
node tests/profiling/ui_shots.mjs --outdir docs/screenshots
```

The benchmark launches the exe with its own `--user-data-dir` and a DevTools
port, so an installed copy that is already running is not touched.

## Startup (ms from launch)

| | before | after |
|---|---|---|
| first window on screen | 219 (splash) | 177 (main window, no splash) |
| main window visible | 1,263 | **275** |
| full UI shell rendered | 1,350 | **382** |
| engine ready (a file can be opened) | 1,350 | **817** |
| `--fe-open` file loaded (2 s sample) | 1,716 | **1,317** |
| first processed result (2 s sample) | 2,336 | **1,911** |
| backend alone, spawn → `/health` (Python 3.14, source) | 1,642 | **1,141** |

## Memory (idle, after startup, whole process tree)

| | before | after |
|---|---|---|
| private (committed) memory | 1,865 MB | **384 MB** |
| of which the Python backend | ~1,650 MB | ~135 MB |
| working set | 533 MB | 515 MB |
| processes | 5 | 5 |

The backend's 1.5 GB came from numpy and scipy each starting a 24-thread
OpenBLAS pool that commits its buffers up front. Every multisample worker
paid that again.

## Playback, 2 s of a 10 s sample (renderer, CDP Performance metrics)

| | before | after |
|---|---|---|
| playhead / time readout update rate | 15 Hz (React state) | every frame (~146 fps here); readout text 20 Hz |
| script time | 41 ms | **11 ms** |
| task time | 76 ms | 64 ms |
| style recalcs / layouts | 1 / 30 | 37 / 37 |
| React re-renders | 30 (whole app) | 0 |

## What changed

**Startup**
- Electron spawns the backend at process start and opens the main window in
  parallel. The splash window is gone (it was a second renderer process with
  a bouncy, navy-tinted animation). The port comes over IPC (`backend:url`);
  the renderer polls `/health` with a 20 ms → 250 ms backoff instead of the
  main process polling every 500 ms.
- The UI renders immediately. The title bar shows "Starting the audio
  engine…" (or the failure with Retry, which restarts the backend). A file
  opened or dropped before the engine is up loads as soon as it is.
- Backend: `OPENBLAS_NUM_THREADS=1` (the DSP only uses BLAS for vector dot
  products); `server.audio.sinusoidal`, which no request uses but which
  imported all of `scipy.signal` (~0.5 s), is no longer pre-imported; the
  load path (`pitch_yin` → `scipy.ndimage`) is imported in a background thread
  once the server is listening.
- Non-English locales are separate chunks loaded on demand (main bundle 298 →
  272 KB).

**UI**
- Pitch view: piano-roll grid hierarchy (accidental rows shaded, C lines
  strongest, natural-note lines, target dashed on top), major/minor time grid
  that never draws lines closer than 6 px, labels that thin out with zoom and
  always show note names.
- Playhead on its own overlay canvas, driven by one rAF loop from the audio
  element's time; playback never re-renders React or repaints the waveform.
- Contrast floor in all themes: text ≥ 4.5:1, control boundaries and octave
  lines ≥ 3:1 (new `--line-ctl`, `--fg-off` for disabled).
- New high-contrast theme, UI scale preference (100–200 %, clamped to what
  fits the display; frame zoom so canvases stay sharp), and a "UI animations"
  switch that also follows the OS reduced-motion setting.
- Sliders fill from their reference value (centre for bipolar controls,
  1.00× for stretch).
- Motion: progress bars animate `transform` instead of `width`; tooltip fade
  and fold-chevron rotation removed; nothing in the edit loop animates.
- Hit areas ≥ 24 px (zoom buttons, back, toast close); true minus signs in
  every signed readout; themed scrollbars and selection.
- The harmonic-pane splitter drags 1:1 without re-rendering the app.

## Tests run

- `pytest tests/` with `OPENBLAS_NUM_THREADS=1`: 221 passed, every case
  max |diff| 0.000 (the BLAS cap does not change DSP output).
- `tests/smoke_backend.py` against the rebuilt backend exe: all 7 pitch modes,
  2 stretch methods and a 4-note multisample OK.
- Startup benchmark: 7 runs idle, 7 with a file, 6 with playback, both builds.
- Frame health: animation frames at full rate at 100 % and 150 % UI scale.

## Known limits

- Timings are warm-cache; a cold boot after a reboot was not measured.
- The 200 % UI scale is only reachable on displays with at least
  2200 × 1400 DIP of work area; smaller screens clamp it.
- Calling `webFrame.setZoomFactor` from the preload while the page loads
  stopped all animation frames on Electron 41, so zoom is applied from the
  main process (`webContents.setZoomFactor`) and re-asserted after each load.

## Dead-code pass (same day)

Removed code and calls nothing in the app used (list in ARCHITECTURE.md,
"Dead / duplicated code"). Measured on the packaged app, 10 s sample opened
with `--fe-open`, median of runs 2–6:

| | after rework | after dead-code pass |
|---|---|---|
| open → first processed result | 5,211 ms | **4,147 ms** |
| working set | 683 MB | 610 MB |
| `app.asar` | 19.9 MB (10,456 node_modules files) | **354 KB** |
| backend bundle | 938 files | 857 files |

The ~1 s is the WORLD CheapTrick + D4C precompute that no mode read. Tests:
221/221 golden cases bit-identical, backend smoke test OK, and an in-app
check that the original plays from its streamed temp WAV, the loop-finder
sliders no longer trigger `/process`, and a formant change still does.
