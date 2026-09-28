#!/usr/bin/env python3
"""Export or verify a current-format offline A1 timing dataset. No gateway access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from framework.timing_dataset import DatasetError, export_dataset
from framework.timing_dataset_loader import load_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-dir", type=Path, action="append", help="explicit run directory; repeat to select multiple runs")
    source.add_argument("--results-root", type=Path, help="explicit recursive discovery root; preparations/builds/analysis are excluded")
    source.add_argument("--check", type=Path, help="verify an existing dataset, without creating outputs")
    parser.add_argument("--output", type=Path, help="new generated dataset directory, separate from raw runs")
    parser.add_argument("--verify-source-inputs", action="store_true", help="with --check, re-hash the exact original consumed input paths")
    args = parser.parse_args(argv)
    if args.check is not None and args.output is not None:
        parser.error("--check does not accept --output")
    if args.check is None and (args.output is None or args.verify_source_inputs):
        parser.error("export requires --output; --verify-source-inputs is only for --check")
    try:
        if args.check is not None:
            data = load_dataset(args.check, verify_inputs=args.verify_source_inputs)
            print(json.dumps({"status": "verified", "counts": data.metadata["counts"]}, sort_keys=True))
        else:
            metadata = export_dataset(output=args.output, run_dirs=args.run_dir or (), results_root=args.results_root)
            # Exercise the same loader users will call; never publish success on an
            # internally inconsistent export, even when all run inputs were failures.
            load_dataset(args.output)
            print(json.dumps({"status": "exported", "output": str(args.output),
                              "counts": metadata["counts"], "dataset_id": metadata["dataset_id"]}, sort_keys=True))
        return 0
    except (DatasetError, OSError) as exc:
        print("timing-dataset: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
