"""Timestamped human-facing progress output for framework workflows."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, TextIO
import sys

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now().astimezone()


def emit_progress(
    stage: str,
    message: str,
    *,
    detail: str | None = None,
    stream: TextIO | None = None,
    clock: Clock = _default_clock,
) -> None:
    """Emit one timestamped progress event and an optional indented detail line."""
    output = stream or sys.stdout
    timestamp = clock().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    label = stage.strip().upper()[:12]
    print(f"{timestamp}  [{label:<12}] {message}", file=output, flush=True)
    if detail:
        print(f"{'':19}{detail}", file=output, flush=True)
