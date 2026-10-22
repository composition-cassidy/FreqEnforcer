# FreqEnforcer profiling baseline

Measured 2026-10-22 on branch `perf-regression-baseline` before any refactoring.
No DSP code was changed. Reproduce with:

```bash
python tests/profiling/profile_baseline.py all
```

Raw JSON and `.prof` files are written to `tests/profiling/out/` (gitignored).

**Machine:** Intel Core i7-13700KF (24 threads), 128 GB RAM, Windows 11 Pro 26200.
**Software:** Python 3.14.2, numpy 2.3.5, scipy 1.16.3, pyworld 0.3.5,
praat-parselmouth 0.4.7, pylibrb 0.1.2, stftpitchshift 2.0. Backend exe built
2026-03-30 (`build-backend/freqenforcer-backend/`).
**Input:** `test_10s_C4.wav` (10 s, 44.1 kHz mono). Target F4 (+5 st) unless
noted. Multisample uses `test_2s_C4.wav`.
**Noise:** repeated runs vary by roughly ±5 % (HNM up to ±15 %). Treat differences
under 10 % as noise.

## Method

| Part | How |
|---|---|
| (a) startup | Spawn the backend, poll `GET /health` every 10 ms, time to first 200. One first run plus 5 repeats, both binaries. All runs are *warm disk cache*; a true cold boot needs a reboot and was not measured. `python -X importtime` gives the import breakdown. |
| (b) `/process` e2e | Real `python server/main.py` on port 8765 with httpx: `POST /api/load-audio`, then per mode one first + 3 warm `POST /api/process` + `GET /api/audio-file/{name}` (what the renderer does). Server-reported `timings` give the DSP vs serialization split. |
| (c) DSP only | Each pitch function called directly in-process (same args as `_run_pipeline`). Wall = median of 3, then one cProfile'd run. Plus two full `_run_pipeline` runs including the temp WAV write and waveform peaks. |
| (d) multisample | 24 notes C3–B4, world_hard, looping on. Wall clock of the real `/api/render-multisample` SSE stream, plus a cProfile'd in-process replica of the endpoint's per-note loop. |
| headroom | Harness-only vectorised reimplementations of the two hottest Python loops (results checked with `allclose`), to size the interpreter overhead. |

**Attribution.** CPython 3.14's cProfile does not see calls into Cython
(pyworld) or nanobind (pylibrb) functions; it books their time onto the
calling Python frame. It also sometimes drops or double-books events. The
harness therefore wraps every native entry point at runtime: `pyworld.{dio,
harvest, stonemask, cheaptrick, d4c, synthesize}`, `parselmouth.praat.call`,
pylibrb `RubberBandStretcher` methods, `stftpitchshift.vocoder.{encode,decode}`,
`soundfile.{read,write}` and `soxr.resample`. Each wrapper is a timing
trampoline, and those timers give the native buckets exactly. The remaining wall
time is split between *Python glue*, *numpy/scipy* and *HTTP/IO* in the
proportions cProfile reports for pure-Python frames. In every run, profiled wall
minus native minus cProfile Python time is within ±0.03 s.

**Caveat on "Python glue".** cProfile cannot see numpy *operator* calls
(`a * b`, `np.dot` in a loop body). Their cost is booked to the Python function
running the loop. The "Python glue" column therefore means *time in Python frames*:
interpreter overhead plus inline numpy array ops. The headroom section below
splits the two for the hot spots that matter.

## Breakdown: % of wall time

| Scenario | Wall (s) | Python glue | numpy/scipy | pyworld | parselmouth | pylibrb | HTTP/IO | startup | other 3rd-party |
|---|---|---|---|---|---|---|---|---|---|
| (a) start, `python server/main.py` (warm-cache median) | 1.60 | 2 | 44 | – | – | – | 21 | 33 | – |
| (a) start, PyInstaller exe (warm-cache median)¹ | 0.90 | – | – | – | – | – | – | 100 | – |
| (b) `/process` world_hard, first call (WORLD cache miss) + audio GET | 2.59 | 1 | 1 | 97 | – | – | 2 | – | – |
| (b) `/process` world_hard, warm (cache hit) + audio GET | 1.33 | – | – | 98 | – | – | 2 | – | – |
| (c) DSP only: world_hard | 1.41 | – | – | 100 | – | – | – | – | – |
| (c) DSP only: world_formant (+200 c) | 1.45 | 2 | 1 | 97 | – | – | – | – | – |
| (c) DSP only: world_soft | 1.53 | 3 | 6 | 91 | – | – | – | – | – |
| (c) DSP only: world_vt | 1.57 | 6 | 7 | 87 | – | – | – | – | – |
| (c) DSP only: world_hnm | 2.80 | 49 | 12 | 39 | – | – | – | – | – |
| (c) DSP only: praat_soft | 0.14 | 4 | 1 | – | 95 | – | – | – | – |
| (c) DSP only: sine_spectral | 1.76 | 81 | 19 | – | – | – | – | – | – |
| (c) DSP only: stft_pitchshift | 2.71 | 78 | 14 | – | – | – | – | – | 7² |
| (c) full pipeline: world_hard, cold WORLD cache | 2.42 | 1 | 1 | 98 | – | – | – | – | – |
| (c) full pipeline: world_soft + clean 50 % + Rubber Band ×1.5 + breath 2.0 + limiter | 6.39 | 4 | 4 | 86 | – | 6 | – | – | – |
| (d) multisample, 24 notes, in-process | 7.25 | 6 | 9 | 83 | – | – | 1 | – | – |
| (d) multisample, 24 notes via `/api/render-multisample` | 7.08 | 6 | 10 | 85 | – | – | 1 | – | – |

"–" = under 0.5 %. ¹ The frozen exe can't be introspected; it is reported as
all startup. ² stftpitchshift encode/decode.

How the rows were built:
- (a) python: `-X importtime` gives numpy+scipy 0.70 s (scipy alone 0.52 s),
  fastapi/pydantic/uvicorn/starlette/soundfile 0.34 s, `server.*` 0.03 s and
  other stdlib 0.23 s. The remaining 0.30 s is interpreter boot plus uvicorn
  startup. The stdlib share and that remainder make up the startup column.
  pyworld and parselmouth are imported lazily on first use, not at startup.
- (b) the server-side DSP part is split like the matching (c) row. HTTP/IO is
  client e2e minus server DSP wall: JSON encode/decode, socket, the 0.9 MB
  temp WAV write and its GET.

## (a) Startup

| Backend | First run (s) | Warm median of 5 (s) |
|---|---|---|
| `python server/main.py` | 1.91 | 1.60 |
| PyInstaller exe (onedir) | 1.67 | 0.90 |

The exe is faster than source once the disk cache is warm: no site-packages
scan, and bytecode comes precompiled from the PYZ. Its first run pays to page in
the 164 MB `_internal/`. The first `/process` adds lazy imports and pyworld's
first call. The app hides part of this behind the splash screen. `/api/warmup`
exists for this but is never called.

## (b) `/process` end-to-end (10 s input)

| mode | first `/process` (s) | warm e2e incl. audio GET (s) | server DSP (s) | serialize (ms) | HTTP+JSON+GET overhead (ms) | JSON bytes | WAV bytes |
|---|---|---|---|---|---|---|---|
| world_hard | 2.57 | 1.33 | 1.30 | 9 | 30 | 227,643 | 882,484 |
| world_soft | 1.43 | 1.44 | 1.41 | 9 | 29 | 227,648 | 882,484 |
| world_vt | 1.48 | 1.49 | 1.46 | 10 | 31 | 227,680 | 882,484 |
| world_hnm | 2.70 | 2.72 | 2.69 | 9 | 30 | 228,748 | 880,046 |
| praat_soft | 0.21 | 0.19 | 0.16 | 9 | 30 | 226,748 | 882,044 |
| sine_spectral | 1.79 | 1.80 | 1.77 | 9 | 31 | 224,298 | 882,044 |
| stft_pitchshift | 2.73 | 2.74 | 2.71 | 9 | 31 | 227,254 | 882,044 |

- HTTP, JSON, the temp WAV write and the audio GET cost **about 30 ms per call,
  1–15 % of a request**. Moving off HTTP (IPC, shared memory) would save at most
  those 30 ms.
- The first world_hard call costs 2.57 s versus 1.33 s warm. The 1.12 s
  difference is the WORLD precompute (`dio`+`stonemask`+`cheaptrick`+`d4c`) in
  `_run_pipeline` step 0. Only its `f0`/`timeaxis` are reused; its `sp`/`ap`
  are thrown away (see ARCHITECTURE.md, dead code #1). About 1 s of the first
  call is wasted.
- `/api/load-audio` takes 1.30 s for the 10 s file. **1.28 s of that is pitch
  detection** (in-house pYIN), the file read is 4 ms and peaks are 4 ms.

## (c) DSP only, inside pyworld

world_hard on 10 s (wrapped timers): `d4c` 0.87 s · `synthesize` 0.30 s ·
`cheaptrick` 0.12 s · `dio` 0.11 s · `stonemask` 0.03 s. **D4C (aperiodicity)
alone is about 60 % of every WORLD mode.** `apply_breathiness` runs a fresh
`harvest` (1.3 s) + `cheaptrick` + `d4c` + `synthesize`, which is why the heavy
chain is 6.4 s.

Python-frame hot spots (cProfile self time, 10 s input):

| Function | Self (s) | Used by | Nature |
|---|---|---|---|
| `pitch_yin._difference_function` | 0.92 | load-audio, sine_spectral, stft_pitchshift, tdpsola | Python loop over 882 lags per frame, one tiny `np.dot` each |
| `autotuner._lanczos3_resample` | 0.78 | stft_pitchshift | vectorised per frame, called per STFT frame (small-array overhead) |
| `hnm_synth.hnm_synthesize` | 1.27 | world_hnm | per 5 ms frame: `cos(outer(f, t))`, 63 harmonics × 2048 samples |
| `pitch_yin._absolute_threshold` | 0.28 | as pYIN | scalar Python loop, 50 thresholds × lags × frames |
| `pitch_yin._cmnd` | 0.16 | as pYIN | scalar Python loop |
| `loop_crossfade.find_loop_by_template_matching` | 0.24 (24 notes) | multisample | numpy correlation search |

## (d) 24-note multisample (2 s source, C3–B4, loops on)

7.1–7.3 s total, about 0.30 s per note, the same in-process and over HTTP/SSE
(so HTTP costs nothing here). pyworld takes 83–85 %. Every note re-runs
`cheaptrick` and `d4c` on the **same source audio with the same analysis F0**:
world_hard's default `force` voicing interpolates F0 independently of the
target. Only `synthesize` depends on the note. From the per-function split, about
**two thirds of the render repeats identical analysis**.

## Headroom: interpreter overhead vs numpy work

| Hot spot | Shipped code | Harness-only vectorised numpy | Speed-up | Max abs error |
|---|---|---|---|---|
| pYIN difference function + CMND (858 frames × 882 lags) | 0.98 s | 0.076 s | **13×** | 4e-14 |
| HNM harmonic kernel (`cos(outer)` + `dot`, 63 harmonics × 2048 samples) | 0.6–0.8 ms/frame × 2001 frames = 1.2–1.6 s | n/a (already vectorised) | – | – |

- pYIN is almost all interpreter overhead. A batched FFT autocorrelation in plain
  numpy removes about 92 % of it, with no Rust needed. The threshold scan
  (`_absolute_threshold`, 0.28 s) vectorises the same way.
- The HNM kernel accounts for nearly all of `hnm_synthesize`'s self time, so
  HNM is bound by numpy **transcendental throughput**, not the interpreter. The
  fix is algorithmic: a phasor recurrence or IFFT synthesis instead of 129 k
  `cos()` per frame. A native kernel would help most here, but an algorithmic
  numpy change gets most of the gain.

## After the backend cleanup (same machine, 2026-10-22)

Measured after commits a7c6176..8d28656 (librosa removal, dynamic port,
modes refactor, parallel multisample, repo hygiene). DSP output is unchanged:
all golden cases are bit-identical.

| Metric | Before | After |
|---|---|---|
| Backend bundle, `npm run build:backend` | **broken** (fails: `--add-data` resolved against `--specpath`); 434.7 MB / 1,900 files with the paths fixed (librosa + numba + llvmlite + PyQt6 + sklearn pulled in by `--collect-all librosa`) | 191.8 MB / 904 files (`scripts/build_backend.py`) |
| Backend bundle, `scripts/build.bat` (shipped) | 187.7 MB / 267 files (Mar 30 build, already librosa-free) | 191.8 MB / 904 files (same script now; +4 MB / +637 small files are packages installed since March, e.g. tzdata, watchfiles) |
| Installer / portable zip | 153.4 MB / 210.3 MB | 156.2 MB / 213.4 MB |
| Cold start, exe, warm-cache median of 5 | 0.90 s | 0.88 s |
| Cold start, exe, first launch after a fresh build | 5.6–5.8 s (new binary is scanned on first run) | 5.2 s (same effect) |
| Cold start, `python server/main.py` | 1.60 s | 1.60 s |
| 24-note multisample via HTTP, frozen exe | 12.24 s (serial) | **2.94 s** (23 workers) |
| 24-note multisample via HTTP, `python server/main.py` | 7.08 s | 4.42 s |
| 24-note multisample from the packaged app's renderer | – | 2.93 s |

Notes:
- Removing librosa does not change cold start. It was never imported at
  startup, so the win is bundle size only, on the npm build path.
- Multisample speed-up is bounded by pool start-up. Workers are spawned one at
  a time on Windows (~0.25 s each) and each imports numpy/scipy/pyworld, so
  24 notes at ~0.3 s/note finish in ~3 s on 24 threads.
- The serial frozen exe (12.2 s) was slower than serial `python` (7.1 s) for
  the same work. Not investigated; it doesn't matter with the pool, but it
  suggests the bundled numpy/BLAS threading behaves differently.

## Verdict

1. **WORLD is where the time goes.** pyworld's C++ (mostly `d4c`) is 87–100 % of
   every WORLD mode, 98 % of a real `/process` call and 83–85 % of a multisample
   render. Python glue is 0–6 % there, HTTP about 30 ms per call (≤2 %), and startup
   0.9 s (exe).
2. **The biggest wins are algorithmic, not language.** Drop the unused `sp`/`ap`
   precompute (−1 s on the first call). Cache `cheaptrick`/`d4c` per source and
   analysis F0 so a multisample analyses once instead of 24 times (≈−65 %).
   Vectorise pYIN (13×; most of the 1.3 s file-load and about 1 s of
   sine/stft modes).
3. **The Python-bound modes are sine_spectral (81 %), stft_pitchshift (78 %) and
   world_hnm (49 %)**, but their cost is concentrated in 3–4 functions: the pYIN
   loops, Lanczos per frame and the HNM cos kernel. numpy batching or algorithm
   changes cover them.
4. **A Rust port would not meaningfully help.** Porting the glue saves at most
   about 6 % on the default paths. Re-implementing WORLD in Rust would race
   already-compiled C++ (≈1×). Only HNM and Lanczos could gain from a native
   kernel, and only after the algorithmic fixes above.
5. **Do this first:** remove redundant WORLD analysis, cache analysis across
   multisample notes, vectorise pYIN. Re-measure with this harness, using
   `pytest tests/` to guard behaviour. Reconsider targeted native kernels
   (Rust/PyO3 or Cython) only for HNM if it is still hot afterwards.
