from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_source_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "source.py"
    spec = importlib.util.spec_from_file_location("framework_source", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_capture_git_provenance_records_clean_state(tmp_path):
    source = load_source_module()
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        assert cwd == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return source.GitCommandExecution(command, 0, "abc123\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return source.GitCommandExecution(command, 0, "", "", 0.01)
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result == {
        "git_commit": "abc123",
        "git_dirty": False,
        "git_status_available": True,
    }
    assert calls == [["git", "rev-parse", "HEAD"], ["git", "status", "--short"]]


def test_capture_git_provenance_records_dirty_state_without_file_contents(tmp_path):
    source = load_source_module()

    def fake_runner(command, cwd):
        if command == ["git", "rev-parse", "HEAD"]:
            return source.GitCommandExecution(command, 0, "def456\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return source.GitCommandExecution(
                command,
                0,
                " M scripts/framework/build.py\n?? tests/unit/test_source.py\n",
                "",
                0.01,
            )
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result == {
        "git_commit": "def456",
        "git_dirty": True,
        "git_status_available": True,
    }


def test_capture_git_provenance_records_unavailable_state_when_git_fails(tmp_path):
    source = load_source_module()

    def fake_runner(command, cwd):
        return source.GitCommandExecution(command, 128, "", "not a git repository", 0.01)

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result == {
        "git_commit": None,
        "git_dirty": None,
        "git_status_available": False,
    }


def test_capture_git_provenance_records_status_unavailable_when_status_fails(tmp_path):
    source = load_source_module()

    def fake_runner(command, cwd):
        if command == ["git", "rev-parse", "HEAD"]:
            return source.GitCommandExecution(command, 0, "abc123\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return source.GitCommandExecution(command, 128, "", "status failed", 0.01)
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result == {
        "git_commit": "abc123",
        "git_dirty": None,
        "git_status_available": False,
    }
