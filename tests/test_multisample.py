"""Parallel multisample rendering must match the in-process render exactly.

Renders a few notes of test_2s_C4.wav (world_hard, loops on) once in-process
(workers=1, the old serial path) and once through the process pool, and
compares the written files byte for byte.  F4 is also checked against the
pipe_loop golden reference, so the parallel path is anchored to the baseline.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

import matrix

FIXTURE = "test_2s_C4.wav"
NOTES = [57, 60, 63, 65, 66, 71]  # A3 C4 D#4 F4 F#4 B4 (sharps exercise filenames)


def _render(tmp_path, workers: int):
    from server.audio.multisample import RenderOptions, render_note_range
    from server.routes.audio import _run_pipeline, _world_cache_for
    from server.state import state

    audio, sr = matrix.load_fixture(FIXTURE)
    freq, note, cents = matrix.detect_source(FIXTURE)
    state.detected_pitch = {"freq_hz": freq, "note_name": note, "cents": cents}
    state.world_cache = {"audio_hash": None}
    settings = dict(matrix.PIPELINE_DEFAULTS)
    token = state.increment_token()
    world_cache = _world_cache_for(audio, sr, settings, {})

    out_dir = tmp_path / f"w{workers}"
    options = RenderOptions(output_dir=str(out_dir), base_name="t")
    progress = []
    zones = render_note_range(
        audio, sr, NOTES, settings, options,
        detected_pitch=state.detected_pitch,
        world_cache=world_cache,
        run_pipeline_inprocess=lambda a, s, st: _run_pipeline(a, s, st, token, None)[0],
        workers=workers,
        on_note_done=lambda zone, done, total: progress.append((done, total)),
    )
    return zones, out_dir, progress


@pytest.fixture(scope="module")
def renders(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ms")
    return _render(tmp, 1), _render(tmp, 3)


def test_parallel_matches_serial(renders):
    (z1, d1, _), (z3, d3, _) = renders
    assert [z["midi"] for z in z3] == NOTES
    for a, b in zip(z1, z3):
        assert (a["filename"], a["loop_start"], a["loop_end"], a["sample_count"]) == \
               (b["filename"], b["loop_start"], b["loop_end"], b["sample_count"])
        assert (d1 / a["filename"]).read_bytes() == (d3 / b["filename"]).read_bytes(), a["filename"]


def test_filenames_have_no_hash(renders):
    _, (zones, out_dir, _) = renders
    names = [p.name for p in out_dir.iterdir()]
    assert len(names) == len(NOTES)
    assert not any("#" in n for n in names), names


def test_progress_reports_every_note(renders):
    _, (_, _, progress) = renders
    assert progress == [(i, len(NOTES)) for i in range(1, len(NOTES) + 1)]


def test_f4_matches_pipe_loop_golden(renders):
    _, (zones, out_dir, _) = renders
    manifest = json.loads(matrix.MANIFEST_PATH.read_text())
    ref_entry = next(c for c in manifest["cases"] if c["mode"] == "pipe_loop")
    ref, _ = sf.read(str(matrix.GOLDEN_DIR / ref_entry["file"]), dtype="float32")
    zone = next(z for z in zones if z["midi"] == 65)
    # manifest.json stores numpy ints via json default=str, hence int()
    assert (int(zone["loop_start"]), int(zone["loop_end"])) == \
           (int(ref_entry["loop_start"]), int(ref_entry["loop_end"]))
    got, _ = sf.read(str(out_dir / zone["filename"]), dtype="float32")  # PCM16 on disk
    assert got.shape == ref.shape
    assert np.max(np.abs(got - np.clip(ref, -1.0, 1.0))) <= 1.0 / 32768 + 1e-7
