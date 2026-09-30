"""Compact run status and per-run transcripts; no hardware or evidence verdicts."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
import io
import os
from pathlib import Path
import re
import shutil
import sys
import traceback

from framework.progress import _default_clock

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
COLORS = {"Running": "33", "Success": "32", "Failed": "31", "Skipped": "36",
          "Blocked": "35", "Interrupted": "33"}
_ACTIVE = ContextVar("run_console", default=None)


def terminal_environment(stream=None):
    stream = stream or sys.stdout
    return {"PQC_PROGRESS_TTY": "1" if stream.isatty() else "0",
            "PQC_PROGRESS_COLUMNS": str(shutil.get_terminal_size((120, 24)).columns)}


class RunStatus:
    """Keep one terminal row per run; redirected output gets only final rows."""
    def __init__(self, stream=None, *, clock=_default_clock):
        self._stream = stream
        self.clock = clock
        self.tty = os.environ.get("PQC_PROGRESS_TTY", "1" if self.stream.isatty() else "0") == "1"
        try:
            columns = int(os.environ.get("PQC_PROGRESS_COLUMNS", shutil.get_terminal_size((120, 24)).columns))
        except ValueError:
            columns = 120
        self.width = max(40, min(120, columns)) - 1
        self.color = self.tty and "NO_COLOR" not in os.environ
        self.run_id = None
        self.done = 0
        self.total = 1
        self.label = ""

    @property
    def stream(self):
        return self._stream if self._stream is not None else sys.stdout

    def start(self, run_id, done=0, total=1, *, label=""):
        self.run_id, self.done, self.total, self.label = str(run_id), done, total, label
        self._draw("Running")

    def identify(self, run_id):
        self.run_id = str(run_id)
        self._draw("Running")

    def finish(self, status, *, done=None):
        if self.run_id is None:
            return
        if done is not None:
            self.done = done
        self._draw(status, final=True)
        self.run_id = None

    def _draw(self, status, *, final=False):
        if not self.tty and not final:
            return
        stamp = self.clock().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"{stamp} "
        suffix = f" [{status}] {self.done}/{self.total}" + (f" {self.label}" if self.label else "")
        # Run identifiers are ASCII in the framework. Sanitize arbitrary fallback
        # labels too, so escape codes/control characters cannot corrupt the row.
        identifier = ANSI.sub("", self.run_id).encode("ascii", "replace").decode("ascii")
        identifier = "".join(c if 32 <= ord(c) < 127 else "?" for c in identifier)
        available = max(1, self.width - len(prefix) - len(suffix))
        if len(identifier) > available:
            left = (available - 3) // 2
            identifier = identifier[:left] + "..." + identifier[-(available - 3 - left):] if available > 3 else identifier[:available]
        if self.color:
            suffix = suffix.replace(f"[{status}]", f"\x1b[{COLORS[status]}m[{status}]\x1b[0m", 1)
        row = prefix + identifier + suffix
        self.stream.write(("\r\x1b[2K" if self.tty else "") + row + ("\n" if final else ""))
        self.stream.flush()


class RunOutput(io.TextIOBase):
    """Capture Python stdout/stderr, attaching to the framework-created run."""
    def __init__(self, fallback):
        self.console = sys.stdout
        self.verbose = os.environ.get("PQC_RUN_VERBOSE") == "1"
        self.status = RunStatus(self.console)
        self.fallback = str(fallback)
        self.pending = io.StringIO()
        self.log = None
        self.directory = None

    def write(self, value):
        if self.verbose:
            self.console.write(value)
            self.console.flush()
        target = self.log if self.log is not None else self.pending
        target.write(ANSI.sub("", value))
        target.flush()
        return len(value)

    def flush(self):
        if self.log is not None:
            self.log.flush()

    def attach(self, directory, run_id):
        self.directory = Path(directory)
        self.log = (self.directory / "console.log").open("x", encoding="utf-8", buffering=1)
        self.log.write(self.pending.getvalue())
        self.pending = io.StringIO()
        if not self.verbose:
            self.status.identify(run_id)

    def seal(self, directory):
        if self.directory == Path(directory) and self.log is not None:
            self.log.flush()
            self.log.close()
            self.log = None

    def execute(self, operation):
        if not self.verbose:
            self.status.start(self.fallback)
        token = _ACTIVE.set(self)
        result = 1
        state = "Failed"
        try:
            with redirect_stdout(self), redirect_stderr(self):
                try:
                    result = operation()
                    state = "Success" if result == 0 else "Failed"
                except KeyboardInterrupt:
                    state, result = "Interrupted", 130
                    print("Interrupted by operator.")
                    raise
                except BaseException:
                    traceback.print_exc()
                    raise
            return result
        finally:
            _ACTIVE.reset(token)
            if self.log is not None:
                self.log.close()
                self.log = None
            if not self.verbose:
                self.status.finish(state, done=0 if state == "Interrupted" else 1)
            # Pre-allocation errors or errors during sealing cannot go into the
            # already sealed transcript. Keep these exceptional diagnostics visible.
            remaining = self.pending.getvalue()
            if remaining and not self.verbose:
                self.console.write(remaining)
                self.console.flush()


def attach_run_output(directory, run_id):
    active = _ACTIVE.get()
    if active is not None:
        active.attach(directory, run_id)


def seal_run_output(directory):
    active = _ACTIVE.get()
    if active is not None:
        active.seal(directory)
