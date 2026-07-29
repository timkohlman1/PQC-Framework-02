from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO

from framework.progress import emit_progress


def test_emit_progress_formats_timestamp_stage_and_detail() -> None:
    output = StringIO()
    emit_progress(
        "build",
        "Application build decision complete",
        detail="Build skipped: cached_build_valid. 0 compiler warnings.",
        stream=output,
        clock=lambda: datetime(2026, 7, 29, 21, 55, 6, tzinfo=timezone.utc),
    )

    lines = output.getvalue().splitlines()
    assert lines[0] == "2026-07-29 21:55:06  [BUILD       ] Application build decision complete"
    assert lines[1].strip() == "Build skipped: cached_build_valid. 0 compiler warnings."


def test_emit_progress_truncates_long_stage_labels() -> None:
    output = StringIO()
    emit_progress(
        "external_dependencies",
        "Prepared",
        stream=output,
        clock=lambda: datetime(2026, 7, 29, 21, 55, 6, tzinfo=timezone.utc),
    )
    assert "[EXTERNAL_DEP]" in output.getvalue()
