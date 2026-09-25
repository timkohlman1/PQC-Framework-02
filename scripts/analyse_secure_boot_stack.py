"""Offline aggregation of retained bootloader stack-profiling raw streams."""
import argparse
from pathlib import Path

from framework.secure_boot_stack_analysis import aggregate_runs, write_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="+", type=Path, help="Finalized run manifest.json paths")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Derived output directory under analysis/ (never a run-capture directory)")
    args = parser.parse_args()
    output = write_analysis(aggregate_runs(args.manifest), args.output_dir)
    print(f"Stack analysis: {output}")


if __name__ == "__main__":
    main()
