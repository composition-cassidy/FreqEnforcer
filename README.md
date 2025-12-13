# FreqEnforcer

FreqEnforcer is a small desktop tool for pitch-correcting monophonic samples to a target note, tailored towards sample editing for Sparta Remixers aswell as YTPMVs.

## Features

- Load audio files:(`.wav`, `.mp3`, `.flac`, `.ogg` supported)
- Detect predominant pitch
- Pitch-correct to a selected target note
- Optional time-stretch and normalization
- Export processed audio to WAV
  - Exported WAVs are tagged with sampler metadata (`smpl` + `inst` RIFF chunks) so many DAWs/samplers can auto-detect the **root note**

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

## Examples / A-B comparisons

Compared to its competition under this field, Melodyne, it is far superior when battling background noise, rough speech, and general efficiency.

- `5_ORIGINALSAMPLE.wav`
  - Untouched source audio
- `6_FREQENFORCER.wav`
  - The same sample processed with FreqEnforcer
- `6_MELODYNE.wav`
  - The same sample processed with Melodyne (for comparison)

### How to try them

1) Launch the app.
2) Drag & drop one of the files from `spartan_tuner\test\` into the window.
3) Toggle between original/processed where applicable and export.
4) (Optional) Drag the exported WAV into your DAW sampler.
   - The export includes WAV sampler metadata (`smpl` + `inst`) so many samplers can auto-set the root note.

This repo contains local/test audio files under `spartan_tuner\` (WAVs generated during development). Most audio is ignored by `.gitignore` to keep the repo small, but the curated examples in `spartan_tuner\test\` are intended to be kept for the public beta.
