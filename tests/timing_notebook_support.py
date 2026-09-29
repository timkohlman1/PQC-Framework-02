"""Test-owned configuration for the real A2 notebook analysis cells."""
from pathlib import Path

import nbformat


def isolated_notebook(source: Path, destination: Path) -> Path:
    """Copy an interactive notebook, replacing only its configuration cell.

    Saved campaign paths and outputs are user settings, never CI prerequisites.
    The CLI supplies paths to the synthetic dataset, specification and output.
    All subsequent analysis/plotting cells remain the repository versions.
    """
    notebook = nbformat.read(source, as_version=4)
    configuration = next(cell for cell in notebook.cells if cell.cell_type == "code")
    if not configuration.source.startswith("# Configuration"):
        raise ValueError(f"Expected an explicit first configuration cell in {source}")
    root = Path(__file__).resolve().parents[1]
    configuration.source = f"""# Configuration: test-owned synthetic inputs only.
import json
import os
import sys
from pathlib import Path
ROOT = Path({str(root)!r})
sys.path.insert(0, str(ROOT / "scripts"))
DATASET = Path(os.environ["PQC_A2_DATASET"])
SPEC_FILE = Path(os.environ["PQC_A2_SPEC"])
OUTPUT = Path(os.environ["PQC_A2_OUTPUT"])
SPEC = json.loads(SPEC_FILE.read_text())
"""
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    nbformat.write(notebook, destination)
    return destination
