from datetime import datetime
from io import StringIO
import hashlib
import sys

import pytest

from framework.run_console import ANSI, RunOutput, RunStatus, attach_run_output, seal_run_output


@pytest.mark.parametrize("status", ["Success", "Failed", "Skipped", "Blocked", "Interrupted"])
def test_terminal_updates_same_row_with_bounded_width_and_status_color(monkeypatch, status):
    monkeypatch.setenv("PQC_PROGRESS_TTY", "1")
    monkeypatch.setenv("PQC_PROGRESS_COLUMNS", "120")
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = StringIO()
    progress = RunStatus(stream, clock=lambda: datetime(2026, 9, 30, 12, 0, 0))
    progress.start("a" * 150, 0, 20)
    progress.identify("2026-09-30_001_" + "run" * 80 + "-unique-suffix")
    progress.finish(status, done=1)
    raw = stream.getvalue()
    assert raw.count("\n") == 1
    assert raw.count("\r\x1b[2K") == 3
    assert "\x1b[33m[Running]" in raw
    assert f"[{status}]" in raw
    frames = [ANSI.sub("", row).strip("\n") for row in raw.split("\r") if row]
    assert all(len(row) <= 119 for row in frames)
    assert frames[-1].endswith(f"[{status}] 1/20")
    assert "-unique-suffix" in frames[-1]


def test_redirected_output_is_one_plain_final_line(monkeypatch):
    monkeypatch.setenv("PQC_PROGRESS_TTY", "0")
    stream = StringIO()
    progress = RunStatus(stream)
    progress.start("placeholder", 9, 20)
    progress.identify("actual-id")
    assert stream.getvalue() == ""
    progress.finish("Success", done=10)
    assert "actual-id [Success] 10/20\n" in stream.getvalue()
    assert "\r" not in stream.getvalue() and "\x1b" not in stream.getvalue()


def test_no_color_still_updates_in_place(monkeypatch):
    monkeypatch.setenv("PQC_PROGRESS_TTY", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    stream = StringIO()
    progress = RunStatus(stream)
    progress.start("run")
    progress.finish("Failed", done=1)
    assert "\r\x1b[2K" in stream.getvalue()
    assert "\x1b[31m" not in stream.getvalue()


@pytest.mark.parametrize("outcome", ["success", "failure", "exception", "interrupt"])
def test_run_transcript_captures_details_and_closes_before_sealing(tmp_path, monkeypatch, capsys, outcome):
    monkeypatch.setenv("PQC_PROGRESS_TTY", "0")
    monkeypatch.delenv("PQC_RUN_VERBOSE", raising=False)
    sealed = []
    output = RunOutput("before-allocation")
    def operation():
        print("before folder exists")
        attach_run_output(tmp_path, "actual-run-id")
        print("full detailed run output")
        print("stderr detail", file=sys.stderr)
        if outcome == "exception":
            raise RuntimeError("test exception")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        seal_run_output(tmp_path)
        sealed.append(hashlib.sha256((tmp_path / "console.log").read_bytes()).hexdigest())
        return 0 if outcome == "success" else 7
    if outcome in {"exception", "interrupt"}:
        with pytest.raises(RuntimeError if outcome == "exception" else KeyboardInterrupt):
            output.execute(operation)
    else:
        assert output.execute(operation) == (0 if outcome == "success" else 7)
    contents = (tmp_path / "console.log").read_text()
    assert all(text in contents for text in ("before folder exists", "full detailed run output", "stderr detail"))
    assert "\x1b" not in contents
    if sealed:
        assert sealed[0] == hashlib.sha256((tmp_path / "console.log").read_bytes()).hexdigest()
    if outcome == "exception":
        assert "RuntimeError: test exception" in contents
    if outcome == "interrupt":
        assert "Interrupted by operator" in contents
    console = capsys.readouterr().out
    assert len(console.splitlines()) == 1
    assert "actual-run-id" in console and "detail" not in console
    assert ("[Success]" if outcome == "success" else "[Interrupted]" if outcome == "interrupt" else "[Failed]") in console
