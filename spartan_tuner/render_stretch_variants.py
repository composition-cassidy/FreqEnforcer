from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from audio.autotuner import autotune_to_note
from audio.cleanliness import apply_cleanliness
from audio.loader import load_audio, save_audio
from audio.time_stretch import MissingDependencyError, STRETCHERS


def _format_factor(f: float) -> str:
    f_f = float(f)
    if abs(f_f - round(f_f)) < 1e-9:
        return str(int(round(f_f)))
    return ("{:.2f}".format(f_f)).rstrip("0").rstrip(".")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(Path(__file__).with_name("Pitch1.wav")),
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).with_name("test")),
    )
    parser.add_argument("--note", default="F4")
    parser.add_argument("--cleanliness", type=float, default=40.0)
    parser.add_argument(
        "--factors",
        nargs="+",
        type=float,
        default=[1.25, 1.5, 2.0, 5.0],
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=sorted(STRETCHERS.keys()),
        help="Subset of stretch methods to run (default: all)",
    )

    args = parser.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    audio, sr, _original_sr = load_audio(str(in_path))

    tuned = autotune_to_note(audio, sr, str(args.note), preserve_formants=True)
    tuned = np.asarray(tuned, dtype=np.float32)

    cleanliness = float(args.cleanliness)

    failures: list[str] = []

    for method_name in args.methods:
        if method_name not in STRETCHERS:
            failures.append(f"Unknown method: {method_name}")
            continue

        fn = STRETCHERS[method_name]

        for factor in args.factors:
            factor_f = float(factor)
            tag = _format_factor(factor_f)
            out_name = f"{in_path.stem}_{args.note}_{method_name}_x{tag}.wav"
            out_path = out_dir / out_name

            try:
                stretched = fn(tuned, int(sr), factor_f)
                stretched = np.asarray(stretched, dtype=np.float32)

                cleaned = apply_cleanliness(stretched, int(sr), cleanliness)
                cleaned = np.asarray(cleaned, dtype=np.float32)

                save_audio(str(out_path), cleaned, int(sr))
                print(f"WROTE: {out_path}")

            except MissingDependencyError as e:
                msg = f"SKIP ({method_name} x{tag}): {e}"
                print(msg)
                failures.append(msg)

            except Exception as e:
                msg = f"FAIL ({method_name} x{tag}): {type(e).__name__}: {e}"
                print(msg)
                failures.append(msg)

    if failures:
        print("\nSUMMARY:")
        for m in failures:
            print(m)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
