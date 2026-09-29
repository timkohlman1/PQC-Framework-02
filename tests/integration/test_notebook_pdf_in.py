"""Exercise the Jupyter PDF pipeline with Markdown, math and a saved plot."""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys

import nbformat
import pytest


@pytest.mark.integration
def test_nbconvert_pdf_with_markdown_math_and_plot(tmp_path):
    missing = [tool for tool in ("pandoc", "xelatex") if shutil.which(tool) is None]
    if missing and not os.environ.get("PQC_CONTAINER"):
        pytest.skip("Use the maintained Docker image for PDF export")
    assert not missing, f"Rebuild development image; missing PDF tools: {missing}"
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [0.4, 0.6, 0.5])
    ax.set_ylabel("Handshake time (ms)")
    png = io.BytesIO()
    fig.savefig(png, format="png")
    plt.close(fig)
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell("# TLS analysis\n\nMean timing: $\\bar{x}=0.5$ ms.\n\n| Condition | Runs |\n|---|---|\n| Test | 3 |"),
        nbformat.v4.new_code_cell("# Saved output; exporting must not execute cells\nraise RuntimeError('do not execute')", outputs=[
            nbformat.v4.new_output("display_data", data={"image/png": base64.b64encode(png.getvalue()).decode(), "text/plain": "Timing plot"}),
        ]),
    ])
    source = tmp_path / "analysis.ipynb"
    nbformat.write(notebook, source)
    result = subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "pdf", str(source)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    pdf = source.with_suffix(".pdf").read_bytes()
    assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
