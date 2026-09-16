from __future__ import annotations

import hashlib
import json

from framework.result_collector import _parse_raw_stream, expected_result_sources, result_topics


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


def test_collector_validates_each_source_in_its_own_sequence_namespace(tmp_path):
    run_id='run-1'
    stm=b'{"timing":1}\n'
    energy=b'{"sample":1}\n{"sample":2}\n'
    path=tmp_path/'raw.ndjson'
    path.write_text('\n'.join([
        _line(f'pqc/result/stm32/{run_id}/chunk',{"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":stm.hex()}),
        _line(f'pqc/instrument/energy/{run_id}/chunk',{"type":"chunk","source":"energy","run_id":run_id,"sequence":0,"data_hex":energy.hex()}),
        _line(f'pqc/result/stm32/{run_id}/complete',_complete('stm32',run_id,stm,1,1)),
        _line(f'pqc/instrument/energy/{run_id}/complete',_complete('energy',run_id,energy,2,1)),
    ])+'\n',encoding='utf-8')
    result=_parse_raw_stream(path,run_id,("stm32","energy"))
    assert result.passed
    assert result.completion_count == 2
    assert result.observed_chunk_count == 2
    assert set(result.source_results) == {'stm32','energy'}
    assert result.source_results['stm32']['passed'] is True
    assert result.source_results['energy']['passed'] is True


def test_collector_rejects_source_topic_mismatch(tmp_path):
    run_id='run-1'; path=tmp_path/'raw.ndjson'
    path.write_text(_line(
        f'pqc/instrument/energy/{run_id}/chunk',
        {"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":"610a"},
    )+'\n',encoding='utf-8')
    result=_parse_raw_stream(path,run_id)
    assert not result.passed
    assert any('source/topic mismatch' in reason for reason in result.failure_reasons)



def test_configured_instrument_is_a_required_result_source(tmp_path):
    run_id='run-1'
    logical=b'{"timing":1}\n'
    path=tmp_path/'raw.ndjson'
    path.write_text('\n'.join([
        _line(f'pqc/result/stm32/{run_id}/chunk',{"type":"chunk","source":"stm32","run_id":run_id,"sequence":0,"data_hex":logical.hex()}),
        _line(f'pqc/result/stm32/{run_id}/complete',_complete('stm32',run_id,logical,1,1)),
    ])+'\n',encoding='utf-8')
    result=_parse_raw_stream(path,run_id,("stm32","energy"))
    assert not result.passed
    assert 'required energy source missing' in result.failure_reasons


def test_common_topics_include_stm32_and_enabled_instruments():
    bundle={"experiment":{"instruments":{"energy":{"profile":"esp32_ina228"}}}}
    assert result_topics(bundle,"r") == ("pqc/result/stm32/r/#","pqc/instrument/energy/r/#")
    assert expected_result_sources(bundle) == ("stm32","energy")
