"""Allocate real result folders in successive runtime processes after run 999."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def test_runtime_processes_continue_numbering_without_changing_retained_run(tmp_path):
    retained = tmp_path / "2026-06-25_999_previous_experiment"
    retained.mkdir()
    original = b'{"retained_capture": "must remain unchanged"}\n'
    (retained / "manifest.json").write_bytes(original)
    script = """
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from framework.config_resolver import ConfigResolver
from framework.manifest import create_result_folder
resolver = ConfigResolver(Path(sys.argv[1]))
case = resolver.expand_campaign("baseline")[0]
bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
folder, _ = create_result_folder(
    bundle, Path(sys.argv[2]), datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc))
print(folder.name)
"""
    created = []
    for sequence in (1000, 1001, 1002):
        process = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(tmp_path)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        folder = tmp_path / process.stdout.strip().splitlines()[-1]
        assert folder.name.startswith(f"2026-06-25_{sequence}_")
        data = json.loads((folder / "manifest.json").read_text())
        assert data["run_id"] == folder.name
        assert (folder / "notes.md").is_file()
        created.append(folder)
    assert len(set(created)) == 3
    assert len(list(tmp_path.iterdir())) == 4
    assert (retained / "manifest.json").read_bytes() == original
