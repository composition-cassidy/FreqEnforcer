# FreqEnforcer

FreqEnforcer is a small desktop tool for pitch-correcting monophonic samples to a target note, tailored towards sample editing for Sparta Remixers aswell as YTPMVs.

## Features

- Load audio files:(`.wav`, `.mp3`, `.flac`, `.ogg` supported)
- Detect predominant pitch
- Pitch-correct to a selected target note
- Optional time-stretch and normalization
- Cleanliness (harmonic isolation)
  - Amount slider removes non-harmonic content between harmonic lines
  - Advanced Mode exposes manual cleanup controls (Low Cut + High Shelf)
  - When Advanced Mode is off, Low Cut / High Shelf are auto-driven by Amount
- Export processed audio to WAV
  - Exported WAVs are tagged with sampler metadata (`smpl` + `inst` RIFF chunks) so many DAWs/samplers can auto-detect the **root note**
- **Harmonic limiter** (new in v1.2.0)
  - Per-harmonic ceiling control with interactive spectral view
  - Drag nodes to cap individual harmonics, or use Compression slider for automated limiting
  - Tame harsh overtones and balance harmonic balance before export
- **Breathiness + HF Bias** (new in v1.2.0)
  - Breathiness slider: adjust aperiodic/noise content (0 = cleaner, 1 = original, 2+ = more breathy)
  - HF Bias: bias the shaping toward high frequencies (0 = uniform, 1 = mainly high-freq)

## Requirements

- Windows 10/11
- Python 3.11+

## Run from source

From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r spartan_tuner\requirements.txt

.\.venv\Scripts\python.exe spartan_tuner\main.py
```

Optional startup overrides (e.g. `--breathiness 0.8 --hf-bias 0.2 --harmonic-ceiling "1:-3,2:-2" --harmonic-amount 50`) apply breathiness, HF bias, or harmonic limiter settings before the UI loads.

## Build (Windows)

### Generate ICON.ico (if needed)

From the repo root:

```powershell
py -3 tools\make_ico.py
```

### Build the standalone app (PyInstaller)

```powershell
py -3.14 -m PyInstaller --clean -y FreqEnforcer.spec
```

The output EXE is under `dist\FreqEnforcer\FreqEnforcer.exe`.

### Build the installer (Inno Setup)

After building the standalone app, compile the installer:

```powershell
iscc FreqEnforcer.iss
```

The installer is written to `installer\FreqEnforcer-Setup-1.2.0.exe`.

### Release artifacts

- **Portable**: `dist\FreqEnforcer\` — copy this folder anywhere; run `FreqEnforcer.exe` (no install)
- **Installer**: `installer\FreqEnforcer-Setup-1.2.0.exe` — installs to Program Files, Start Menu shortcut, optional desktop icon

### How to try them

1) Launch the app.
2) Drag & drop one of the files from `spartan_tuner\test\` into the window.
3) Toggle between original/processed where applicable and export.
4) (Optional) Drag the exported WAV into your DAW sampler.
   - The export includes WAV sampler metadata (`smpl` + `inst`) so many samplers can auto-set the root note.

This repo contains local/test audio files under `spartan_tuner\` (WAVs generated during development). Most audio is ignored by `.gitignore` to keep the repo small, but the curated examples in `spartan_tuner\test\` are intended to be kept for the public beta.
