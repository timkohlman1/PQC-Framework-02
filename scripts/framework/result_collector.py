"""Raw MQTT result collection and transport-integrity validation.

This module deliberately does not parse scientific timing, memory, TLS or energy
values. It validates only the common reporting envelope and retains the raw
MQTT topic/payload stream as run evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from framework.ssh_target import gateway_ssh_target
from framework.uart import CommandExecution

RAW_RESULT_STREAM_NAME = "mqtt-reporting-raw.ndjson"
RESULT_COLLECTOR_LOG_NAME = "mqtt-reporting-collector.log"

@dataclass(frozen=True)
class GatewayResultCollector:
    gateway_target: str
    run_id: str
    pid: int
    remote_stream_path: str
    topics: tuple[str, ...]
    reporting_host: str
    reporting_port: int
    expected_sources: tuple[str, ...]

@dataclass(frozen=True)
class ResultCollectorValidation:
    passed: bool
    record_count: int
    completion_count: int
    duplicate_sequences: tuple[int, ...]
    missing_sequences: tuple[int, ...]
    expected_chunk_count: int | None
    observed_chunk_count: int
    expected_record_count: int | None
    expected_sha256: str | None
    observed_sha256: str | None
    source_results: dict[str, dict[str, Any]]
    failure_reasons: tuple[str, ...]

@dataclass(frozen=True)
class GatewayResultCollectorResult:
    return_code: int
    raw_stream_path: Path | None
    log_path: Path
    validation: ResultCollectorValidation
    failure_reason: str | None


def _run(command: list[str], *, cwd: Path) -> CommandExecution:
    started=time.perf_counter()
    completed=subprocess.run(command,cwd=cwd,text=True,encoding="utf-8",errors="replace",capture_output=True,check=False)
    return CommandExecution(command,completed.returncode,completed.stdout,completed.stderr,time.perf_counter()-started)


def reporting_config(bundle: dict[str, dict[str, Any]]) -> tuple[str,int]:
    experiment=bundle.get("experiment",{})
    reporting=experiment.get("reporting",{}) if isinstance(experiment,dict) else {}
    host=str(reporting.get("host") or bundle.get("host",{}).get("network",{}).get("address") or bundle.get("host",{}).get("alias") or "127.0.0.1")
    port=int(reporting.get("port",1886))
    return host,port


def result_topics(bundle: dict[str, dict[str, Any]], run_id: str) -> tuple[str,...]:
    topics=[f"pqc/result/stm32/{run_id}/#"]
    instruments=bundle.get("experiment",{}).get("instruments",{})
    if isinstance(instruments,dict):
        for kind in sorted(instruments):
            if instruments[kind] is not None:
                topics.append(f"pqc/instrument/{kind}/{run_id}/#")
    return tuple(topics)


def expected_result_sources(bundle: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    sources=["stm32"]
    instruments=bundle.get("experiment",{}).get("instruments",{})
    if isinstance(instruments,dict):
        for kind in sorted(instruments):
            if instruments[kind] is not None:
                sources.append(kind)
    return tuple(sources)


def start_gateway_result_collector(*, bundle: dict[str,dict[str,Any]], repo_root: Path, result_dir: Path, run_id: str, runner: Callable[...,CommandExecution]=_run) -> tuple[GatewayResultCollector|None,CommandExecution]:
    target=gateway_ssh_target(bundle["host"])
    host,port=reporting_config(bundle)
    safe=re.sub(r"[^A-Za-z0-9_.-]","_",run_id)
    remote=f"/tmp/pqc-{safe}-reporting.ndjson"
    topics=result_topics(bundle,run_id)
    expected_sources=expected_result_sources(bundle)
    topic_args=" ".join(f"-t {shlex.quote(topic)}" for topic in topics)
    # mosquitto_sub's -F format gives one JSON object per received MQTT message.
    fmt=r'{"topic":"%t","payload":%j}'
    script=(
        "command -v mosquitto_sub >/dev/null 2>&1 || exit 127; "
        "command -v mosquitto_pub >/dev/null 2>&1 || exit 127; "
        f"rm -f {shlex.quote(remote)}; "
        f"nohup mosquitto_sub -h {shlex.quote(host)} -p {port} -q 1 {topic_args} -F {shlex.quote(fmt)} >{shlex.quote(remote)} 2>&1 </dev/null & "
        "pid=$!; sleep 1; kill -0 $pid 2>/dev/null || exit 1; "
        f"mosquitto_pub -h {shlex.quote(host)} -p {port} -q 1 -r -t pqc/control/run-id/current -m {shlex.quote(run_id)}; "
        "printf '%s\\n' $pid"
    )
    command=["ssh",target,f"sh -c {shlex.quote(script)}"]
    execution=runner(command,cwd=repo_root)
    if execution.return_code!=0:
        return None,execution
    try: pid=int(execution.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError):
        return None,CommandExecution(execution.command,1,execution.stdout,execution.stderr+"\ncollector did not return pid\n",execution.duration_seconds)
    return GatewayResultCollector(target,run_id,pid,remote,topics,host,port,expected_sources),execution


def _topic_source(topic: str, run_id: str) -> str | None:
    parts=topic.split("/")
    if len(parts) >= 5 and parts[:3] == ["pqc","result","stm32"] and parts[3] == run_id:
        return "stm32"
    if len(parts) >= 5 and parts[:2] == ["pqc","instrument"] and parts[3] == run_id:
        return parts[2]
    return None


def _parse_raw_stream(path: Path, run_id: str, expected_sources: tuple[str, ...] = ("stm32",)) -> ResultCollectorValidation:
    sources: dict[str, dict[str, Any]]={}
    failures: list[str]=[]
    records=0

    for lineno,line in enumerate(path.read_text(encoding="utf-8",errors="replace").splitlines(),1):
        if not line.strip():
            continue
        try:
            outer=json.loads(line)
            topic=str(outer.get("topic", ""))
            payload=outer.get("payload")
            obj=json.loads(payload) if isinstance(payload,str) else payload
        except Exception as exc:
            failures.append(f"line {lineno}: invalid JSON envelope: {exc}")
            continue
        if not isinstance(obj,dict):
            failures.append(f"line {lineno}: payload is not an object")
            continue
        if obj.get("run_id") != run_id:
            failures.append(f"line {lineno}: run_id mismatch")
            continue
        source=str(obj.get("source", "")).strip()
        topic_source=_topic_source(topic,run_id)
        if not source:
            failures.append(f"line {lineno}: source missing")
            continue
        if topic_source is None:
            failures.append(f"line {lineno}: topic is outside the reporting namespace")
            continue
        if source != topic_source:
            failures.append(f"line {lineno}: source/topic mismatch")
            continue

        state=sources.setdefault(source,{"chunks":{},"duplicates":[],"completions":[],"records":0})
        kind=obj.get("type")
        if kind == "chunk":
            try:
                seq=int(obj["sequence"])
                encoded=str(obj["data_hex"])
                data=bytes.fromhex(encoded)
            except Exception as exc:
                failures.append(f"line {lineno}: invalid chunk: {exc}")
                continue
            if seq in state["chunks"]:
                state["duplicates"].append(seq)
            else:
                state["chunks"][seq]=data
        elif kind == "complete":
            state["completions"].append(obj)
        else:
            failures.append(f"line {lineno}: unsupported record type {kind!r}")
            continue
        state["records"] += 1
        records += 1

    source_results: dict[str,dict[str,Any]]={}
    total_completions=0
    total_chunks=0
    expected_chunks_total=0
    expected_records_total=0
    have_expected_chunks=True
    have_expected_records=True

    for source,state in sorted(sources.items()):
        source_failures: list[str]=[]
        chunks: dict[int,bytes]=state["chunks"]
        duplicate=sorted(set(state["duplicates"]))
        completions: list[dict[str,Any]]=state["completions"]
        total_completions += len(completions)
        total_chunks += len(chunks)
        completion=completions[-1] if completions else None
        expected_chunks=int(completion["chunk_count"]) if completion and "chunk_count" in completion else None
        expected_records=int(completion["record_count"]) if completion and "record_count" in completion else None
        expected_sha=str(completion.get("logical_sha256")) if completion and completion.get("logical_sha256") else None
        if expected_chunks is None:
            have_expected_chunks=False
        else:
            expected_chunks_total += expected_chunks
        if expected_records is None:
            have_expected_records=False
        else:
            expected_records_total += expected_records
        missing=[i for i in range(expected_chunks or 0) if i not in chunks] if expected_chunks is not None else []
        logical=b"".join(chunks[i] for i in sorted(chunks))
        observed_sha=hashlib.sha256(logical).hexdigest() if chunks or expected_chunks == 0 else None
        logical_record_count=sum(1 for line in logical.splitlines() if line.strip())

        if len(completions) != 1:
            source_failures.append(f"expected exactly one completion record, observed {len(completions)}")
        if duplicate:
            source_failures.append("duplicate chunk sequence(s)")
        if missing:
            source_failures.append("missing chunk sequence(s)")
        if expected_chunks is not None and len(chunks) != expected_chunks:
            source_failures.append("chunk count mismatch")
        if expected_records is not None and logical_record_count != expected_records:
            source_failures.append("logical record count mismatch")
        if expected_sha is not None and observed_sha != expected_sha:
            source_failures.append("logical buffer hash mismatch")
        if completion and "logical_bytes" in completion and len(logical) != int(completion["logical_bytes"]):
            source_failures.append("logical byte count mismatch")

        source_results[source]={
            "passed": not source_failures,
            "observed_chunk_count": len(chunks),
            "expected_chunk_count": expected_chunks,
            "observed_record_count": logical_record_count,
            "expected_record_count": expected_records,
            "completion_count": len(completions),
            "duplicate_sequences": duplicate,
            "missing_sequences": missing,
            "expected_sha256": expected_sha,
            "observed_sha256": observed_sha,
            "failure_reasons": source_failures,
        }
        failures.extend(f"{source}: {reason}" for reason in source_failures)

    for expected_source in expected_sources:
        if expected_source not in sources:
            failures.append(f"required {expected_source} source missing")
    unexpected_sources=sorted(set(sources).difference(expected_sources))
    if unexpected_sources:
        failures.append("unexpected result source(s): " + ", ".join(unexpected_sources))
    if not sources:
        failures.append("no result sources observed")

    only_source=next(iter(source_results.values())) if len(source_results)==1 else None
    duplicate_all=tuple(sorted({seq for result in source_results.values() for seq in result["duplicate_sequences"]}))
    missing_all=tuple(sorted({seq for result in source_results.values() for seq in result["missing_sequences"]}))
    return ResultCollectorValidation(
        not failures,
        records,
        total_completions,
        duplicate_all,
        missing_all,
        expected_chunks_total if have_expected_chunks else None,
        total_chunks,
        expected_records_total if have_expected_records else None,
        only_source["expected_sha256"] if only_source else None,
        only_source["observed_sha256"] if only_source else None,
        source_results,
        tuple(failures),
    )


def stop_and_collect_gateway_result_collector(*, collector: GatewayResultCollector, repo_root: Path, result_dir: Path, runner: Callable[...,CommandExecution]=_run) -> GatewayResultCollectorResult:
    stop_script=f"kill -INT {collector.pid} 2>/dev/null || true; sleep 1; test -f {shlex.quote(collector.remote_stream_path)}"
    stop=runner(["ssh",collector.gateway_target,f"sh -c {shlex.quote(stop_script)}"],cwd=repo_root)
    raw=result_dir/RAW_RESULT_STREAM_NAME
    copy=runner(["scp",f"{collector.gateway_target}:{collector.remote_stream_path}",str(raw)],cwd=repo_root)
    runner(["ssh",collector.gateway_target,f"rm -f {shlex.quote(collector.remote_stream_path)}"],cwd=repo_root)
    if stop.return_code!=0 or copy.return_code!=0 or not raw.is_file():
        validation=ResultCollectorValidation(False,0,0,tuple(),tuple(),None,0,None,None,None,{},("collector stream unavailable",))
        reason="result collector stop/copy failed"
    else:
        validation=_parse_raw_stream(raw,collector.run_id,collector.expected_sources); reason=None if validation.passed else "; ".join(validation.failure_reasons)
    log=result_dir/RESULT_COLLECTOR_LOG_NAME
    log.write_text(json.dumps({"run_id":collector.run_id,"topics":collector.topics,"expected_sources":collector.expected_sources,"stop_return_code":stop.return_code,"copy_return_code":copy.return_code,"validation":validation.__dict__},indent=2,sort_keys=True,default=list)+"\n",encoding="utf-8")
    return GatewayResultCollectorResult(0 if reason is None else 1,raw if raw.is_file() else None,log,validation,reason)
