"""First-class campaign execution above the normal experiment runner.

The campaign layer owns matrix ordering, firmware/preparation reuse, broker reuse,
condition retention, repetitions, resume state, and campaign cleanup. Individual
experiment preparation/runtime evidence remains owned by ``scripts/experiment.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from framework.config_resolver import ConfigResolver, ResolutionError

CAMPAIGN_SCHEMA_NAME = "pqc-campaign-execution"
CAMPAIGN_SCHEMA_VERSION = 1


class CampaignError(RuntimeError):
    """Raised when campaign execution cannot proceed safely."""


class CampaignCleanupError(CampaignError):
    """Shared infrastructure could not be removed safely."""


class GroupSetupError(CampaignError):
    """Preparation or broker setup prevents this firmware group from running."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _setup_step(stage: str, operation: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return operation(**kwargs)
    except CampaignCleanupError:
        raise
    except CampaignError as exc:
        raise GroupSetupError(stage, str(exc)) from exc


class RepetitionError(CampaignError):
    """A finished runtime attempt failed; subsequent repetitions may proceed."""

    def __init__(self, message: str, *, manifest: Path | None, return_code: int, log: Path):
        super().__init__(message)
        self.manifest = manifest
        self.return_code = return_code
        self.log = log


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("._") or "campaign"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"JSON file must contain an object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class ExecutionPolicy:
    repetitions: int
    reset_between_runs: str
    build: str
    flash: str
    experiment_broker: str
    reporting_broker: str
    condition: str
    evidence: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ExecutionPolicy":
        if not isinstance(value, dict):
            raise CampaignError("campaign execution policy must be a mapping")
        try:
            repetitions = int(value.get("repetitions", 0))
        except (TypeError, ValueError) as exc:
            raise CampaignError("execution.repetitions must be an integer") from exc
        if repetitions < 1:
            raise CampaignError("execution.repetitions must be at least 1")
        policy = cls(
            repetitions=repetitions,
            reset_between_runs=str(value.get("reset_between_runs", "")),
            build=str(value.get("build", "")),
            flash=str(value.get("flash", "")),
            experiment_broker=str(value.get("experiment_broker", value.get("broker", ""))),
            reporting_broker=str(value.get("reporting_broker", "")),
            condition=str(value.get("condition", "")),
            evidence=str(value.get("evidence", "")),
        )
        expected = {
            "build": "once_per_firmware_identity",
            "flash": "once_per_firmware_identity",
            "experiment_broker": "reuse_if_compatible",
            "reporting_broker": "always_available",
            "condition": "retain_within_condition",
            "evidence": "per_run",
        }
        for field, wanted in expected.items():
            actual = getattr(policy, field)
            if actual != wanted:
                raise CampaignError(f"execution.{field} must be '{wanted}', got {actual!r}")
        if policy.reset_between_runs not in {"hardware_reset", "none"}:
            raise CampaignError("execution.reset_between_runs must be 'hardware_reset' or 'none'")
        return policy

    def as_dict(self) -> dict[str, Any]:
        return {
            "repetitions": self.repetitions,
            "reset_between_runs": self.reset_between_runs,
            "build": self.build,
            "flash": self.flash,
            "experiment_broker": self.experiment_broker,
            "reporting_broker": self.reporting_broker,
            "condition": self.condition,
            "evidence": self.evidence,
        }


def validate_policy_against_case(
    *, policy: ExecutionPolicy, case: dict[str, Any], resolver: ConfigResolver
) -> None:
    """Reject policy/profile combinations before hardware side effects."""
    workload_id = str(case.get("selections", {}).get("workload", ""))
    workload = resolver.load_profile("workload", workload_id).data
    requires_fresh_boot = bool(
        workload.get("requires_fresh_boot")
        or (workload.get("execution") or {}).get("requires_fresh_boot")
        or (workload.get("iterations") or {}).get("requires_fresh_boot")
    )
    if policy.reset_between_runs == "none" and requires_fresh_boot:
        raise CampaignError(
            f"workload '{workload_id}' requires a fresh boot boundary; reset_between_runs=none is invalid"
        )


def group_cases_by_firmware_identity(cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for case in cases:
        firmware_identity = str(case.get("provenance", {}).get("firmware_identity", ""))
        if not firmware_identity:
            raise CampaignError(f"case {case.get('id')} has no firmware identity")
        if firmware_identity not in grouped:
            grouped[firmware_identity] = []
            order.append(firmware_identity)
        grouped[firmware_identity].append(case)
    return [{"firmware_identity": identity, "cases": grouped[identity]} for identity in order]


def condition_identity(case: dict[str, Any]) -> str:
    choices = case.get("choices", {})
    hashes = case.get("provenance", {}).get("profile_hashes", {})
    network_id = str(choices.get("network_condition", ""))
    return canonical_sha256({
        "network_condition": network_id,
        "profile_hash": hashes.get(f"network_condition:{network_id}"),
    })


def broker_identity(bundle: dict[str, dict[str, Any]], case: dict[str, Any]) -> str:
    mqtt = bundle.get("experiment", {}).get("mqtt", {})
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    broker = mqtt.get("broker", {}) if isinstance(mqtt, dict) else {}
    services = case.get("selections", {}).get("services", {})
    hashes = case.get("provenance", {}).get("profile_hashes", {})
    experiment_service = str(services.get("experiment_broker", ""))
    return canonical_sha256({
        "service": experiment_service,
        "service_hash": hashes.get(f"service:mqtt_broker:{experiment_service}"),
        "broker_profile": mqtt.get("broker_profile") if isinstance(mqtt, dict) else None,
        "listener": broker,
        "tls": tls,
    })


def preparation_firmware_sha256(manifest_path: Path) -> str:
    manifest = _read_json(manifest_path)
    firmware = manifest.get("firmware", {})
    candidate = firmware.get("sha256") if isinstance(firmware, dict) else None
    if isinstance(candidate, str) and candidate:
        return candidate
    provenance_path = manifest_path.parent / "run-provenance.json"
    if provenance_path.is_file():
        provenance = _read_json(provenance_path)
        records = provenance.get("records", {})
        firmware = records.get("firmware", {}) if isinstance(records, dict) else {}
        candidate = firmware.get("sha256") if isinstance(firmware, dict) else None
        if isinstance(candidate, str) and candidate:
            return candidate
    raise CampaignError(f"preparation has no validated firmware SHA-256: {manifest_path}")


def validate_preparation_manifest(manifest_path: Path, *, expected_firmware_identity: str) -> str:
    manifest = _read_json(manifest_path)
    run = manifest.get("run", {})
    if not isinstance(run, dict) or run.get("return_code") != 0:
        raise CampaignError(f"preparation did not complete successfully: {manifest_path}")
    final_index = manifest.get("final_index", {})
    if not isinstance(final_index, dict) or final_index.get("status") != "finalized":
        raise CampaignError(f"preparation manifest is not finalized: {manifest_path}")
    configuration = manifest.get("configuration", {})
    actual_identity = configuration.get("firmware_identity") if isinstance(configuration, dict) else None
    if actual_identity != expected_firmware_identity:
        raise CampaignError(
            f"preparation firmware identity mismatch: expected {expected_firmware_identity}, got {actual_identity}"
        )
    return preparation_firmware_sha256(manifest_path)


def validate_completed_run(
    manifest_path: Path,
    *,
    campaign_id: str,
    case_id: str,
    condition_id: str,
    repetition_index: int,
    firmware_sha256: str,
) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        manifest = _read_json(manifest_path)
    except CampaignError:
        return False
    run = manifest.get("run", {})
    if not isinstance(run, dict) or run.get("return_code") != 0:
        return False
    final_index = manifest.get("final_index", {})
    if not isinstance(final_index, dict) or final_index.get("status") != "finalized":
        return False
    acceptance = manifest.get("capture_acceptance", {})
    if not isinstance(acceptance, dict) or acceptance.get("accepted") is not True:
        return False
    configuration = manifest.get("configuration", {})
    campaign = configuration.get("campaign_execution", {}) if isinstance(configuration, dict) else {}
    if not isinstance(campaign, dict):
        return False
    return (
        campaign.get("campaign_id") == campaign_id
        and campaign.get("case_id") == case_id
        and campaign.get("condition_identity") == condition_id
        and campaign.get("repetition_index") == repetition_index
        and campaign.get("firmware_sha256") == firmware_sha256
    )


CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def _default_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _stream_command_to_log(
    command: list[str], cwd: Path, log_path: Path
) -> subprocess.CompletedProcess[str]:
    """Run a long-lived experiment command with live, durable output.

    Output is appended to ``log_path`` as it is produced and mirrored to this
    process' stdout so gateway/hardware validation remains observable. The
    returned ``CompletedProcess.stdout`` still contains the complete combined
    stream for compatibility with existing error handling.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []
    with log_path.open("w", encoding="utf-8", buffering=1) as log_handle:
        log_handle.write(f"[{_now()}] command={subprocess.list2cmdline(command)}\n")
        log_handle.flush()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            log_handle.write(line)
            log_handle.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        return_code = process.wait()
        log_handle.write(f"\n[{_now()}] return_code={return_code}\n")
        log_handle.flush()
    return subprocess.CompletedProcess(
        args=command, returncode=return_code, stdout="".join(captured), stderr=None
    )


def _new_manifest_after(results_dir: Path, before: set[Path]) -> Path:
    candidates = {
        path.resolve()
        for path in results_dir.glob("*/manifest.json")
        if path.is_file()
    } - before
    if len(candidates) != 1:
        raise CampaignError(
            f"experiment runner produced {len(candidates)} new manifests under {results_dir}; expected exactly one"
        )
    return next(iter(candidates))


def _run_experiment(
    *,
    repo_root: Path,
    command: list[str],
    results_dir: Path,
    runner: CommandRunner,
    log_path: Path,
) -> tuple[int, Path | None, str]:
    results_dir.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in results_dir.glob("*/manifest.json") if path.is_file()}
    if runner is _default_runner:
        completed = _stream_command_to_log(command, repo_root, log_path)
    else:
        completed = runner(command, repo_root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(completed.stdout or "", encoding="utf-8")
    manifest_path = None
    try:
        manifest_path = _new_manifest_after(results_dir, before)
    except CampaignError:
        if completed.returncode == 0:
            raise
    return completed.returncode, manifest_path, completed.stdout or ""


def _materialize_preparation_case(
    *, resolver: ConfigResolver, representative: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    selections = dict(representative["selections"])
    choices = dict(representative["choices"])
    choices["network_condition"] = "baseline"
    overrides = dict(representative.get("overrides", {}).get("workload", {}))
    preparation = resolver.resolve_case(
        campaign_id=f"{representative['campaign']['id']}-preparation",
        case_index=int(representative["campaign"]["case_index"]),
        selections=selections,
        choices=choices,
        workload_overrides=overrides,
        execution=dict(representative.get("execution", {})),
    )
    if preparation["provenance"]["firmware_identity"] != representative["provenance"]["firmware_identity"]:
        raise CampaignError("baseline preparation case changed the build-affecting firmware identity")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(preparation, sort_keys=False), encoding="utf-8")
    return preparation


def _broker_ctl_command(
    repo_root: Path, subcommand: str, *, profile: str | None = None, broker_port: int | None = None,
    certificate_profile: str | None = None,
) -> list[str]:
    command = [sys.executable, str(repo_root / "experiment/mqtt-broker/scripts/mqtt_broker_ctl.py"), subcommand,
               "--gateway-config", "configs/gateways/pqc_gateway1.yaml"]
    if certificate_profile:
        command.extend(["--certificate-profile", certificate_profile])
    if profile:
        command.extend(["--profile", profile])
    if broker_port:
        port_option = "--oqs-port" if profile and profile.startswith("oqs") else "--classical-port"
        command.extend([port_option, str(broker_port)])
    return command


def _broker_certificate_profile(bundle: dict[str, dict[str, Any]]) -> str | None:
    """Select the same certificate family as the resolved TLS clients."""
    tls = bundle["experiment"]["mqtt"].get("tls", {})
    if str(tls.get("mode", "")).lower() == "plaintext":
        return None
    return str(tls.get("certificate_profile") or "").strip() or None


def _broker_profile_and_port(bundle: dict[str, dict[str, Any]]) -> tuple[str, int | None]:
    """Return the Compose profile and optional TLS host-port override.

    The resolved MQTT broker port is the workload listener.  For plaintext
    workloads that is port 1883, but mqtt_broker_ctl.py's --classical-port
    option controls the TLS listener rather than the plaintext listener.
    Passing 1883 through that option makes the classical service attempt to
    bind both listeners to the same host port.  Plaintext campaigns therefore
    use the Compose profile's canonical listener mapping without a TLS-port
    override.  TLS campaigns retain the resolved host-port override.
    """
    mqtt = bundle["experiment"]["mqtt"]
    profile = str(mqtt.get("broker_profile", "classical"))
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    if isinstance(tls, dict) and str(tls.get("mode", "")).lower() == "plaintext":
        return profile, None
    return profile, int(mqtt["broker"]["port"])


class CampaignExecutor:
    def __init__(
        self,
        repo_root: Path | str,
        *,
        results_root: Path | str = "results/campaigns",
        runner: CommandRunner = _default_runner,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.results_root = Path(results_root)
        if not self.results_root.is_absolute():
            self.results_root = self.repo_root / self.results_root
        self.resolver = ConfigResolver(self.repo_root)
        self.runner = runner
        self._broker_active_identity: str | None = None
        self._broker_bundle: dict[str, dict[str, Any]] | None = None

    def execute(self, campaign: Path | str, *, resume_manifest: Path | None = None) -> Path:
        from framework.network_degradation import (
            GatewayNetworkDegradation,
            apply_gateway_network_degradation,
            remove_gateway_network_degradation,
            verify_gateway_network_degradation,
            gateway_impairment_packet_counts,
        )

        source_path, campaign_data = self.resolver.load_campaign(campaign)
        cases = self.resolver.expand_campaign(source_path)
        generated_root = self.resolver.materialize_campaign(source_path)
        if not cases:
            raise CampaignError("campaign expansion produced no cases")
        policy = ExecutionPolicy.from_mapping(dict(campaign_data["execution"]))
        for case in cases:
            validate_policy_against_case(policy=policy, case=case, resolver=self.resolver)
        groups = group_cases_by_firmware_identity(cases)

        source_identity = canonical_sha256({
            "source": source_path.read_text(encoding="utf-8"),
            "cases": [case["provenance"]["configuration_identity"] for case in cases],
            "policy": policy.as_dict(),
        })
        if resume_manifest is not None:
            manifest_path = Path(resume_manifest).resolve()
            state = _read_json(manifest_path)
            if state.get("source_identity") != source_identity:
                raise CampaignError("resume manifest does not match the current campaign source/resolution")
            campaign_root = manifest_path.parent
            state.pop("final_index", None)
            state.pop("failure", None)
            state.pop("completed_at", None)
            state["resumed_at"] = _now()
            state["state"] = "running"
        else:
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            campaign_root = self.results_root / f"{_safe_component(str(campaign_data['id']))}_{timestamp}"
            campaign_root.mkdir(parents=True, exist_ok=False)
            manifest_path = campaign_root / "campaign-manifest.json"
            state = self._initial_state(
                source_path=source_path,
                campaign_data=campaign_data,
                source_identity=source_identity,
                policy=policy,
                cases=cases,
                groups=groups,
            )
        _write_json_atomic(manifest_path, state)

        cleanup_errors: list[str] = []
        active_condition: GatewayNetworkDegradation | None = None
        try:
            for group_index, group in enumerate(groups, start=1):
                firmware_sha256 = None
                try:
                    representative = group["cases"][0]
                    if resume_manifest is not None and self._resume_group_completed(
                        state=state, group=group, group_index=group_index,
                        campaign_root=campaign_root, campaign_id=str(campaign_data["id"]),
                        repetitions=policy.repetitions,
                    ):
                        _write_json_atomic(manifest_path, state)
                        continue
                    preparation_manifest, firmware_sha256 = _setup_step("preparation", self._ensure_preparation,
                        campaign_root=campaign_root,
                        generated_root=generated_root,
                        state=state,
                        manifest_path=manifest_path,
                        group_index=group_index,
                        representative=representative,
                        firmware_identity=group["firmware_identity"],
                        force_reflash=resume_manifest is not None,
                    )
                    group_state = state["firmware_groups"][group_index - 1]
                    group_state["validated_firmware_sha256"] = firmware_sha256
                    _write_json_atomic(manifest_path, state)

                    bundle = self.resolver.to_legacy_bundle(representative)
                    wanted_broker_identity = broker_identity(bundle, representative)
                    _setup_step("broker_setup", self._ensure_broker, bundle=bundle, identity=wanted_broker_identity, campaign_root=campaign_root)
                    group_state["broker_identity"] = wanted_broker_identity
                    _write_json_atomic(manifest_path, state)

                    condition_groups: dict[str, list[dict[str, Any]]] = {}
                    condition_order: list[str] = []
                    for case in group["cases"]:
                        cid = condition_identity(case)
                        if cid not in condition_groups:
                            condition_groups[cid] = []
                            condition_order.append(cid)
                        condition_groups[cid].append(case)

                    for cid in condition_order:
                        if active_condition is not None:
                            cleanup = remove_gateway_network_degradation(
                                degradation=active_condition, repo_root=self.repo_root
                            )
                            if cleanup.return_code != 0:
                                cleanup_errors.append(cleanup.failure_reason or "condition cleanup failed")
                                raise CampaignError(cleanup.failure_reason or "condition cleanup failed")
                            active_condition = None
                        condition_cases = condition_groups[cid]
                        condition_bundle = self.resolver.to_legacy_bundle(condition_cases[0])
                        control_dir = campaign_root / "control" / f"condition-{cid[:12]}"
                        control_dir.mkdir(parents=True, exist_ok=True)
                        active_condition, apply_result = apply_gateway_network_degradation(
                            bundle=condition_bundle, repo_root=self.repo_root, result_dir=control_dir
                        )
                        if apply_result is not None and active_condition is None:
                            raise CampaignError(
                                f"failed to apply condition {condition_cases[0]['choices']['network_condition']}"
                            )
                        state.setdefault("condition_events", []).append({
                            "condition_identity": cid,
                            "network_condition": condition_cases[0]["choices"]["network_condition"],
                            "status": "applied" if active_condition is not None else "baseline",
                            "control_log": (
                                None if active_condition is None else str(active_condition.log_path.relative_to(campaign_root))
                            ),
                            "at": _now(),
                        })
                        _write_json_atomic(manifest_path, state)

                        for case in condition_cases:
                            case_path = self._case_path(generated_root, case)
                            for repetition in range(1, policy.repetitions + 1):
                                if self._resume_completed(
                                    state=state,
                                    campaign_id=str(campaign_data["id"]),
                                    case=case,
                                    cid=cid,
                                    repetition=repetition,
                                    firmware_sha256=firmware_sha256,
                                ):
                                    continue
                                _setup_step("broker_setup", self._ensure_broker,
                                    bundle=self.resolver.to_legacy_bundle(case),
                                    identity=broker_identity(self.resolver.to_legacy_bundle(case), case),
                                    campaign_root=campaign_root,
                                )
                                before_packets = None
                                if active_condition is not None:
                                    observed_before = verify_gateway_network_degradation(
                                        degradation=active_condition, repo_root=self.repo_root
                                    )
                                    before_packets = gateway_impairment_packet_counts(observed_before.stdout)
                                    if observed_before.return_code != 0 or before_packets is None:
                                        raise CampaignError(
                                            "retained network condition failed effective-state/counter verification before repetition "
                                            f"{repetition}; inspect {active_condition.log_path}"
                                        )
                                try:
                                    run_manifest = self._run_repetition(
                                        campaign_root=campaign_root,
                                        campaign_id=str(campaign_data["id"]),
                                        case=case,
                                        case_path=case_path,
                                        preparation_manifest=preparation_manifest,
                                        firmware_sha256=firmware_sha256,
                                        cid=cid,
                                        repetition=repetition,
                                        policy=policy,
                                        condition_log=(
                                            None if active_condition is None
                                            else active_condition.log_path
                                        ),
                                    )
                                except RepetitionError as exc:
                                    self._record_run(
                                        state=state, case=case, cid=cid, repetition=repetition,
                                        run_manifest=exc.manifest, firmware_sha256=firmware_sha256,
                                        failure={"message": str(exc), "return_code": exc.return_code,
                                                 "log": str(exc.log)},
                                    )
                                    _write_json_atomic(manifest_path, state)
                                    print(f"Campaign repetition failed; continuing: {exc}", file=sys.stderr, flush=True)
                                    continue
                                if active_condition is not None:
                                    observed_after = verify_gateway_network_degradation(
                                        degradation=active_condition, repo_root=self.repo_root
                                    )
                                    after_packets = gateway_impairment_packet_counts(observed_after.stdout)
                                    with active_condition.log_path.open("a", encoding="utf-8") as evidence:
                                        evidence.write(
                                            f"\nRepetition {repetition} packet counters: "
                                            f"before={before_packets}, after={after_packets}\n"
                                        )
                                    if observed_after.return_code != 0 or after_packets is None:
                                        raise CampaignError(
                                            "retained network condition failed effective-state/counter verification after repetition "
                                            f"{repetition}; inspect {active_condition.log_path}"
                                        )
                                    if any(after <= before for after, before in zip(after_packets, before_packets)):
                                        raise CampaignError(
                                            "experiment-broker egress and IFB ingress counters must both advance "
                                            f"during repetition {repetition}; inspect {active_condition.log_path}"
                                        )
                                self._record_run(
                                    state=state,
                                    case=case,
                                    cid=cid,
                                    repetition=repetition,
                                    run_manifest=run_manifest,
                                    firmware_sha256=firmware_sha256,
                                )
                                _write_json_atomic(manifest_path, state)

                    if active_condition is not None:
                        cleanup = remove_gateway_network_degradation(
                            degradation=active_condition, repo_root=self.repo_root
                        )
                        state.setdefault("condition_events", []).append({
                            "condition_identity": condition_identity(group["cases"][-1]),
                            "status": "removed" if cleanup.return_code == 0 else "cleanup_failed",
                            "at": _now(),
                            "return_code": cleanup.return_code,
                        })
                        if cleanup.return_code != 0:
                            cleanup_errors.append(cleanup.failure_reason or "condition cleanup failed")
                            raise CampaignError(cleanup.failure_reason or "condition cleanup failed")
                        active_condition = None
                    group_state["state"] = "completed"
                    group_state.pop("failure", None)
                    _write_json_atomic(manifest_path, state)
                except GroupSetupError as exc:
                    group_state = state["firmware_groups"][group_index - 1]
                    group_state["state"] = "blocked"
                    group_state["failure"] = {"stage": exc.stage, "message": str(exc), "at": _now()}
                    for blocked_case in group["cases"]:
                        for blocked_rep in range(1, policy.repetitions + 1):
                            existing = next((run for run in state["runs"]
                                             if run["case_id"] == blocked_case["id"]
                                             and run["repetition_index"] == blocked_rep), None)
                            if existing and existing.get("state") == "failed":
                                continue
                            if firmware_sha256 is not None and self._resume_completed(
                                state=state, campaign_id=str(campaign_data["id"]), case=blocked_case,
                                cid=condition_identity(blocked_case), repetition=blocked_rep,
                                firmware_sha256=firmware_sha256,
                            ):
                                continue
                            # A preparation failure must not erase previously completed evidence.
                            if firmware_sha256 is None and existing and existing.get("state") == "completed":
                                continue
                            self._record_run(
                                state=state, case=blocked_case, cid=condition_identity(blocked_case),
                                repetition=blocked_rep, run_manifest=None,
                                firmware_sha256=firmware_sha256,
                                failure={"stage": exc.stage, "message": str(exc),
                                         "runtime_started": False, "control_logs": str(campaign_root / "control")},
                                blocked=True,
                            )
                    _write_json_atomic(manifest_path, state)
                    # Shared infrastructure must be removed before trying another group.
                    if active_condition is not None:
                        cleanup = remove_gateway_network_degradation(
                            degradation=active_condition, repo_root=self.repo_root
                        )
                        if cleanup.return_code != 0:
                            cleanup_errors.append(cleanup.failure_reason or "condition cleanup failed")
                            raise CampaignError(cleanup_errors[-1])
                        active_condition = None
                    cleanup_error = self._stop_brokers(campaign_root)
                    if cleanup_error:
                        cleanup_errors.append(cleanup_error)
                        raise CampaignError(cleanup_error)
                    print(f"Campaign firmware group {group_index} blocked during {exc.stage}; "
                          f"continuing to next group: {exc}", file=sys.stderr, flush=True)
                    continue

            failed = sum(run.get("state") == "failed" for run in state["runs"])
            blocked = sum(run.get("state") == "blocked" for run in state["runs"])
            state["summary"] = {"planned": len(cases) * policy.repetitions,
                                "completed": len(state["runs"]) - failed - blocked,
                                "failed": failed, "blocked": blocked}
            state["state"] = "completed_with_failures" if failed or blocked else "completed"
            state["completed_at"] = _now()
        except BaseException as exc:
            state["state"] = "failed"
            state["failure"] = {"type": type(exc).__name__, "message": str(exc), "at": _now()}
            raise
        finally:
            if active_condition is not None:
                cleanup = remove_gateway_network_degradation(
                    degradation=active_condition, repo_root=self.repo_root
                )
                if cleanup.return_code != 0:
                    cleanup_errors.append(cleanup.failure_reason or "network condition cleanup failed")
            broker_cleanup = self._stop_brokers(campaign_root)
            if broker_cleanup is not None:
                cleanup_errors.append(broker_cleanup)
            state["cleanup"] = {
                "status": "passed" if not cleanup_errors else "failed",
                "errors": cleanup_errors,
                "completed_at": _now(),
            }
            if cleanup_errors and state.get("state") in {"completed", "completed_with_failures"}:
                state["state"] = "failed"
                state["failure"] = {"type": "CleanupError", "message": "; ".join(cleanup_errors), "at": _now()}
            if state.get("state") in {"completed", "completed_with_failures"} and state.get("cleanup", {}).get("status") == "passed":
                final_payload = {key: value for key, value in state.items() if key != "final_index"}
                state["final_index"] = {
                    "status": "finalized",
                    "finalized_at": _now(),
                    "sha256": canonical_sha256(final_payload),
                    "scope": "campaign_execution_index",
                }
            else:
                state.pop("final_index", None)
            _write_json_atomic(manifest_path, state)
        if cleanup_errors:
            raise CampaignError("campaign cleanup failed: " + "; ".join(cleanup_errors))
        return manifest_path

    def _initial_state(
        self,
        *,
        source_path: Path,
        campaign_data: dict[str, Any],
        source_identity: str,
        policy: ExecutionPolicy,
        cases: list[dict[str, Any]],
        groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema": {"name": CAMPAIGN_SCHEMA_NAME, "version": CAMPAIGN_SCHEMA_VERSION},
            "campaign_id": campaign_data["id"],
            "source": source_path.relative_to(self.repo_root).as_posix(),
            "source_identity": source_identity,
            "created_at": _now(),
            "state": "running",
            "execution_policy": policy.as_dict(),
            "expanded_cases": [
                {
                    "id": case["id"],
                    "configuration_identity": case["provenance"]["configuration_identity"],
                    "firmware_identity": case["provenance"]["firmware_identity"],
                    "condition_identity": condition_identity(case),
                    "network_condition": case["choices"]["network_condition"],
                }
                for case in cases
            ],
            "condition_ordering": [
                {
                    "case_id": case["id"],
                    "firmware_identity": case["provenance"]["firmware_identity"],
                    "condition_identity": condition_identity(case),
                    "network_condition": case["choices"]["network_condition"],
                }
                for case in cases
            ],
            "repetition_indices": list(range(1, policy.repetitions + 1)),
            "firmware_groups": [
                {
                    "firmware_identity": group["firmware_identity"],
                    "case_ids": [case["id"] for case in group["cases"]],
                    "preparation_manifest": None,
                    "validated_firmware_sha256": None,
                    "broker_identity": None,
                    "state": "pending",
                }
                for group in groups
            ],
            "runs": [],
            "condition_events": [],
            "cleanup": {"status": "pending", "errors": []},
        }

    def _case_path(self, generated_root: Path, case: dict[str, Any]) -> Path:
        path = generated_root / "cases" / f"{case['campaign']['case_index']:04d}_{case['id']}.yaml"
        if not path.is_file():
            raise CampaignError(f"materialized campaign case is missing: {path}")
        return path

    def _resume_group_completed(
        self, *, state: dict[str, Any], group: dict[str, Any], group_index: int,
        campaign_root: Path, campaign_id: str, repetitions: int,
    ) -> bool:
        """Skip hardware work only when every saved repetition still validates."""
        recorded = state["firmware_groups"][group_index - 1].get("preparation_manifest")
        if not recorded:
            return False
        path = Path(recorded)
        if not path.is_absolute():
            path = campaign_root / path
        try:
            firmware_sha = validate_preparation_manifest(
                path, expected_firmware_identity=group["firmware_identity"]
            )
        except CampaignError:
            return False
        return all(
            self._resume_completed(
                state=state, campaign_id=campaign_id, case=case,
                cid=condition_identity(case), repetition=repetition,
                firmware_sha256=firmware_sha,
            )
            for case in group["cases"]
            for repetition in range(1, repetitions + 1)
        )

    def _ensure_preparation(
        self,
        *,
        campaign_root: Path,
        generated_root: Path,
        state: dict[str, Any],
        manifest_path: Path,
        group_index: int,
        representative: dict[str, Any],
        firmware_identity: str,
        force_reflash: bool = False,
    ) -> tuple[Path, str]:
        group_state = state["firmware_groups"][group_index - 1]
        recorded = group_state.get("preparation_manifest")
        if recorded:
            recorded_path = Path(recorded)
            if not recorded_path.is_absolute():
                recorded_path = campaign_root / recorded_path
            try:
                firmware_sha = validate_preparation_manifest(
                    recorded_path, expected_firmware_identity=firmware_identity
                )
                if not force_reflash:
                    return recorded_path, firmware_sha
            except CampaignError:
                group_state["preparation_manifest"] = None
                group_state["validated_firmware_sha256"] = None
                group_state["state"] = "preparation_stale"
                _write_json_atomic(manifest_path, state)

        if recorded:
            group_state.setdefault("previous_preparations", []).append({
                "manifest": recorded,
                "firmware_sha256": group_state.get("validated_firmware_sha256"),
                "replaced_at": _now(),
                "reason": "resume_reflash" if force_reflash else "stale_preparation",
            })
        if force_reflash:
            # A prior successful flash says nothing about current board contents.
            # Re-enter the normal preparation path before allowing runtime reuse.
            group_state["state"] = "resume_reflash_required"
            group_state["preparation_manifest"] = None
            group_state["validated_firmware_sha256"] = None
            _write_json_atomic(manifest_path, state)
            print(f"Restoring firmware for resumed group {group_index} via preparation/build/sign/flash",
                  flush=True)

        prep_case_path = generated_root / "preparation-cases" / f"firmware-{group_index:04d}.yaml"
        _materialize_preparation_case(
            resolver=self.resolver,
            representative=representative,
            output_path=prep_case_path,
        )
        preparation_results = campaign_root / "preparations"
        command = [
            sys.executable,
            str(self.repo_root / "scripts/experiment.py"),
            "run",
            "--experiment", str(prep_case_path),
            "--results-dir", str(preparation_results),
        ]
        log_path = campaign_root / "logs" / f"preparation-{group_index:04d}.log"
        if representative.get("selections", {}).get("instruments", {}).get("energy"):
            command.append("--prepare-only")
        if log_path.exists():
            attempt = 2
            while log_path.with_name(f"{log_path.stem}-attempt-{attempt}.log").exists():
                attempt += 1
            log_path = log_path.with_name(f"{log_path.stem}-attempt-{attempt}.log")
        rc, produced_manifest, output = _run_experiment(
            repo_root=self.repo_root,
            command=command,
            results_dir=preparation_results,
            runner=self.runner,
            log_path=log_path,
        )
        if rc != 0 or produced_manifest is None:
            raise CampaignError(f"firmware preparation failed for {firmware_identity}; see {log_path}")
        firmware_sha = validate_preparation_manifest(
            produced_manifest, expected_firmware_identity=firmware_identity
        )
        group_state.update({
            "preparation_manifest": produced_manifest.relative_to(campaign_root).as_posix(),
            "validated_firmware_sha256": firmware_sha,
            "state": "prepared",
            "preparation_reason": "resume_reflash" if force_reflash else "initial_or_stale",
        })
        _write_json_atomic(manifest_path, state)
        return produced_manifest, firmware_sha

    def _ensure_broker(self, *, bundle: dict[str, dict[str, Any]], identity: str, campaign_root: Path) -> None:
        if self._broker_active_identity == identity and self._broker_bundle is not None:
            if self._broker_health(bundle=bundle, campaign_root=campaign_root):
                return
            cleanup_error = self._stop_brokers(campaign_root)
            if cleanup_error:
                raise CampaignCleanupError(cleanup_error)
        elif self._broker_active_identity is not None:
            cleanup_error = self._stop_brokers(campaign_root)
            if cleanup_error:
                raise CampaignCleanupError(cleanup_error)

        profile, port = _broker_profile_and_port(bundle)
        deploy_command = _broker_ctl_command(self.repo_root, "deploy")
        deployed = self.runner(deploy_command, self.repo_root)
        self._append_control_log(campaign_root, "broker-deploy.log", deploy_command, deployed)
        if deployed.returncode != 0:
            raise CampaignError("failed to deploy campaign broker configuration")
        self._broker_active_identity = identity
        self._broker_bundle = bundle
        for wanted_profile, wanted_port in ((profile, port), ("reporting", None)):
            command = _broker_ctl_command(
                self.repo_root, "start", profile=wanted_profile, broker_port=wanted_port,
                certificate_profile=(
                    _broker_certificate_profile(bundle) if wanted_profile != "reporting" else None
                ),
            )
            completed = self.runner(command, self.repo_root)
            self._append_control_log(campaign_root, "broker-start.log", command, completed)
            if completed.returncode != 0:
                raise CampaignError(f"failed to start broker profile {wanted_profile}")
        if not self._broker_health(bundle=bundle, campaign_root=campaign_root):
            cleanup_error = self._stop_brokers(campaign_root)
            if cleanup_error:
                raise CampaignCleanupError(cleanup_error)
            raise CampaignError("broker health check failed after campaign start")

    def _broker_health(self, *, bundle: dict[str, dict[str, Any]], campaign_root: Path) -> bool:
        profile, port = _broker_profile_and_port(bundle)
        ok = True
        for wanted_profile, wanted_port in ((profile, port), ("reporting", None)):
            command = _broker_ctl_command(
                self.repo_root, "status", profile=wanted_profile, broker_port=wanted_port,
                certificate_profile=(
                    _broker_certificate_profile(bundle) if wanted_profile != "reporting" else None
                ),
            )
            completed = self.runner(command, self.repo_root)
            self._append_control_log(campaign_root, "broker-health.log", command, completed)
            status_text = (completed.stdout or "").lower()
            service_present = any(token in status_text for token in ("running", " up ", "healthy"))
            ok = ok and completed.returncode == 0 and service_present
        return ok

    def _stop_brokers(self, campaign_root: Path) -> str | None:
        if self._broker_active_identity is None:
            return None
        command = _broker_ctl_command(self.repo_root, "stop")
        completed = self.runner(command, self.repo_root)
        self._append_control_log(campaign_root, "broker-stop.log", command, completed)
        if completed.returncode != 0:
            return "broker cleanup failed"
        self._broker_active_identity = None
        self._broker_bundle = None
        return None

    def _append_control_log(
        self,
        campaign_root: Path,
        name: str,
        command: list[str],
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        path = campaign_root / "control" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{_now()}] command={subprocess.list2cmdline(command)}\n")
            handle.write(f"return_code={completed.returncode}\n")
            handle.write((completed.stdout or "") + "\n")

    def _run_repetition(
        self,
        *,
        campaign_root: Path,
        campaign_id: str,
        case: dict[str, Any],
        case_path: Path,
        preparation_manifest: Path,
        firmware_sha256: str,
        cid: str,
        repetition: int,
        policy: ExecutionPolicy,
        condition_log: Path | None = None,
    ) -> Path:
        results_dir = campaign_root / "runs"
        command = [
            sys.executable,
            str(self.repo_root / "scripts/experiment.py"),
            "run",
            "--experiment", str(case_path),
            "--results-dir", str(results_dir),
            "--runtime-only",
            "--profile-preparation-manifest", str(preparation_manifest),
            "--campaign-managed-broker",
            "--campaign-managed-condition",
            "--campaign-id", campaign_id,
            "--campaign-case-id", str(case["id"]),
            "--campaign-condition-identity", cid,
            "--campaign-repetition-index", str(repetition),
        ]
        if condition_log is not None:
            command.extend(["--campaign-condition-log", str(condition_log)])
        ota_plan = case.get("execution", {}).get("ota_plan") if isinstance(case.get("execution"), dict) else None
        if ota_plan:
            command.extend(["--ota-plan", str(ota_plan)])
        if policy.reset_between_runs == "none":
            command.append("--skip-hardware-reset")
        log_path = campaign_root / "logs" / f"{case['id']}-rep-{repetition:04d}.log"
        if log_path.exists():
            attempt = 2
            while log_path.with_name(f"{log_path.stem}-attempt-{attempt}.log").exists():
                attempt += 1
            log_path = log_path.with_name(f"{log_path.stem}-attempt-{attempt}.log")
        try:
            rc, produced_manifest, output = _run_experiment(
                repo_root=self.repo_root,
                command=command,
                results_dir=results_dir,
                runner=self.runner,
                log_path=log_path,
            )
        except CampaignError as exc:
            raise RepetitionError(str(exc), manifest=None, return_code=0, log=log_path) from exc
        failure = None
        if rc != 0:
            failure = f"repetition failed for {case['id']} #{repetition}; see {log_path}"
        elif produced_manifest is None:
            failure = f"repetition produced no run manifest; see {log_path}"
        else:
            try:
                valid = validate_completed_run(
                    produced_manifest, campaign_id=campaign_id, case_id=str(case["id"]),
                    condition_id=cid, repetition_index=repetition, firmware_sha256=firmware_sha256,
                )
            except CampaignError:
                valid = False
            if not valid:
                failure = f"repetition evidence validation failed: {produced_manifest}"
        if failure:
            raise RepetitionError(failure, manifest=produced_manifest, return_code=rc, log=log_path)
        return produced_manifest

    def _record_run(
        self,
        *,
        state: dict[str, Any],
        case: dict[str, Any],
        cid: str,
        repetition: int,
        run_manifest: Path | None,
        firmware_sha256: str,
        failure: dict[str, Any] | None = None,
        blocked: bool = False,
    ) -> None:
        existing = next((item for item in state["runs"] if item.get("case_id") == case["id"] and item.get("repetition_index") == repetition), None)
        record = {
            "case_id": case["id"],
            "configuration_identity": case["provenance"]["configuration_identity"],
            "firmware_identity": case["provenance"]["firmware_identity"],
            "firmware_sha256": firmware_sha256,
            "condition_identity": cid,
            "network_condition": case["choices"]["network_condition"],
            "repetition_index": repetition,
            "manifest": str(run_manifest) if run_manifest else None,
            "state": "blocked" if blocked else "failed" if failure else "completed",
            "failure": failure,
            "completed_at": _now(),
        }
        if existing is None:
            state["runs"].append(record)
        else:
            history = existing.get("previous_attempts", [])
            history.append({key: value for key, value in existing.items() if key != "previous_attempts"})
            existing.clear()
            existing.update(record)
            existing["previous_attempts"] = history

    def _resume_completed(
        self,
        *,
        state: dict[str, Any],
        campaign_id: str,
        case: dict[str, Any],
        cid: str,
        repetition: int,
        firmware_sha256: str,
    ) -> bool:
        record = next(
            (
                item for item in state.get("runs", [])
                if item.get("case_id") == case["id"] and item.get("repetition_index") == repetition
            ),
            None,
        )
        if not isinstance(record, dict) or record.get("state") != "completed":
            return False
        manifest_path = Path(str(record.get("manifest", "")))
        if not manifest_path.is_absolute():
            manifest_path = self.repo_root / manifest_path
        valid = validate_completed_run(
            manifest_path,
            campaign_id=campaign_id,
            case_id=str(case["id"]),
            condition_id=cid,
            repetition_index=repetition,
            firmware_sha256=firmware_sha256,
        )
        if not valid:
            record["state"] = "stale"
            record["resume_validation"] = "failed"
            return False
        record["resume_validation"] = "validated"
        return True
