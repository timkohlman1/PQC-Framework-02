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
    expected_completion_counts: dict[str, int]
    allow_additional_stm32_epochs: bool = False

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
            if instruments[kind] is None:
                continue
            if kind == "energy":
                # Passive appliance: fixed topic, no run ID or command plane.
                topics.append("pqc/instrument/energy/capture/#")
            else:
                topics.append(f"pqc/instrument/{kind}/{run_id}/#")
    return tuple(topics)


def expected_result_sources(bundle: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    sources=["stm32"]
    instruments=bundle.get("experiment",{}).get("instruments",{})
    if isinstance(instruments,dict):
        for kind in sorted(instruments):
            if instruments[kind] is not None and kind != "energy":
                sources.append(kind)
    return tuple(sources)


def expected_completion_counts(bundle: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts={source:1 for source in expected_result_sources(bundle)}
    experiment=bundle.get("experiment",{})
    workload=experiment.get("workload",{}) if isinstance(experiment,dict) else {}
    iterations=workload.get("iterations",{}) if isinstance(workload,dict) else {}
    if isinstance(iterations,dict) and "handshakes_per_run" in iterations:
        counts["stm32"]=int(iterations["handshakes_per_run"])
        instruments=experiment.get("instruments",{}) if isinstance(experiment,dict) else {}
        if isinstance(instruments,dict) and instruments.get("energy") is not None:
            # Repeated TLS emits one extra tiny STM32 epoch containing the
            # experiment-wide TIM2/GPIO anchors after the handshake epochs.
            counts["stm32"] += 1
    return counts


def start_gateway_result_collector(*, bundle: dict[str,dict[str,Any]], repo_root: Path, result_dir: Path, run_id: str, allow_additional_stm32_epochs: bool = False, runner: Callable[...,CommandExecution]=_run) -> tuple[GatewayResultCollector|None,CommandExecution]:
    target=gateway_ssh_target(bundle["host"])
    host,port=reporting_config(bundle)
    safe=re.sub(r"[^A-Za-z0-9_.-]","_",run_id)
    remote=f"/tmp/pqc-{safe}-reporting.ndjson"
    topics=result_topics(bundle,run_id)
    expected_sources=expected_result_sources(bundle)
    expected_completions=expected_completion_counts(bundle)
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
    return GatewayResultCollector(target,run_id,pid,remote,topics,host,port,expected_sources,expected_completions,allow_additional_stm32_epochs),execution


def _topic_source(topic: str, run_id: str) -> str | None:
    parts=topic.split("/")
    if len(parts) >= 5 and parts[:3] == ["pqc","result","stm32"] and parts[3] == run_id:
        return "stm32"
    if len(parts) >= 5 and parts[:2] == ["pqc","instrument"] and parts[3] == run_id:
        return parts[2]
    return None


def _parse_raw_stream(
    path: Path,
    run_id: str,
    expected_sources: tuple[str, ...] = ("stm32",),
    expected_completion_counts: dict[str, int] | None = None,
    *,
    allow_additional_stm32_epochs: bool = False,
) -> ResultCollectorValidation:
    """Validate one or more complete result epochs for each reporting source.

    A reset-spanning run can legitimately contain multiple result streams from
    the same physical source.  Each stream starts its sequence namespace at zero
    and is closed by its own completion record.  Integrity is therefore checked
    independently per completion-bounded epoch instead of treating a later boot
    as duplicate chunks from the first boot.
    """
    sources: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    records = 0

    def source_state(source: str) -> dict[str, Any]:
        return sources.setdefault(
            source,
            {
                "current_chunks": {},
                "current_duplicates": [],
                "streams": [],
                "trailing_failures": [],
                "records": 0,
            },
        )

    def validate_stream(
        source: str,
        chunks: dict[int, bytes],
        duplicate_sequences: list[int],
        completion: dict[str, Any],
        stream_index: int,
    ) -> dict[str, Any]:
        stream_failures: list[str] = []
        duplicate = sorted(set(duplicate_sequences))
        try:
            expected_chunks = int(completion["chunk_count"]) if "chunk_count" in completion else None
            expected_records = int(completion["record_count"]) if "record_count" in completion else None
            expected_bytes = int(completion["logical_bytes"]) if "logical_bytes" in completion else None
        except (TypeError, ValueError) as exc:
            stream_failures.append(f"invalid completion metadata: {exc}")
            expected_chunks = None
            expected_records = None
            expected_bytes = None
        expected_sha = str(completion.get("logical_sha256")) if completion.get("logical_sha256") else None
        missing = [i for i in range(expected_chunks or 0) if i not in chunks] if expected_chunks is not None else []
        logical = b"".join(chunks[i] for i in sorted(chunks))
        observed_sha = hashlib.sha256(logical).hexdigest() if chunks or expected_chunks == 0 else None
        logical_record_count = sum(1 for line in logical.splitlines() if line.strip())

        if duplicate:
            stream_failures.append("duplicate chunk sequence(s)")
        if missing:
            stream_failures.append("missing chunk sequence(s)")
        if expected_chunks is not None and len(chunks) != expected_chunks:
            stream_failures.append("chunk count mismatch")
        if expected_records is not None and logical_record_count != expected_records:
            stream_failures.append("logical record count mismatch")
        if expected_sha is not None and observed_sha != expected_sha:
            stream_failures.append("logical buffer hash mismatch")
        if expected_bytes is not None and len(logical) != expected_bytes:
            stream_failures.append("logical byte count mismatch")

        return {
            "stream_index": stream_index,
            "passed": not stream_failures,
            "observed_chunk_count": len(chunks),
            "expected_chunk_count": expected_chunks,
            "observed_record_count": logical_record_count,
            "expected_record_count": expected_records,
            "expected_logical_bytes": expected_bytes,
            "observed_logical_bytes": len(logical),
            "duplicate_sequences": duplicate,
            "missing_sequences": missing,
            "expected_sha256": expected_sha,
            "observed_sha256": observed_sha,
            "failure_reasons": stream_failures,
        }

    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            outer = json.loads(line)
            topic = str(outer.get("topic", ""))
            payload = outer.get("payload")
            # mosquitto_sub %j emits a JSON metadata object whose own ``payload``
            # member contains the application payload as a JSON string. Keep the
            # raw capture unchanged, but unwrap that transport metadata for
            # integrity validation.
            if isinstance(payload, dict) and "payload" in payload:
                mqtt_payload = payload.get("payload")
                obj = json.loads(mqtt_payload) if isinstance(mqtt_payload, str) else mqtt_payload
            else:
                obj = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as exc:
            failures.append(f"line {lineno}: invalid JSON envelope: {exc}")
            continue
        if not isinstance(obj, dict):
            failures.append(f"line {lineno}: payload is not an object")
            continue
        if topic.startswith("pqc/instrument/energy/capture/"):
            # Energy uses its own fixed-topic binary integrity contract and is
            # validated separately by framework.energy_evidence.
            continue
        if obj.get("run_id") != run_id:
            failures.append(f"line {lineno}: run_id mismatch")
            continue
        source = str(obj.get("source", "")).strip()
        topic_source = _topic_source(topic, run_id)
        if not source:
            failures.append(f"line {lineno}: source missing")
            continue
        if topic_source is None:
            failures.append(f"line {lineno}: topic is outside the reporting namespace")
            continue
        if source != topic_source:
            failures.append(f"line {lineno}: source/topic mismatch")
            continue

        state = source_state(source)
        kind = obj.get("type")
        if kind == "chunk":
            try:
                seq = int(obj["sequence"])
                from framework.energy_evidence import chunk_bytes
                data = chunk_bytes(obj)
            except Exception as exc:
                failures.append(f"line {lineno}: invalid chunk: {exc}")
                continue
            if seq in state["current_chunks"]:
                state["current_duplicates"].append(seq)
            else:
                state["current_chunks"][seq] = data
        elif kind == "complete":
            stream_index = len(state["streams"])
            stream = validate_stream(
                source,
                state["current_chunks"],
                state["current_duplicates"],
                obj,
                stream_index,
            )
            state["streams"].append(stream)
            state["current_chunks"] = {}
            state["current_duplicates"] = []
        else:
            failures.append(f"line {lineno}: unsupported record type {kind!r}")
            continue
        state["records"] += 1
        records += 1

    source_results: dict[str, dict[str, Any]] = {}
    total_completions = 0
    total_chunks = 0
    expected_chunks_total = 0
    expected_records_total = 0
    have_expected_chunks = True
    have_expected_records = True

    for source, state in sorted(sources.items()):
        source_failures: list[str] = []
        streams: list[dict[str, Any]] = list(state["streams"])

        if state["current_chunks"] or state["current_duplicates"]:
            trailing = {
                "stream_index": len(streams),
                "passed": False,
                "observed_chunk_count": len(state["current_chunks"]),
                "expected_chunk_count": None,
                "observed_record_count": sum(
                    1
                    for line in b"".join(
                        state["current_chunks"][i] for i in sorted(state["current_chunks"])
                    ).splitlines()
                    if line.strip()
                ),
                "expected_record_count": None,
                "expected_logical_bytes": None,
                "observed_logical_bytes": sum(len(value) for value in state["current_chunks"].values()),
                "duplicate_sequences": sorted(set(state["current_duplicates"])),
                "missing_sequences": [],
                "expected_sha256": None,
                "observed_sha256": None,
                "failure_reasons": ["completion record missing"],
            }
            streams.append(trailing)

        if not streams:
            source_failures.append("expected at least one completion record, observed 0")

        for stream in streams:
            stream_index = int(stream["stream_index"])
            for reason in stream["failure_reasons"]:
                source_failures.append(f"stream {stream_index}: {reason}")

        total_completions += len(state["streams"])
        total_chunks += sum(int(stream["observed_chunk_count"]) for stream in streams)

        for stream in state["streams"]:
            expected_chunks = stream["expected_chunk_count"]
            expected_records = stream["expected_record_count"]
            if expected_chunks is None:
                have_expected_chunks = False
            else:
                expected_chunks_total += int(expected_chunks)
            if expected_records is None:
                have_expected_records = False
            else:
                expected_records_total += int(expected_records)

        duplicate = sorted(
            {
                seq
                for stream in streams
                for seq in stream["duplicate_sequences"]
            }
        )
        missing = sorted(
            {
                seq
                for stream in streams
                for seq in stream["missing_sequences"]
            }
        )

        single_complete = state["streams"][0] if len(state["streams"]) == 1 and len(streams) == 1 else None
        if expected_completion_counts is not None and source in expected_completion_counts:
            expected_completions = int(expected_completion_counts[source])
            observed_completions = len(state["streams"])
            # An OTA plan may reset and run the application more than once.
            # Keep the minimum configured count, but never accept a malformed,
            # incomplete or hash-invalid additional stream. All non-OTA runs,
            # including repeated TLS workloads, retain exact count matching.
            if source == "stm32" and allow_additional_stm32_epochs:
                if observed_completions < expected_completions:
                    source_failures.append(
                        f"completion count below minimum: expected at least {expected_completions}, observed {observed_completions}"
                    )
            elif observed_completions != expected_completions:
                source_failures.append(
                    f"completion count mismatch: expected {expected_completions}, observed {observed_completions}"
                )

        source_results[source] = {
            "passed": not source_failures,
            "stream_count": len(state["streams"]),
            "observed_chunk_count": sum(int(stream["observed_chunk_count"]) for stream in streams),
            "expected_chunk_count": (
                sum(int(stream["expected_chunk_count"]) for stream in state["streams"])
                if state["streams"] and all(stream["expected_chunk_count"] is not None for stream in state["streams"])
                else None
            ),
            "observed_record_count": sum(int(stream["observed_record_count"]) for stream in streams),
            "expected_record_count": (
                sum(int(stream["expected_record_count"]) for stream in state["streams"])
                if state["streams"] and all(stream["expected_record_count"] is not None for stream in state["streams"])
                else None
            ),
            "completion_count": len(state["streams"]),
            "duplicate_sequences": duplicate,
            "missing_sequences": missing,
            "expected_sha256": single_complete["expected_sha256"] if single_complete else None,
            "observed_sha256": single_complete["observed_sha256"] if single_complete else None,
            "streams": streams,
            "failure_reasons": source_failures,
        }
        failures.extend(f"{source}: {reason}" for reason in source_failures)

    for expected_source in expected_sources:
        if expected_source not in sources:
            failures.append(f"required {expected_source} source missing")
    unexpected_sources = sorted(set(sources).difference(expected_sources))
    if unexpected_sources:
        failures.append("unexpected result source(s): " + ", ".join(unexpected_sources))
    if not sources:
        failures.append("no result sources observed")

    only_source = next(iter(source_results.values())) if len(source_results) == 1 else None
    duplicate_all = tuple(
        sorted(
            {
                seq
                for result in source_results.values()
                for seq in result["duplicate_sequences"]
            }
        )
    )
    missing_all = tuple(
        sorted(
            {
                seq
                for result in source_results.values()
                for seq in result["missing_sequences"]
            }
        )
    )
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
        validation=_parse_raw_stream(
            raw, collector.run_id, collector.expected_sources, collector.expected_completion_counts,
            allow_additional_stm32_epochs=collector.allow_additional_stm32_epochs,
        ); reason=None if validation.passed else "; ".join(validation.failure_reasons)
    log=result_dir/RESULT_COLLECTOR_LOG_NAME
    log.write_text(json.dumps({"run_id":collector.run_id,"topics":collector.topics,"expected_sources":collector.expected_sources,"allow_additional_stm32_epochs":collector.allow_additional_stm32_epochs,"stop_return_code":stop.return_code,"copy_return_code":copy.return_code,"validation":validation.__dict__},indent=2,sort_keys=True,default=list)+"\n",encoding="utf-8")
    return GatewayResultCollectorResult(0 if reason is None else 1,raw if raw.is_file() else None,log,validation,reason)
