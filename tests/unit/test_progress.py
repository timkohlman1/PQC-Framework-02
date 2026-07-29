from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO

from framework.progress import emit_progress


def test_emit_progress_formats_melbourne_timestamp_stage_and_detail(monkeypatch) -> None:
    monkeypatch.setenv("PQC_PROGRESS_TIMEZONE", "Australia/Melbourne")
    output = StringIO()
    emit_progress(
        "build",
        "Application compilation completed",
        detail="0 compiler warnings; return code: 0.",
        stream=output,
        clock=lambda: datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc),
    )

    lines = output.getvalue().splitlines()
    assert lines[0] == "2026-07-29 22:00:00 AEST  [BUILD       ] Application compilation completed"
    assert lines[1].strip() == "0 compiler warnings; return code: 0."


def test_emit_progress_truncates_long_stage_labels(monkeypatch) -> None:
    monkeypatch.setenv("PQC_PROGRESS_TIMEZONE", "UTC")
    output = StringIO()
    emit_progress(
        "external_dependencies",
        "Prepared",
        stream=output,
        clock=lambda: datetime(2026, 7, 29, 21, 55, 6, tzinfo=timezone.utc),
    )
    assert "2026-07-29 21:55:06 UTC" in output.getvalue()
    assert "[EXTERNAL_DEP]" in output.getvalue()
