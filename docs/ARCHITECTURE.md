# FreqEnforcer architecture (v2.0.x, Electron port)

Snapshot of the code as of branch `perf-regression-baseline` (based on `31ccb9b`
plus the uncommitted working tree at the time). This is the reference for the
upcoming refactor; nothing listed under "Dead / duplicated code" has been removed.

## Processes and data flow

```
┌───────────────────────────── Electron main (electron/main.js) ─────────────────────────────┐
│ splash window → spawn backend exe (resources/backend/freqenforcer-backend.exe)             │
│ polls GET /health, then opens main window. IPC: window controls, open/save/dir dialogs,    │
│ theme storage (preload.js exposes window.electronAPI)                                      │
└──────────────┬──────────────────────────────────────────────────────────────────────────────┘
               │ spawn                                     ▲ file paths via native dialogs
               ▼                                           │
┌──────── FastAPI backend (server/main.py, 127.0.0.1:8765) ────────┐    ┌──── React renderer (src/) ────┐
│ uvicorn, single process; one global AppState (server/state.py):  │◄───┤ fetch() JSON over HTTP         │
│ original_audio (float32, 44.1 kHz mono), processed_audio,        │    │ EventSource for SSE progress   │
│ detected_pitch, world_cache, loop points, processing_token       │───►│ <audio> plays temp WAV via     │
│ DSP runs in asyncio.to_thread / a daemon thread                  │    │ /api/audio-file/{name}         │
└──────────────────────────────────────────────────────────────────┘    └────────────────────────────────┘
```

Typical session:

1. **Load**: renderer → `POST /api/load-audio {file_path}` (or multipart
   `/api/load-audio-upload` for drag-and-drop). `loader.load_audio` reads with
   soundfile, downmixes, resamples to 44.1 kHz with soxr, peak-limits to ±1.
   `pitch_detector.get_predominant_pitch` (in-house pYIN, `pitch_yin.py`) sets
   `state.detected_pitch`. Response carries 2000-bin waveform peaks. The
   renderer then pulls the original as base64 WAV via `POST /api/get-audio`.
2. **Process**: every settings change → `POST /api/process` (renderer
   debounces; `processing_token` cancels superseded jobs between stages). The
   renderer also holds an SSE stream on `GET /api/process-progress`.
   `_run_pipeline` (server/routes/audio.py) runs:
   0. WORLD analysis cache (`dio`→`stonemask`→`cheaptrick`→`d4c`) when a
      WORLD mode or breathiness is used, keyed by an md5 of the first 1000 samples
   1. pitch correction (mode table below)
   2. time stretch (`time_stretch.STRETCHERS`) if `stretch_factor != 1`
   3. smart low-cut (`cleanliness.compute_smart_lowcut` + `apply_low_cut`)
   4. cleanliness + HF rollback (`cleanliness.apply_cleanliness`, STFT harmonic mask)
   5. breathiness (`autotuner.apply_breathiness`, a fresh WORLD harvest+resynthesis)
   6. harmonic analysis (pre) → optional harmonic limiting → analysis (post)
      (`harmonic_limiter.py`)
   7. normalize (`normalizer.normalize_audio`, −0.1 dBFS)

   The result is written to a temp `fe_processed_*.wav` (PCM16). The JSON
   response carries peaks, harmonic analysis, timings and the temp filename. The
   renderer plays it from `GET /api/audio-file/{filename}`.
3. **Loop / export**: `/api/crossfade-loop` (template-matching loop finder in
   `loop_crossfade.py`, overwrites `processed_audio`), `/api/export` or
   `/api/quick-export` (PCM16 + `smpl` chunk with root note and loop points via
   `loader.set_wav_root_note`).
4. **Multisample**: `POST /api/render-multisample` streams SSE while a daemon
   thread calls `multisample.render_note_range`. That function renders notes
   in a `ProcessPoolExecutor` with `cpu_count - 1` workers, capped at the
   number of notes. The parent computes the WORLD F0 cache once
   (`_world_cache_for`) and hands each worker the source audio, settings and
   an F0-only cache through the pool initializer. Each worker runs
   `_run_pipeline` + optional `process_with_loop` + `save_audio` +
   `set_wav_root_note` per note. Progress events
   (`progress`/`current_note`/`notes_done`/`notes_total`) go out as notes
   finish and are mirrored to `/process-progress`; then `sfz_writer.write_sfz`
   runs. Workers exit when the backend process dies, and Electron kills the
   whole backend process tree on quit. A new `/process` call supersedes the
   token: pending notes are dropped and the stream ends with `cancelled`.
   `server/main.py` calls `multiprocessing.freeze_support()` so the frozen exe
   can start workers. `tests/test_multisample.py` checks that parallel output
   is byte-identical to the in-process path and to the `pipe_loop` golden.

## Endpoints

| Method | Path | Request | Response / effect | Used by frontend |
|---|---|---|---|---|
| GET | `/health` | – | `{status, version}` | yes (splash/startup) |
| POST | `/api/load-audio` | `{file_path}` (≤100 MB, must exist) | duration, sr, detected_pitch, waveform_peaks, peak/rms dB, timings; resets state | yes |
| POST | `/api/load-audio-upload` | multipart `file` (.wav/.mp3/.flac/.ogg/.aiff) | same as above + `uploaded_path` (temp file kept) | yes (drag-drop) |
| POST | `/api/process` | `ProcessRequest` (target_note, pitch_mode, pitch_amount, retune_speed_ms, preserve_vibrato, preserve_formants, formant_shift_cents, formant_shift_beta, stretch_factor, stretch_method, clean_lowcut_percent, cleanliness_percent, clean_hf_rollback_percent, breathiness, hf_bias, harmonic_limiter_enabled, harmonic_ceiling_offsets_db, harmonic_knee_db, harmonic_release_ms, normalize) | peaks, peak/rms dB, harmonic_analysis, duration, `audio_temp_path`/`_filename`, timings; 409 if superseded | yes |
| GET | `/api/process-progress` | – | SSE `{progress, stage}` (shared global queue, never closes) | yes |
| POST | `/api/get-audio` | `{which: original\|processed}` | base64 PCM16 WAV | yes (original) |
| GET | `/api/audio-file/{filename}` | only `fe_processed_*` / `fe_upload_*` in temp dir | WAV file | yes |
| POST | `/api/export` | `{output_path, target_note}` | writes PCM16 + smpl chunk | yes |
| POST | `/api/quick-export` | `{target_note, overwrite}` | writes `<src>_<note>_tuned.wav` next to source, or `{exists:true}` | yes |
| POST | `/api/crossfade-loop` | `{template_periods, min_loop_periods, crossfade_periods, f0_hz?}` | loop_start/end; replaces processed_audio | yes |
| POST | `/api/render-multisample` | note range + loop options + all ProcessRequest fields + `output_dir` | SSE progress → `{complete, output_dir, sfz_path, notes_rendered}` | yes |
| GET | `/api/stretch-methods` | – | static list of 7 stretch methods | **no** (frontend hard-codes its own list) |
| POST | `/api/warmup` | – | runs pitch detect, WORLD, WSOLA and cleanliness on 0.25 s of sine | **no** |

## Pitch modes

Each mode is a module in `server/audio/modes/<pitch_mode>.py` with the same
interface: `NAME`, `USES_WORLD_CACHE`, and `render(audio, sr, settings,
world_cache=None)`. `render` maps the `/api/process` settings onto the mode's
DSP function. `_run_pipeline` dispatches through
`modes.render_pitch_mode()`; unknown modes fall back to `world_hard`. Shared
code lives in `modes/_world.py` (input validation, DIO/StoneMask with cache,
CheapTrick/D4C, strict/force/dilate voicing, unvoiced F0 fill),
`modes/_retune.py` (soft-retune trajectory) and `modes/_dsp.py` (spectral
helpers). `server/audio/autotuner.py` keeps `apply_breathiness` and re-exports
the `autotune_*` functions for existing callers.

All modes take `target_note`. F0 targets are either flat (hard modes) or
smoothed in log2 space: a one-pole filter (`retune_speed_ms`), with the
vibrato residual re-added (`preserve_vibrato`) and `pitch_amount` blending.

| `pitch_mode` | Function (server/audio/modes/) | Analysis | Synthesis | Voicing used by app | Libraries |
|---|---|---|---|---|---|
| `world_hard` (default), `preserve_formants=true` | `autotune_to_note` | WORLD dio/stonemask (cached), cheaptrick, d4c | `pw.synthesize`, flat F0 | `force` (function default) | pyworld |
| `world_hard`, `preserve_formants=false` | `autotune_with_formant_shift(formant_shift_cents)` | same | `pw.synthesize` + per-frame envelope resample (`_shift_spectral_envelope`) | `force` | pyworld, numpy |
| `world_soft` | `autotune_soft_to_note` | same | `pw.synthesize` + `_repair_world_artifacts` | `strict` (hard-coded) | pyworld, scipy |
| `world_vt` | `autotune_world_vt(formant_shift_beta)` | same | freq-dependent envelope warp (`_warp_spectral_envelope_fdep`), `pw.synthesize`, repair | `strict` | pyworld, numpy |
| `world_hnm` | `autotune_world_vt(use_hnm=True, beta=0.2)` | same | `hnm_synth.hnm_synthesize` (per-frame harmonic + noise OLA, **unseeded `np.random`**), micro-RMS envelope transfer, repair | `strict` | pyworld (analysis only), numpy |
| `praat_soft` | `autotune_praat_soft_to_note` | Praat `To Manipulation` pitch tier | Praat PSOLA overlap-add resynthesis | n/a | parselmouth |
| `sine_spectral` | `autotune_sine_spectral` | in-house pYIN + scipy STFT + cepstral envelope (`sinusoidal.estimate_spectral_envelope`) | envelope × harmonic-excitation phase, ISTFT, RMS envelope match | n/a | numpy/scipy |
| `stft_pitchshift` | `autotune_stft_pitchshift` | in-house pYIN, zero-padded STFT | `stftpitchshift` vocoder encode/decode, Lanczos-3 resample, cepstral lifter, V/UV crossfade | n/a | stftpitchshift, numpy |

Voicing modes (`strict` / `force` / `dilate`) exist only on the four WORLD
functions: `strict` keeps unvoiced frames unvoiced, `force` makes every frame
voiced (F0 interpolated across gaps), `dilate` grows the voiced mask by
`dilation_frames` (3).

Time-stretch methods (`time_stretch.STRETCHERS`): `audiotsm_wsola` (default),
`audiotsm_ola`, `audiotsm_phasevocoder`, `rubberband_default_engine_faster`,
`rubberband_default_engine_finer`, `rubberband_percussive_engine_finer`
(pylibrb), `tdpsola` (in-house, pYIN marks).

## Regression and profiling harness

- `tests/golden/matrix.py`: render matrix (3 fixtures × 8 pitch modes × voicing
  where it applies × targets −7/+5/+12 semitones = 162 cases, plus 19 full-pipeline
  cases on `test_2s_C4.wav`, 181 in total). The `pipe_mode_*` cases send every
  `pitch_mode` through `_run_pipeline` dispatch and cover the formant-shift,
  `preserve_formants=false` and non-default-beta branches. Calls DSP functions directly and
  seeds `np.random` with 0 before each render. Targets are relative to the
  *detected* source note. All three fixtures detect as C4, including
  `test_10s_C4_Fs4_tuned.wav` (261.6 Hz), so every fixture renders F3/F4/C5.
  `world_formant` uses +200 cents so the formant-shift path is actually exercised.
- `tests/golden/render_golden.py`: writes float32 reference WAVs (Git LFS) and
  `manifest.json` (params, sha256 of float32 samples, RMS, peak, detected f0,
  env versions). Regenerate **only** for intentional DSP changes.
- `tests/test_regression.py`: `pytest tests/` re-renders every case. A case
  passes if max |diff| < 1e-4, or else if the relative spectral-flux difference
  is < 0.05 % (STFT 2048/512, Hann). The threshold is calibrated in the module
  docstring: a formant beta change from 0.10 to 0.12 scores 0.114 % and fails,
  while float32-level noise scores 0.000 % and passes. Length changes always
  fail. Prints a per-mode summary table, and checks that the manifest still
  matches the matrix and that librosa is never imported. On the reference
  machine all cases are bit-identical (max |diff| = 0). Runtime is about 4 min.
- `tests/profiling/profile_baseline.py`: see [PROFILE.md](PROFILE.md).

## Dead / duplicated code (found, **not deleted**)

### Wasted work on the hot path
1. **WORLD `sp`/`ap` precompute is unused.** `_run_pipeline` step 0 runs
   `cheaptrick` + `d4c` on the original audio and caches them, but every pitch
   function reads only `f0`/`timeaxis` from the cache and recomputes `sp`/`ap`
   with its own (interpolated) analysis F0. Breathiness is explicitly passed
   `world_cache=None`. That is one full cheaptrick + d4c per new audio, thrown
   away (see PROFILE.md for the cost). The md5 cache key also hashes only the
   first 1000 samples.
2. `harmonic_analysis_pre` runs on every `/process` call even when the limiter
   is off (needed for the UI meters, but worth knowing; it is a full STFT).
3. `_run_pipeline` computes `_t` for step 0 and never uses it.

### Duplicated code
4. *Resolved:* the voicing-mask selection (strict/force/dilate + `np.interp`
   fill) was copy-pasted 4×. It is now `modes/_world.voiced_masks` and
   `fill_unvoiced_f0`.
5. *Resolved:* the soft-retune F0 trajectory was copy-pasted 5× (soft, vt,
   praat, sine, stft). It is now `modes/_retune.retune_log2`. The one-pole
   smoother is still a per-frame Python loop (cheap; outputs unchanged).
6. *Resolved:* the WORLD input validation and DIO/StoneMask/CheapTrick/D4C
   analysis are now `modes/_world.py` helpers.
7. `ProcessRequest` and `RenderMultisampleRequest` duplicate all 20 processing
   fields and the `round_formant_cents` validator. `ProcessRequest` also has
   `stretch_positive` and `clean_range`, which the multisample request does not.
8. `/load-audio` and `/load-audio-upload` duplicate the state-reset and
   response-building block.
9. *Resolved:* `multisample.py::render_note_range` used to duplicate the
   endpoint's inline loop. It is now the one implementation, a parallel
   renderer (below), and the endpoint calls it.
10. Peak/RMS dB helpers exist twice: `routes/audio.py::_peak_db/_rms_db` and
    `normalizer.get_peak_db/get_rms_db` (the latter unused).
11. Two STFT implementations: `harmonic_limiter._centered_stft/_centered_istft`
    ("matching librosa defaults"), `autotuner._zp_stft/_zp_istft`, plus
    `scipy.signal.stft` in cleanliness and sine_spectral.
12. *Mostly resolved:* dual module identity. All modes now import
    `server.audio.*`; `sine_spectral` and `stft_pitchshift` used to import the
    bare `audio.*` package, which loaded two copies. The `spartan_tuner.*` /
    `utils.*` import fallbacks in `pitch_detector.py` are still there, and the
    PyInstaller `--add-data server\audio;audio` copy is now unused (kept for
    now).

### Unused or unreachable
13. `voicing_mode` is never exposed to the frontend; `dilate` and `strict`
    (for world_hard) are unreachable from the UI.
14. `autotune_to_note(preserve_formants=False)` branch is unreachable: the
    route sends `preserve_formants=False` to `autotune_with_formant_shift`.
15. `sinusoidal.py` (1270 lines): only `estimate_spectral_envelope` is used.
    `dft_anal`, `peak_detect`, `peak_interp`, `sine_tracking`,
    `sine_model_anal`, `harmonic_model_anal`, `sine_model_synth`,
    `gen_spec_sines`, `compute_residual_stft`, and the track-cleanup helpers are dead.
16. `dwp_writer.py` (`write_dwp`) is never imported.
17. `cleanliness.apply_high_shelf` (imported by the route but unused, see the
    "high shelf removed" comment) and `cleanliness.preview_cleanliness_mask` are unused.
18. `loader.set_wav_loop_points`, `pitch_detector.get_target_frequency`, and
    `server/utils/harmonic_cli.py` are unused.
19. `/api/stretch-methods` and `/api/warmup` are not called by the frontend.
20. The "docstring" in `apply_cleanliness` comes after an import statement, so
    it is a dead string expression, not a docstring. (The same problem in
    `autotune_to_note` and `autotune_with_formant_shift` was fixed when they
    moved to `modes/world_hard.py`.)

### Dependency and config drift
21. `requirements.txt` still lists **librosa** (the code no longer imports it;
    PyInstaller excludes it). It omits **stftpitchshift** and **soxr**, both
    required at runtime.
22. Default `stretch_method` is `audiotsm_wsola`. The shipped exe bundles
    audiotsm, but the current dev Python **does not have audiotsm installed**.
    `python server/main.py` fails any stretch with the default method, and
    rebuilding the exe from this env with `scripts/build.bat` would silently
    drop it.
23. `/api/warmup` comment says "librosa (pitch detection)"; it is in-house pYIN now.
24. `_progress_queue` is a module-level unbounded `asyncio.Queue` shared by all
    clients. Items pile up when no `/process-progress` listener is connected.
    Multisample now pushes one event per finished note instead of every
    pipeline stage of every note; worker processes push nothing.

### Behavioural oddities noticed while baselining (not changed)
- `hnm_synth.py` uses unseeded `np.random`, so `world_hnm` output differs on
  every call. Tests seed the global RNG to make it reproducible.
- `tdpsola` stretch ×1.5 on `test_2s_C4` produces output whose detected F0
  is ~120 Hz, not the ~349 Hz target (golden case `pipe_stretch_tdpsola`
  records this as-is).
- `apply_cleanliness` emits scipy's "NOLA condition failed" warning (its
  window/hop pair is not perfectly invertible).
- `test_10s_C4_Fs4_tuned.wav` is not at F#4: the app's own detector reads it
  as C4 (261.62 Hz, 0 cents). Its length is 441 220 samples, which matches a
  `world_*` output rather than the 441 000-sample source.
- Repeated analysis is the largest perf issue (see PROFILE.md). `cheaptrick`
  and `d4c` are recomputed for every multisample note, although with `force`
  voicing their inputs don't depend on the target note.
