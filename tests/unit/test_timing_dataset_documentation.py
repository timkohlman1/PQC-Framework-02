"""Keep analysis entry points discoverable without snapshotting explanatory prose."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/012_results_and_analysis.md"


@pytest.mark.parametrize("script,flags", [
    ("export_timing_dataset.py", ("--results-root", "--run-dir", "--output", "--check", "--verify-source-inputs")),
    ("analyse_results.py", ("--spec", "--output", "--export", "--recipe", "--comparison", "--network-selection", "--energy-selection", "--verify-sources")),
    ("build_research_report.py", ("--spec", "--output", "--verify", "--rebuild")),
])
def test_analysis_reference_exposes_supported_cli_options(script, flags):
    documentation = RESULTS.read_text()
    source = (ROOT / "scripts" / script).read_text()
    assert script in documentation
    for flag in flags:
        assert flag in documentation
        assert re.search(rf"['\"]{re.escape(flag)}['\"]", source), (script, flag)


def test_analysis_notebook_routes_exist():
    documentation = RESULTS.read_text()
    notebooks = set(re.findall(r"notebooks/[\w-]+\.ipynb", documentation))
    assert notebooks
    for path in notebooks:
        assert (ROOT / path).is_file(), path
    for entry in ("README.md", "docs/README.md", "docs/007_framework_architecture.md"):
        assert "012_results_and_analysis.md" in (ROOT / entry).read_text()
