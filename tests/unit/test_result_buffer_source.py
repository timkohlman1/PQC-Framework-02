from pathlib import Path

def test_result_buffer_is_bounded_preallocated_and_sha256_complete():
    h=Path('Core/Inc/pqc_result_buffer.h').read_text(encoding='utf-8')
    c=Path('Core/Src/pqc_result_buffer.c').read_text(encoding='utf-8')
    assert 'PQC_RESULT_BUFFER_CAPACITY_BYTES (32U * 1024U)' in h
    assert 'static uint8_t s_buffer[PQC_RESULT_BUFFER_CAPACITY_BYTES]' in c
    assert 'PQC_ResultBufferSha256Hex' in c
    assert 'malloc(' not in c

def test_reporting_publishes_chunks_and_completion_after_workload_returns():
    main=Path('Core/Src/main.c').read_text(encoding='utf-8')
    wolf=Path('Core/Src/pqc_wolfmqtt_build_only.c').read_text(encoding='utf-8')
    run=main.index('PQC_MQTT_ApplicationRun(&fixture);')
    publish=main.index('PQC_WolfMQTT_PublishDeferredResults',run)
    assert publish>run
    assert 'PQC_REPORTING_CHUNK_BYTES 96U' in wolf
    assert 'type\\":\\"complete' in wolf


def test_memory_evidence_is_buffered_after_measurement():
    main=Path('Core/Src/main.c').read_text(encoding='utf-8')
    end_measurement=main.index('app_measurement_active = false;')
    memory=main.index('APP_BufferMemoryEvidence();', end_measurement)
    publish=main.index('PQC_WolfMQTT_PublishDeferredResults', memory)
    assert end_measurement < memory < publish
    assert 'PQC_ResultBufferAppendText(0U, "memory", line)' in main
    assert 'xPortGetMinimumEverFreeHeapSize()' in main
    assert 'PQC_RAM_RuntimeSnapshotGet(&ram_runtime)' in main


def test_long_records_remain_atomic_valid_json_and_capacity_bounded(tmp_path):
    """Compile the production C buffer implementation and exercise its public API."""
    import ctypes
    import json
    import shutil
    import subprocess

    import pytest

    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("Host C compiler unavailable")
    library_path = tmp_path / "libpqc_result_buffer.so"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
         "-ICore/Inc", "Core/Src/pqc_result_buffer.c", "-o", str(library_path)],
        check=True, capture_output=True, text=True,
    )
    library = ctypes.CDLL(str(library_path))
    library.PQC_ResultBufferAppendText.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p]
    library.PQC_ResultBufferAppendText.restype = ctypes.c_bool
    library.PQC_ResultBufferData.restype = ctypes.POINTER(ctypes.c_ubyte)
    library.PQC_ResultBufferSize.restype = ctypes.c_size_t

    class Status(ctypes.Structure):
        _fields_ = [("schema_version", ctypes.c_uint32),
                   ("record_count", ctypes.c_uint32),
                   ("dropped_record_count", ctypes.c_uint32),
                   ("used_bytes", ctypes.c_uint32),
                   ("overflowed", ctypes.c_uint8)]

    library.PQC_ResultBufferStatusGet.argtypes = [ctypes.POINTER(Status)]

    def snapshot():
        status = Status()
        library.PQC_ResultBufferStatusGet(ctypes.byref(status))
        raw = ctypes.string_at(library.PQC_ResultBufferData(), library.PQC_ResultBufferSize())
        return status, raw

    library.PQC_ResultBufferReset()
    # The Request-12 status is a single, long logical line; also stress JSON escaping.
    status_line = ("PQC_TLS_REPEAT_ITERATION schema=1 iteration=0 handshake=0 "
                   "fresh_tcp_connection=1 fresh_tls_context=1 session_resumption=0 "
                   "timing_source=TIM2_1MHz handshake_elapsed_us=998685 "
                   + "selected_kex=SecP256r1MLKEM768 " * 25
                   + 'extra="quoted" slash=\\ newline=\n end')
    assert len(status_line.encode()) > 768
    assert library.PQC_ResultBufferAppendText(0, b'tls_handshake_repeat', status_line.encode())
    status, raw = snapshot()
    assert status.record_count == 1
    assert status.dropped_record_count == 0
    assert status.overflowed == 0
    records = [json.loads(line) for line in raw.splitlines()]
    assert len(records) == 1
    assert records[0]["iteration"] == 0
    assert records[0]["context"] == "tls_handshake_repeat"
    assert records[0]["text"] == status_line

    # A failed append leaves every previously accepted byte intact.
    assert not library.PQC_ResultBufferAppendText(1, b'tls', b'x' * (32 * 1024))
    after, unchanged = snapshot()
    assert unchanged == raw
    assert after.record_count == 1
    assert after.dropped_record_count == 1
    assert after.overflowed == 1
    assert library.PQC_ResultBufferAppendText(2, b'tls', b'next record')
    later, joined = snapshot()
    assert later.record_count == 2
    assert [json.loads(line)["iteration"] for line in joined.splitlines()] == [0, 2]
    assert later.used_bytes == len(joined) <= 32 * 1024

    library.PQC_ResultBufferReset()
    reset, empty = snapshot()
    assert empty == b''
    assert (reset.record_count, reset.dropped_record_count, reset.overflowed) == (0, 0, 0)
