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
        if command == ["git", "branch", "--show-current"]:
            return source.GitCommandExecution(command, 0, "main\n", "", 0.01)
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result["git_commit"] == "abc123"
    assert result["git_branch"] == "main"
    assert result["git_dirty"] is False
    assert result["git_status_available"] is True
    assert result["source_state_sha256"] is None
    assert ["git", "rev-parse", "HEAD"] in calls
    assert ["git", "status", "--short"] in calls


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
        if command == ["git", "branch", "--show-current"]:
            return source.GitCommandExecution(command, 0, "feature/request16\n", "", 0.01)
        if command == ["git", "diff", "--binary", "HEAD"]:
            return source.GitCommandExecution(command, 0, "diff --git a/file b/file\n", "", 0.01)
        if command == ["git", "ls-files", "--others", "--exclude-standard", "-z"]:
            return source.GitCommandExecution(command, 0, "", "", 0.01)
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result["git_commit"] == "def456"
    assert result["git_branch"] == "feature/request16"
    assert result["git_dirty"] is True
    assert result["git_status_available"] is True
    assert result["source_state_sha256"]


def test_capture_git_provenance_records_unavailable_state_when_git_fails(tmp_path):
    source = load_source_module()

    def fake_runner(command, cwd):
        return source.GitCommandExecution(command, 128, "", "not a git repository", 0.01)

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result["git_commit"] is None
    assert result["git_branch"] is None
    assert result["git_dirty"] is None
    assert result["git_status_available"] is False
    assert result["source_state_sha256"] is None


def test_capture_git_provenance_records_status_unavailable_when_status_fails(tmp_path):
    source = load_source_module()

    def fake_runner(command, cwd):
        if command == ["git", "rev-parse", "HEAD"]:
            return source.GitCommandExecution(command, 0, "abc123\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return source.GitCommandExecution(command, 128, "", "status failed", 0.01)
        if command == ["git", "branch", "--show-current"]:
            return source.GitCommandExecution(command, 0, "main\n", "", 0.01)
        raise AssertionError(f"unexpected command: {command}")

    result = source.capture_git_provenance(tmp_path, fake_runner)

    assert result["git_commit"] == "abc123"
    assert result["git_branch"] == "main"
    assert result["git_dirty"] is None
    assert result["git_status_available"] is False
    assert result["source_state_sha256"] is None
