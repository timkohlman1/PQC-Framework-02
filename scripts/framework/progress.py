"""Timestamped human-facing progress output for framework workflows."""
from __future__ import annotations

from datetime import datetime
import os
import sys
from typing import Callable, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Clock = Callable[[], datetime]
DEFAULT_PROGRESS_TIMEZONE = "Australia/Melbourne"


def _progress_timezone() -> ZoneInfo:
    configured = os.environ.get("PQC_PROGRESS_TIMEZONE", DEFAULT_PROGRESS_TIMEZONE).strip()
    try:
        return ZoneInfo(configured)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _default_clock() -> datetime:
    return datetime.now(tz=_progress_timezone())


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
    instant = clock()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_progress_timezone())
    else:
        instant = instant.astimezone(_progress_timezone())
    timestamp = instant.strftime("%Y-%m-%d %H:%M:%S %Z")
    label = stage.strip().upper()[:12]
    print(f"{timestamp}  [{label:<12}] {message}", file=output, flush=True)
    if detail:
        print(f"{'':23}{detail}", file=output, flush=True)
