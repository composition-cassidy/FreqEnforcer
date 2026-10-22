"""Multisample rendering: one processed, looped WAV per MIDI note.

Notes are independent, so they are rendered in a ProcessPoolExecutor
(cpu_count - 1 workers, capped at the number of notes).  Each worker gets
the source audio, settings and the parent's WORLD F0 cache once (pool
initializer) and then renders whole notes: pipeline -> trim -> loop ->
WAV + smpl chunk.  workers=1 renders in-process, in order.
"""

from __future__ import annotations

import os
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .loader import save_audio, set_wav_root_note
from .loop_crossfade import process_with_loop
from .sfz_writer import note_name_for_filename

# Pipeline target names use '#'; filenames use 's' (note_name_for_filename).
_NOTE_NAMES_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


@dataclass(frozen=True)
class RenderOptions:
    output_dir: str
    base_name: str
    enable_loop: bool = True
    template_periods: int = 6
    min_loop_periods: int = 10
    crossfade_periods: int = 2
    start_trim_ms: float = 0.0


def default_workers(n_notes: int) -> int:
    return max(1, min((os.cpu_count() or 2) - 1, n_notes))


def render_note(source_audio: np.ndarray, sr: int, midi_note: int, settings_base: dict,
                options: RenderOptions, run_pipeline: Callable) -> dict:
    """Render, loop and write one note; returns its SFZ zone dict."""
    note_name = note_name_for_filename(midi_note)
    note_settings = dict(settings_base)
    note_settings["target_note"] = _NOTE_NAMES_SHARP[midi_note % 12] + str(midi_note // 12 - 1)

    processed = run_pipeline(source_audio.copy(), sr, note_settings)

    if options.start_trim_ms > 0:
        trim_samples = int(options.start_trim_ms / 1000.0 * sr)
        if trim_samples < len(processed):
            processed = processed[trim_samples:]

    loop_start = None
    loop_end = None
    if options.enable_loop:
        target_f0 = 440.0 * (2 ** ((midi_note - 69) / 12))
        processed, loop_start, loop_end = process_with_loop(
            processed, sr,
            f0_hz=target_f0,
            template_periods=options.template_periods,
            min_loop_periods=options.min_loop_periods,
            crossfade_periods=options.crossfade_periods,
        )

    filename = f"{options.base_name}_{note_name}.wav"
    filepath = os.path.join(options.output_dir, filename)
    save_audio(filepath, processed, sr)
    set_wav_root_note(filepath, midi_note, sr, loop_start, loop_end)

    return {
        "midi": midi_note,
        "note_name": note_name,
        "path": filepath,
        "filename": filename,
        "loop_start": loop_start,
        "loop_end": loop_end,
        "sample_count": len(processed),
    }


# ---------------------------------------------------------------------------
# Worker process side
# ---------------------------------------------------------------------------

_worker: dict = {}


def _exit_with_parent() -> None:
    """Pool workers aren't told when the backend dies (on Windows a killed
    parent leaves them blocked on the task queue forever), so each one waits on
    the parent's process handle and exits with it."""
    import multiprocessing
    import threading

    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch():
        parent.join()
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def _init_worker(source_audio, sr, settings_base, options, detected_pitch, world_cache):
    from server.state import state

    _exit_with_parent()

    # The WORLD pitch modes read the F0 cache from the process-global state;
    # detected_pitch mirrors what /api/load-audio stored (not used by the DSP).
    state.detected_pitch = detected_pitch
    if world_cache is not None:
        state.world_cache = world_cache
    _worker.update(source_audio=source_audio, sr=sr, settings_base=settings_base,
                   options=options)


def _worker_pipeline(audio, sr, settings):
    from server.routes.audio import _run_pipeline
    from server.state import state

    result, _harmonics, _timings = _run_pipeline(audio, sr, settings,
                                                 state.processing_token, None)
    return result


def _render_note_in_worker(midi_note: int) -> dict:
    w = _worker
    return render_note(w["source_audio"], w["sr"], midi_note, w["settings_base"],
                       w["options"], _worker_pipeline)


# ---------------------------------------------------------------------------
# Parent side
# ---------------------------------------------------------------------------

class RenderCancelled(Exception):
    pass


def render_note_range(
    source_audio: np.ndarray,
    sr: int,
    midi_notes: list[int],
    settings_base: dict,
    options: RenderOptions,
    *,
    detected_pitch: Optional[dict],
    world_cache: Optional[dict],
    run_pipeline_inprocess: Callable,
    workers: Optional[int] = None,
    on_note_done: Optional[Callable[[dict, int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> list[dict]:
    """Render *midi_notes*; returns zone dicts sorted by MIDI note.

    on_note_done(zone, notes_done, notes_total) is called in the calling
    thread as each note finishes.  is_cancelled() is polled between
    completions; when it returns True pending notes are dropped and
    RenderCancelled is raised.
    """
    os.makedirs(options.output_dir, exist_ok=True)
    total = len(midi_notes)
    n_workers = default_workers(total) if workers is None else max(1, min(workers, total))
    results: list[dict] = []

    if n_workers == 1:
        for midi_note in midi_notes:
            if is_cancelled and is_cancelled():
                raise RenderCancelled()
            zone = render_note(source_audio, sr, midi_note, settings_base, options,
                               run_pipeline_inprocess)
            results.append(zone)
            if on_note_done:
                on_note_done(zone, len(results), total)
        return results

    # Workers only need F0 + time axis from the WORLD cache (pitch modes never
    # read sp/ap from it), which keeps the per-worker payload small.
    slim_cache = None
    if world_cache and world_cache.get("f0") is not None:
        slim_cache = {k: world_cache.get(k) for k in ("audio_hash", "f0", "timeaxis", "sr")}
        slim_cache.update(sp=None, ap=None)

    pool = ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_worker,
        initargs=(source_audio, sr, settings_base, options, detected_pitch, slim_cache),
    )
    try:
        pending = {pool.submit(_render_note_in_worker, m) for m in midi_notes}
        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if is_cancelled and is_cancelled():
                raise RenderCancelled()
            for fut in done:
                zone = fut.result()  # re-raises worker exceptions
                results.append(zone)
                if on_note_done:
                    on_note_done(zone, len(results), total)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results.sort(key=lambda z: z["midi"])
    return results
