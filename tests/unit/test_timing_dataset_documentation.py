"""A1 documentation ownership guards; no hardware or experiment data required."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = "docs/007_framework_architecture.md"
A1_HEADING = "### Offline run inventory and timing dataset (Analysis Request A1)"
A1_ANCHOR = "offline-run-inventory-and-timing-dataset-analysis-request-a1"


def test_timing_dataset_usage_routes_to_canonical_owner() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / ARCHITECTURE).read_text(encoding="utf-8")
    assert f"]({ARCHITECTURE}#{A1_ANCHOR})" in readme
    assert architecture.count(A1_HEADING) == 1
    section = architecture.split(A1_HEADING, 1)[1].split("\n### ", 1)[0]
    for text in (
        "**Commands and typed loading.**",
        "./scripts/dev.sh python scripts/export_timing_dataset.py",
        "--results-root results/campaigns/SELECTED_CAMPAIGN",
        "--run-dir results/campaigns/SELECTED_CAMPAIGN/runs/SELECTED_RUN",
        "--check results/analysis/SELECTED_DATASET --verify-source-inputs",
        "from framework.timing_dataset_loader import load_dataset",
        'load_dataset("results/analysis/SELECTED_DATASET")',
        "dataset.timing_view()",
        "./scripts/dev.sh pytest tests/unit/test_timing_dataset.py",
        "./scripts/dev.sh pytest tests/integration/test_timing_dataset_in.py -m integration",
    ):
        assert text in section, f"A1 canonical usage is missing: {text}"


def test_timing_dataset_deferred_entry_is_in_consolidated_register() -> None:
    architecture = (ROOT / ARCHITECTURE).read_text(encoding="utf-8")
    heading = "## Consolidated deferred-test register"
    assert architecture.count(heading) == 1
    section = architecture.split(heading, 1)[1].split("\n## ", 1)[0]
    prefix = "| DTR-A1-CONTAINER |"
    rows = [line for line in architecture.splitlines() if line.startswith(prefix)]
    assert len(rows) == 1, "A1 must have exactly one deferred-test register row"
    assert rows[0] in section.splitlines(), "A1 entry is outside the canonical register"
    cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
    assert len(cells) == 8 and all(cells), "A1 row must retain all register fields"
    assert cells[5].startswith("`tests/")
    assert "./scripts/dev.sh" in cells[6]
