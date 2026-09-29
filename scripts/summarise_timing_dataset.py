#!/usr/bin/env python3
"""Offline A2 batch export or fail-fast clean-kernel starter execution."""
import argparse
import json
import os
from pathlib import Path
import sys

from framework.timing_summary import export_summary, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute-notebook", action="store_true")
    parser.add_argument("--notebook", type=Path, default=Path(__file__).resolve().parents[1] / "notebooks/timing_comparison.ipynb")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output already exists; choose a new destination")
        spec = json.loads(args.spec.read_text())
        if args.execute_notebook:
            import nbformat
            from nbclient import NotebookClient
            notebook = nbformat.read(args.notebook, as_version=4)
            os.environ.update(PQC_A2_DATASET=str(args.dataset.resolve()), PQC_A2_SPEC=str(args.spec.resolve()),
                              PQC_A2_OUTPUT=str(args.output.resolve()))
            NotebookClient(notebook, timeout=180, kernel_name="python3", allow_errors=False,
                           resources={"metadata": {"path": str(Path(__file__).resolve().parents[1])}}).execute()
            if not (args.output / "summary.json").is_file():
                raise ValueError("notebook did not produce a summary")
            nbformat.write(notebook, args.output / "executed.ipynb")
            (args.output / "notebook-execution.json").write_text(json.dumps({
                "source_notebook_sha256": digest(args.notebook), "spec_sha256": digest(args.spec),
                "executed_notebook_sha256": digest(args.output / "executed.ipynb"),
                "note": "Execution timestamps and rendering metadata are not deterministic."}, indent=2) + "\n")
        else:
            export_summary(args.dataset, spec, args.output)
        print(json.dumps({"output": str(args.output), "status": "exported"}))
        return 0
    except Exception as exc:
        print(f"A2 analysis failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
