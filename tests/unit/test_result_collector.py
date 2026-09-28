from __future__ import annotations

import hashlib
import json

from framework.result_collector import _parse_raw_stream, expected_completion_counts, expected_result_sources, result_topics


def _line(topic: str, payload: dict) -> str:
    return json.dumps({"topic": topic, "payload": json.dumps(payload)})


def _complete(source: str, run_id: str, logical: bytes, record_count: int, chunk_count: int) -> dict:
    return {
        "type": "complete",
        "source": source,
        "run_id": run_id,
        "record_count": record_count,
        "chunk_count": chunk_count,
        "logical_bytes": len(logical),
        "logical_sha256": hashlib.sha256(logical).hexdigest(),
    }


def test_collector_accepts_ordered_complete_hash_valid_stream(tmp_path):
    logical=b'{"a":1}\n{"b":2}\n'
    run_id='run-1'
    split=len(logical)//2
    path=tmp_path/'raw.ndjson'
    path.write_text('\n'.join([
        _line(f'pqc/result/stm32/{run_id}/chunk',{"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":logical[:split].hex()}),
        _line(f'pqc/result/stm32/{run_id}/chunk',{"type":"chunk","source":"stm32","run_id":run_id,"sequence":1,"data_hex":logical[split:].hex()}),
        _line(f'pqc/result/stm32/{run_id}/complete',_complete('stm32',run_id,logical,2,2)),
    ])+'\n',encoding='utf-8')
    result=_parse_raw_stream(path,run_id)
    assert result.passed
    assert result.observed_chunk_count==2
    assert result.source_results['stm32']['observed_record_count']==2


def test_collector_rejects_missing_duplicate_and_wrong_run_id(tmp_path):
    run_id='run-1'; path=tmp_path/'raw.ndjson'
    topic=f'pqc/result/stm32/{run_id}/chunk'
    path.write_text('\n'.join([
        _line(topic,{"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":"610a"}),
        _line(topic,{"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":"610a"}),
        _line(topic,{"type":"chunk","source":"stm32","run_id":"other","sequence":2,"data_hex":"620a"}),
        _line(f'pqc/result/stm32/{run_id}/complete',{"type":"complete","source":"stm32","run_id":run_id,"record_count":1,"chunk_count":3,"logical_bytes":3,"logical_sha256":"00"*32}),
    ])+'\n',encoding='utf-8')
    result=_parse_raw_stream(path,run_id)
    assert not result.passed
    assert result.duplicate_sequences==(0,)
    assert result.missing_sequences==(1,2)
    assert any('run_id mismatch' in reason for reason in result.failure_reasons)


def test_common_collector_ignores_fixed_topic_energy_payloads_for_separate_validation(tmp_path):
    run_id = "run-1"
    stm = b'{"timing":1}\n'
    path = tmp_path / "raw.ndjson"
    path.write_text("\n".join([
        _line(f"pqc/result/stm32/{run_id}/chunk", {"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":stm.hex()}),
        _line("pqc/instrument/energy/capture/chunk", {"type":"chunk","source":"energy","schema":1,"capture_id":"0123456789abcdef","sequence":0,"data_b64":"AAAA"}),
        _line(f"pqc/result/stm32/{run_id}/complete", _complete("stm32", run_id, stm, 1, 1)),
        _line("pqc/instrument/energy/capture/complete", {"type":"complete","source":"energy","schema":1,"capture_id":"0123456789abcdef"}),
    ]) + "\n", encoding="utf-8")
    result = _parse_raw_stream(path, run_id, ("stm32",))
    assert result.passed
    assert result.completion_count == 1
    assert set(result.source_results) == {"stm32"}


def test_energy_is_not_a_common_run_scoped_required_source(tmp_path):
    run_id = "run-1"
    logical = b'{"timing":1}\n'
    path = tmp_path / "raw.ndjson"
    path.write_text("\n".join([
        _line(f"pqc/result/stm32/{run_id}/chunk", {"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":logical.hex()}),
        _line(f"pqc/result/stm32/{run_id}/complete", _complete("stm32", run_id, logical, 1, 1)),
    ]) + "\n", encoding="utf-8")
    result = _parse_raw_stream(path, run_id, ("stm32",))
    assert result.passed


def test_collector_accepts_mosquitto_json_transport_wrapper(tmp_path):
    run_id = "run-1"
    logical = b'{"timing":1}\n'
    topic = f"pqc/result/stm32/{run_id}/chunk"
    chunk = {
        "type": "chunk",
        "source": "stm32",
        "run_id": run_id,
        "sequence": 0,
        "data_hex": logical.hex(),
    }
    complete = _complete("stm32", run_id, logical, 1, 1)

    def wrapped_line(message_topic: str, message: dict, mid: int) -> str:
        return json.dumps({
            "topic": message_topic,
            "payload": {
                "tst": "2026-09-16T19:21:52.000000+1000",
                "topic": message_topic,
                "qos": 1,
                "retain": 0,
                "payloadlen": len(json.dumps(message)),
                "mid": mid,
                "payload": json.dumps(message, separators=(",", ":")),
            },
        })

    path = tmp_path / "raw.ndjson"
    path.write_text(
        "\n".join([
            wrapped_line(topic, chunk, 1),
            wrapped_line(f"pqc/result/stm32/{run_id}/complete", complete, 2),
        ]) + "\n",
        encoding="utf-8",
    )

    result = _parse_raw_stream(path, run_id)
    assert result.passed
    assert result.observed_chunk_count == 1
    assert result.completion_count == 1
    assert result.source_results["stm32"]["observed_record_count"] == 1

def test_common_topics_include_fixed_energy_capture_but_common_source_validation_stays_stm32_only():
    bundle = {"experiment": {"instruments": {"energy": {"profile": "esp32_ina228"}}}}
    assert result_topics(bundle, "r") == ("pqc/result/stm32/r/#", "pqc/instrument/energy/capture/#")
    assert expected_result_sources(bundle) == ("stm32",)


def test_repeat_energy_adds_one_boundary_epoch_to_stm32_completion_count():
    bundle = {
        "experiment": {
            "workload": {"iterations": {"handshakes_per_run": 7}},
            "instruments": {"energy": {"profile": "esp32_ina228"}},
        }
    }
    assert expected_completion_counts(bundle) == {"stm32": 8}


def test_collector_accepts_multiple_complete_boot_epochs_for_same_source(tmp_path):
    run_id = "run-reset"
    first = b'{"boot":1}\n'
    second = b'{"boot":2}\n'
    path = tmp_path / "raw.ndjson"
    path.write_text(
        "\n".join([
            _line(
                f"pqc/result/stm32/{run_id}/chunk",
                {"type": "chunk", "source": "stm32", "run_id": run_id, "sequence": 0, "data_hex": first.hex()},
            ),
            _line(
                f"pqc/result/stm32/{run_id}/complete",
                _complete("stm32", run_id, first, 1, 1),
            ),
            _line(
                f"pqc/result/stm32/{run_id}/chunk",
                {"type": "chunk", "source": "stm32", "run_id": run_id, "sequence": 0, "data_hex": second.hex()},
            ),
            _line(
                f"pqc/result/stm32/{run_id}/complete",
                _complete("stm32", run_id, second, 1, 1),
            ),
        ]) + "\n",
        encoding="utf-8",
    )

    result = _parse_raw_stream(path, run_id)

    assert result.passed
    assert result.completion_count == 2
    assert result.observed_chunk_count == 2
    assert result.expected_chunk_count == 2
    assert result.source_results["stm32"]["stream_count"] == 2
    assert [stream["observed_sha256"] for stream in result.source_results["stm32"]["streams"]] == [
        hashlib.sha256(first).hexdigest(),
        hashlib.sha256(second).hexdigest(),
    ]


def test_collector_rejects_unfinished_trailing_boot_epoch(tmp_path):
    run_id = "run-reset"
    first = b'{"boot":1}\n'
    second = b'{"boot":2}\n'
    path = tmp_path / "raw.ndjson"
    path.write_text(
        "\n".join([
            _line(
                f"pqc/result/stm32/{run_id}/chunk",
                {"type": "chunk", "source": "stm32", "run_id": run_id, "sequence": 0, "data_hex": first.hex()},
            ),
            _line(
                f"pqc/result/stm32/{run_id}/complete",
                _complete("stm32", run_id, first, 1, 1),
            ),
            _line(
                f"pqc/result/stm32/{run_id}/chunk",
                {"type": "chunk", "source": "stm32", "run_id": run_id, "sequence": 0, "data_hex": second.hex()},
            ),
        ]) + "\n",
        encoding="utf-8",
    )

    result = _parse_raw_stream(path, run_id)

    assert not result.passed
    assert result.completion_count == 1
    assert any("completion record missing" in reason for reason in result.failure_reasons)


def test_repeat_workload_sets_expected_stm32_completion_count():
    bundle = {
        "experiment": {
            "workload": {"iterations": {"handshakes_per_run": 7}},
            "instruments": {},
        }
    }
    assert expected_completion_counts(bundle) == {"stm32": 7}


def test_collector_requires_exact_repeat_epoch_count(tmp_path):
    run_id = "run-repeat"
    logical = b'{"iteration":0}\n'
    lines = []
    for _ in range(2):
        lines.extend([
            _line(
                f"pqc/result/stm32/{run_id}/chunk",
                {"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":logical.hex()},
            ),
            _line(
                f"pqc/result/stm32/{run_id}/complete",
                _complete("stm32", run_id, logical, 1, 1),
            ),
        ])
    path = tmp_path / "raw.ndjson"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _parse_raw_stream(path, run_id, ("stm32",), {"stm32": 3})

    assert not result.passed
    assert result.source_results["stm32"]["completion_count"] == 2
    assert any("completion count mismatch" in reason for reason in result.failure_reasons)


def _multi_epoch_stream(tmp_path, *, corrupt_second=False):
    run_id = "run-ota-epochs"
    path = tmp_path / "ota-epochs.ndjson"
    lines = []
    for number in (1, 2):
        logical = (json.dumps({"boot": number}) + "\n").encode()
        lines.append(_line(
            f"pqc/result/stm32/{run_id}/chunk",
            {"type": "chunk", "source": "stm32", "run_id": run_id,
             "sequence": 0, "data_hex": logical.hex()},
        ))
        complete = _complete("stm32", run_id, logical, 1, 1)
        if corrupt_second and number == 2:
            complete["logical_sha256"] = "0" * 64
        lines.append(_line(f"pqc/result/stm32/{run_id}/complete", complete))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, run_id


def test_ota_collector_accepts_two_independently_validated_boot_epochs(tmp_path):
    path, run_id = _multi_epoch_stream(tmp_path)
    result = _parse_raw_stream(
        path, run_id, expected_completion_counts={"stm32": 1},
        allow_additional_stm32_epochs=True,
    )
    assert result.passed
    assert result.completion_count == 2
    assert result.source_results["stm32"]["stream_count"] == 2
    assert all(stream["passed"] for stream in result.source_results["stm32"]["streams"])


def test_ota_collector_rejects_invalid_additional_boot_epoch(tmp_path):
    path, run_id = _multi_epoch_stream(tmp_path, corrupt_second=True)
    result = _parse_raw_stream(
        path, run_id, expected_completion_counts={"stm32": 1},
        allow_additional_stm32_epochs=True,
    )
    assert not result.passed
    assert result.completion_count == 2
    assert result.source_results["stm32"]["streams"][0]["passed"]
    assert not result.source_results["stm32"]["streams"][1]["passed"]
    assert any("stream 1: logical buffer hash mismatch" in reason for reason in result.failure_reasons)


def test_non_ota_collector_rejects_additional_boot_epoch(tmp_path):
    path, run_id = _multi_epoch_stream(tmp_path)
    result = _parse_raw_stream(path, run_id, expected_completion_counts={"stm32": 1})
    assert not result.passed
    assert any("completion count mismatch: expected 1, observed 2" in reason for reason in result.failure_reasons)


def test_ota_collector_still_requires_at_least_one_completion(tmp_path):
    run_id = "run-ota-empty"
    path = tmp_path / "empty.ndjson"
    path.write_text("", encoding="utf-8")
    result = _parse_raw_stream(
        path, run_id, expected_completion_counts={"stm32": 1},
        allow_additional_stm32_epochs=True,
    )
    assert not result.passed
    assert "required stm32 source missing" in result.failure_reasons
