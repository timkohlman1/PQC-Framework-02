from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPO_ROOT / "Core" / "Src" / "pqc_wolfmqtt_build_only.c"


def _define_value(source: str, name: str) -> int:
    match = re.search(
        rf"(?m)^#define\s+{re.escape(name)}\s+(\d+)U?\s*$",
        source,
    )
    assert match is not None, f"missing {name} in {FIRMWARE_SOURCE}"
    return int(match.group(1))


def test_reporting_run_id_capacity_covers_campaign_preparation_ids():
    """Retained campaign preparation IDs must fit the STM32 reporting buffer."""
    source = FIRMWARE_SOURCE.read_text(encoding="utf-8")

    run_id_capacity = _define_value(source, "PQC_REPORTING_RUN_ID_MAX")

    # This is the shape that exposed the Request-8 regression.  The concrete
    # identifier is intentionally representative rather than tied to a result
    # directory produced by a particular test invocation.
    representative = (
        "2026-09-24_001_"
        "hw_test_reporting_plane_isolation_hw_066414050b9d_"
        "retained_rate-preparation-0001-39847eb0bde4"
    )

    assert len(representative) == 108
    assert run_id_capacity > len(representative)


def test_reporting_run_id_capacity_fits_existing_topic_and_payload_buffers():
    """Increasing run-ID capacity must not overflow the fixed reporting buffers."""
    source = FIRMWARE_SOURCE.read_text(encoding="utf-8")
    run_id_capacity = _define_value(source, "PQC_REPORTING_RUN_ID_MAX")

    # The implementation rejects payload lengths >= sizeof(run_id), so the
    # longest accepted identifier is capacity - 1.
    max_run_id_length = run_id_capacity - 1

    topic_buffer_match = re.search(r"char\s+topic\[(\d+)\];", source)
    payload_buffer_match = re.search(r"char\s+payload\[(\d+)\];", source)
    chunk_match = re.search(r"#define\s+PQC_REPORTING_CHUNK_BYTES\s+(\d+)U", source)
    assert topic_buffer_match is not None
    assert payload_buffer_match is not None
    assert chunk_match is not None

    topic_buffer = int(topic_buffer_match.group(1))
    payload_buffer = int(payload_buffer_match.group(1))
    chunk_bytes = int(chunk_match.group(1))

    longest_topic = len("pqc/result/stm32/") + max_run_id_length + len("/complete")
    assert longest_topic < topic_buffer

    # Worst-case chunk JSON: maximum uint32 sequence plus two hex characters
    # per data byte.
    chunk_json_fixed = len(
        '{"schema_version":1,"type":"chunk","source":"stm32","run_id":"",'
        '"sequence":4294967295,"context":"deferred_result_buffer","data_hex":""}'
    )
    longest_chunk_payload = chunk_json_fixed + max_run_id_length + (chunk_bytes * 2)
    assert longest_chunk_payload < payload_buffer
