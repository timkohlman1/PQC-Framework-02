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
    parser.add_argument("--secure-boot", action="store_true", help="A7 normal secure-boot comparisons")
    parser.add_argument("--energy", action="store_true", help="A6 offline energy totals and phases")
    parser.add_argument("--energy-spec", type=Path, help="A6 boundary references and selected trace JSON")
    parser.add_argument("--network-spec", type=Path, help="A5 run-key endpoint/window selection JSON")
    parser.add_argument("--tls", action="store_true", help="Include A4 TLS attribution and run summaries")
    parser.add_argument("--resources", action="store_true", help="Include A3 resources from verified retained inputs")
    parser.add_argument("--execute-notebook", action="store_true")
    parser.add_argument("--notebook", type=Path, default=None)
    args = parser.parse_args()
    if args.notebook is None:
        args.notebook = Path(__file__).resolve().parents[1] / ("notebooks/secure_boot_comparison.ipynb" if args.secure_boot else "notebooks/energy_comparison.ipynb" if args.energy or args.energy_spec else "notebooks/network_comparison.ipynb" if args.network_spec else "notebooks/tls_attribution.ipynb" if args.tls else "notebooks/timing_comparison.ipynb")
    try:
        if args.output.exists():
            raise ValueError("output already exists; choose a new destination")
        spec = json.loads(args.spec.read_text())
        network = json.loads(args.network_spec.read_text()) if args.network_spec else None
        energy = json.loads(args.energy_spec.read_text()) if args.energy_spec else {} if args.energy else None
        if args.execute_notebook:
            import nbformat
            from nbclient import NotebookClient
            notebook = nbformat.read(args.notebook, as_version=4)
            os.environ.update(PQC_A2_DATASET=str(args.dataset.resolve()), PQC_A2_SPEC=str(args.spec.resolve()),
                              PQC_A2_OUTPUT=str(args.output.resolve()), PQC_A3_RESOURCES="1" if args.resources else "0", PQC_A4_TLS="1" if args.tls else "0", PQC_A5_NETWORK_SPEC=str(args.network_spec.resolve()) if args.network_spec else "")
            os.environ["PQC_A7_SECURE_BOOT"] = "1" if args.secure_boot else "0"
            os.environ["PQC_A6_ENERGY_SPEC"] = json.dumps(energy)
            NotebookClient(notebook, timeout=180, kernel_name="python3", allow_errors=False,
                           resources={"metadata": {"path": str(Path(__file__).resolve().parents[1])}}).execute()
            if not (args.output / "summary.json").is_file():
                raise ValueError("notebook did not produce a summary")
            produced = json.loads((args.output / "summary.json").read_text())
            if args.secure_boot and "secure_boot" not in produced:
                raise ValueError("notebook omitted requested secure-boot domain")
            if args.tls and "tls" not in produced or args.resources and "resources" not in produced:
                raise ValueError("notebook omitted a requested analysis domain")
            if network is not None and "network" not in produced:
                raise ValueError("notebook omitted requested network domain")
            if energy is not None and "energy" not in produced:
                raise ValueError("notebook omitted requested energy domain")
            nbformat.write(notebook, args.output / "executed.ipynb")
            (args.output / "notebook-execution.json").write_text(json.dumps({
                "source_notebook_sha256": digest(args.notebook), "spec_sha256": digest(args.spec),
                "executed_notebook_sha256": digest(args.output / "executed.ipynb"),
                "note": "Execution timestamps and rendering metadata are not deterministic."}, indent=2) + "\n")
        else:
            export_summary(args.dataset, spec, args.output, resources=args.resources, tls=args.tls, network=network, energy=energy, secure_boot=args.secure_boot)
        print(json.dumps({"output": str(args.output), "status": "exported"}))
        return 0
    except Exception as exc:
        print(f"A2 analysis failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
