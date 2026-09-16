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
