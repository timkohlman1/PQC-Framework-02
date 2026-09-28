"""Gateway-side passive energy wait protocol tests."""
from __future__ import annotations

import hashlib
import json

import pytest

from framework.energy_gateway import main

pytestmark = pytest.mark.integration


def _line(topic: str, payload: dict) -> str:
    return json.dumps({"topic": topic, "payload": payload}) + "\n"


def _stm32_lines(run_id="run", s0=10_000_000, s1=11_000_000):
    record = {
        "context": "energy_boundary",
        "text": (
            "PQC_ENERGY_BOUNDARY scope=experiment "
            f"s0_us={s0} s1_us={s1} valid=1 clock=TIM2 counter_hz=1000000 "
            "timestamp_convention=before_gpio_write"
        ),
    }
    logical = (json.dumps(record) + "\n").encode()
    return [
        _line(
            f"pqc/result/stm32/{run_id}/chunk",
            {"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":logical.hex()},
        ),
        _line(
            f"pqc/result/stm32/{run_id}/complete",
            {"type":"complete","source":"stm32","run_id":run_id,"chunk_count":1,
             "logical_bytes":len(logical),"logical_sha256":hashlib.sha256(logical).hexdigest()},
        ),
    ]


def _energy_complete(capture_id="0123456789abcdef", e0=4_000_000, e1=5_000_000):
    return _line(
        "pqc/instrument/energy/capture/complete",
        {"type":"complete","source":"energy","schema":1,"capture_id":capture_id,"e0_us":e0,"e1_us":e1},
    )


def test_wait_returns_duration_compatible_passive_capture_without_publishing_commands(tmp_path, capsys):
    stream = tmp_path / "raw.ndjson"
    stream.write_text(
        _energy_complete("1111111111111111", 1_000_000, 3_000_000)
        + "".join(_stm32_lines())
        + _energy_complete(),
        encoding="utf-8",
    )
    assert main({"stream": str(stream), "timeout": 0.2, "run_id": "run"}) == 0
    output = capsys.readouterr().out
    completion = json.loads(output.strip())
    assert completion["capture_id"] == "0123456789abcdef"


def test_wait_times_out_when_capture_duration_does_not_match_stm32_window(tmp_path, capsys):
    stream = tmp_path / "raw.ndjson"
    stream.write_text("".join(_stm32_lines()) + _energy_complete(e0=1_000_000, e1=3_000_000), encoding="utf-8")
    assert main({"stream": str(stream), "timeout": 0.05, "run_id": "run"}) == 1
    assert "timed out" in capsys.readouterr().out.lower()


def test_wait_ignores_stm32_boundary_from_another_run(tmp_path, capsys):
    stream = tmp_path / "raw.ndjson"
    stream.write_text("".join(_stm32_lines("other")) + _energy_complete(), encoding="utf-8")
    assert main({"stream": str(stream), "timeout": 0.05, "run_id": "run"}) == 1
    assert "timed out" in capsys.readouterr().out.lower()


def test_wait_tolerates_stream_file_appearing_after_poll_starts(tmp_path, monkeypatch, capsys):
    stream = tmp_path / "late.ndjson"
    import framework.energy_gateway as gateway

    real_sleep = gateway.time.sleep
    calls = {"count": 0}

    def sleep(seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            stream.write_text("".join(_stm32_lines()) + _energy_complete(), encoding="utf-8")
        real_sleep(min(seconds, 0.001))

    monkeypatch.setattr(gateway.time, "sleep", sleep)
    assert main({"stream": str(stream), "timeout": 0.2, "run_id": "run"}) == 0
    assert json.loads(capsys.readouterr().out.strip())["source"] == "energy"
