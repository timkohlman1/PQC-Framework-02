"""Versioned canonical configuration resolver for PQC experiment campaigns.

Source-controlled profiles are the only maintained configuration authority. Campaigns select
profile identities and matrix dimensions. Resolved cases under .pqc-generated-state contain
only identities, non-secret choices, hashes and execution policy; implementation settings are
re-derived from the source profiles when consumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

SCHEMA_VERSION = 1
RESOLVER_VERSION = 1
AUTH_MODES = {"server", "mutual"}
FIRMWARE_MODES = {"single_bank", "dual_bank_no_ota", "dual_bank_ota"}
STANDBY_SIGNING_KEY_COUNTS = {0, 1, 2}
PROFILE_DIRS = {
    "target": Path("targets"),
    "gateway": Path("gateways"),
    "workload": Path("workloads"),
    "tls_kex": Path("tls_kex"),
    "tls_auth": Path("tls_auth"),
    "secure_boot": Path("secure_boot"),
    "network_condition": Path("network_conditions"),
}

class ResolutionError(ValueError):
    """Raised before any side effect when canonical configuration is invalid."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _identity(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _set_dotted(mapping: dict[str, Any], dotted: str, value: Any) -> None:
    current = mapping
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ResolutionError(f"matrix override '{dotted}' crosses non-mapping field '{part}'")
        current = child
    current[parts[-1]] = value


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResolutionError(f"{label} must be a mapping")
    return value


def _require(profile: dict[str, Any], key: str, label: str) -> Any:
    if key not in profile or profile[key] is None or profile[key] == "":
        raise ResolutionError(f"{label} missing required field: {key}")
    return profile[key]


@dataclass(frozen=True)
class LoadedProfile:
    domain: str
    profile_id: str
    path: Path
    data: dict[str, Any]
    content_sha256: str


class ConfigResolver:
    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root).resolve()
        self.configs_root = self.repo_root / "configs"

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ResolutionError(f"configuration file not found: {path}")
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ResolutionError(f"invalid YAML in {path}: {exc}") from exc
        data = _require_mapping(value, str(path))
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ResolutionError(
                f"{path}: schema_version must be {SCHEMA_VERSION}, got {data.get('schema_version')!r}"
            )
        return data

    def load_profile(self, domain: str, profile_id: str) -> LoadedProfile:
        if domain not in PROFILE_DIRS:
            raise ResolutionError(f"unsupported profile domain: {domain}")
        path = self.configs_root / PROFILE_DIRS[domain] / f"{profile_id}.yaml"
        data = self._read_yaml(path)
        if data.get("id") != profile_id:
            raise ResolutionError(f"{path}: id must be '{profile_id}'")
        if data.get("profile_type") != domain:
            raise ResolutionError(f"{path}: profile_type must be '{domain}'")
        self._validate_profile(domain, data, path)
        return LoadedProfile(domain, profile_id, path, data, _identity(data))

    def load_service(self, service_type: str, profile_id: str) -> LoadedProfile:
        path = self.configs_root / "services" / service_type / f"{profile_id}.yaml"
        data = self._read_yaml(path)
        if data.get("id") != profile_id or data.get("profile_type") != "service":
            raise ResolutionError(f"{path}: invalid service identity/type")
        if data.get("service_type") != service_type:
            raise ResolutionError(f"{path}: service_type must be '{service_type}'")
        return LoadedProfile(f"service:{service_type}", profile_id, path, data, _identity(data))

    def load_instrument(self, instrument_type: str, profile_id: str) -> LoadedProfile:
        path = self.configs_root / "instruments" / instrument_type / f"{profile_id}.yaml"
        data = self._read_yaml(path)
        if data.get("id") != profile_id or data.get("profile_type") != "instrument":
            raise ResolutionError(f"{path}: invalid instrument identity/type")
        if data.get("instrument_type") != instrument_type:
            raise ResolutionError(f"{path}: instrument_type must be '{instrument_type}'")
        return LoadedProfile(f"instrument:{instrument_type}", profile_id, path, data, _identity(data))

    def _validate_profile(self, domain: str, data: dict[str, Any], path: Path) -> None:
        if domain == "tls_auth":
            modes = data.get("supported_modes")
            if not isinstance(modes, list) or not modes or not set(modes) <= AUTH_MODES:
                raise ResolutionError(f"{path}: supported_modes must contain only server/mutual")
            identities = _require_mapping(data.get("identities"), f"{path}: identities")
            _require_mapping(data.get("hierarchy"), f"{path}: hierarchy")
            for name in ("server", "healthcheck"):
                if name not in identities:
                    raise ResolutionError(f"{path}: identities.{name} is required")
            if "mutual" in modes and "client" not in identities:
                raise ResolutionError(f"{path}: mutual support requires identities.client")
        elif domain == "tls_kex":
            _require(data, "wolfssl", str(path))
            _require(data, "class", str(path))
        elif domain == "workload":
            _require(data, "firmware_application", str(path))
            uart_mode = str(data.get("uart_output_mode", "minimal"))
            if uart_mode not in {"disabled", "minimal", "full"}:
                raise ResolutionError(
                    f"{path}: uart_output_mode must be disabled, minimal, or full"
                )
        elif domain == "secure_boot":
            _require(data, "wolfboot", str(path))

    def load_campaign(self, campaign: Path | str) -> tuple[Path, dict[str, Any]]:
        path = Path(campaign)
        if not path.is_absolute():
            path = self.configs_root / "campaigns" / (path if path.suffix else f"{path}.yaml")
        data = self._read_yaml(path)
        if data.get("profile_type") != "campaign":
            raise ResolutionError(f"{path}: profile_type must be campaign")
        for key in ("id", "target", "gateway", "services", "workload", "fixed", "execution"):
            _require(data, key, str(path))
        services = _require_mapping(data["services"], f"{path}: services")
        if "experiment_broker" not in services or "reporting_broker" not in services:
            raise ResolutionError(f"{path}: both experiment_broker and reporting_broker are required")
        return path, data

    def expand_campaign(self, campaign: Path | str) -> list[dict[str, Any]]:
        path, data = self.load_campaign(campaign)
        fixed = dict(_require_mapping(data.get("fixed"), f"{path}: fixed"))
        matrix = _require_mapping(data.get("matrix", {}), f"{path}: matrix")
        keys = list(matrix)
        values: list[list[Any]] = []
        for key in keys:
            vals = matrix[key]
            if not isinstance(vals, list) or not vals:
                raise ResolutionError(f"{path}: matrix.{key} must be a non-empty list")
            values.append(vals)
        combinations: Iterable[tuple[Any, ...]] = product(*values) if keys else [tuple()]
        cases: list[dict[str, Any]] = []
        for index, combination in enumerate(combinations, start=1):
            choices = dict(fixed)
            overrides: dict[str, Any] = {}
            for key, value in zip(keys, combination):
                if key.startswith("workload."):
                    _set_dotted(overrides, key.removeprefix("workload."), value)
                else:
                    choices[key] = value
            selection = {
                "target": data["target"], "gateway": data["gateway"],
                "services": dict(data["services"]), "workload": data["workload"],
            }
            if data.get("instruments"):
                selection["instruments"] = data["instruments"]
            cases.append(self.resolve_case(
                campaign_id=str(data["id"]), case_index=index, selections=selection,
                choices=choices, workload_overrides=overrides, execution=dict(data["execution"]),
            ))
        return cases

    def resolve_case(self, *, campaign_id: str, case_index: int, selections: dict[str, Any],
                     choices: dict[str, Any], workload_overrides: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        target = self.load_profile("target", str(selections["target"]))
        gateway = self.load_profile("gateway", str(selections["gateway"]))
        workload = self.load_profile("workload", str(selections["workload"]))
        tls_kex = self.load_profile("tls_kex", str(_require(choices, "tls_kex", "case choices")))
        tls_auth = self.load_profile("tls_auth", str(_require(choices, "tls_auth", "case choices")))
        secure_boot = self.load_profile("secure_boot", str(_require(choices, "secure_boot", "case choices")))
        network = self.load_profile("network_condition", str(_require(choices, "network_condition", "case choices")))
        auth_mode = str(_require(choices, "auth_mode", "case choices"))
        if auth_mode not in AUTH_MODES:
            raise ResolutionError(f"unsupported auth_mode: {auth_mode}")
        if auth_mode not in tls_auth.data["supported_modes"]:
            raise ResolutionError(f"tls_auth '{tls_auth.profile_id}' does not support auth_mode '{auth_mode}'")
        mqtt_transport = str(choices.get("mqtt_transport", "tls"))
        if mqtt_transport not in {"tls", "plaintext"}:
            raise ResolutionError("mqtt_transport must be tls or plaintext")
        if mqtt_transport == "plaintext":
            if workload.profile_id != "mqtt_validation":
                raise ResolutionError("plaintext MQTT transport requires mqtt_validation workload")
            if auth_mode != "server":
                raise ResolutionError("plaintext MQTT transport cannot request mutual TLS authentication")
            if tls_kex.profile_id != "secp256r1" or tls_auth.profile_id != "rsa3072":
                raise ResolutionError("plaintext MQTT uses inert secp256r1/rsa3072 compatibility selections")
        stack_profiling = choices.get("boot_stack_profiling", False)
        if not isinstance(stack_profiling, bool):
            raise ResolutionError("boot_stack_profiling must be a boolean")
        firmware_mode = str(choices.get("firmware_mode", "single_bank"))
        if firmware_mode not in FIRMWARE_MODES:
            raise ResolutionError(
                "firmware_mode must be one of: " + ", ".join(sorted(FIRMWARE_MODES))
            )
        try:
            standby_signing_keys = int(choices.get("standby_signing_keys", 0))
        except (TypeError, ValueError) as exc:
            raise ResolutionError("standby_signing_keys must be 0, 1, or 2") from exc
        if standby_signing_keys not in STANDBY_SIGNING_KEY_COUNTS:
            raise ResolutionError("standby_signing_keys must be 0, 1, or 2")
        secure_signing = secure_boot.data.get("signing", {})
        if standby_signing_keys and not bool(secure_signing.get("requires_private_key")):
            raise ResolutionError(
                "standby_signing_keys requires a signed secure-boot profile; "
                "integrity-only profiles do not have firmware signing keys"
            )
        effective_workload = _deep_merge(workload.data, workload_overrides)
        uart_mode = str(effective_workload.get("uart_output_mode", "minimal"))
        if uart_mode not in {"disabled", "minimal", "full"}:
            raise ResolutionError("workload uart_output_mode must be disabled, minimal, or full")
        transfer = effective_workload.get("transfer", {})
        if transfer:
            payload = int(_require(transfer, "payload_bytes", f"workload {workload.profile_id}.transfer"))
            chunk = int(_require(transfer, "chunk_bytes", f"workload {workload.profile_id}.transfer"))
            if payload <= 0 or chunk <= 0 or chunk > payload:
                raise ResolutionError("workload transfer payload/chunk must be positive and chunk <= payload")
        iterations = effective_workload.get("iterations", {})
        if iterations:
            if not isinstance(iterations, dict):
                raise ResolutionError(f"workload {workload.profile_id}.iterations must be a mapping")
            handshakes = iterations.get("handshakes_per_run")
            if not isinstance(handshakes, int) or isinstance(handshakes, bool) or not (1 <= handshakes <= 1000):
                raise ResolutionError("workload iterations.handshakes_per_run must be an integer from 1 to 1000")
            required_iteration_semantics = {
                "reset_between_handshakes": False,
                "fresh_tcp_connection": True,
                "fresh_tls_context": True,
                "session_resumption": False,
            }
            for field, expected in required_iteration_semantics.items():
                if iterations.get(field) is not expected:
                    raise ResolutionError(
                        f"workload iterations.{field} must be {str(expected).lower()} for independent full TLS handshakes"
                    )
        services = selections.get("services", {})
        exp = self.load_service("mqtt_broker", str(services["experiment_broker"]))
        rep = self.load_service("mqtt_broker", str(services["reporting_broker"]))
        if rep.data.get("transport") != "plaintext" or rep.data.get("tls", {}).get("enabled") is not False:
            raise ResolutionError("reporting broker must be fixed plaintext/non-TLS")
        if rep.data.get("network", {}).get("impairment_exempt") is not True:
            raise ResolutionError("reporting broker must use an impairment-exempt network path")
        instruments: dict[str, LoadedProfile] = {}
        for kind, ident in (selections.get("instruments") or {}).items():
            if ident is not None:
                instruments[kind] = self.load_instrument(kind, str(ident))
        profile_objects = [target, gateway, workload, tls_kex, tls_auth, secure_boot, network, exp, rep, *instruments.values()]
        hashes = {p.domain + ":" + p.profile_id: p.content_sha256 for p in profile_objects}
        public_choices = {
            "tls_kex": tls_kex.profile_id, "tls_auth": tls_auth.profile_id, "auth_mode": auth_mode,
            "secure_boot": secure_boot.profile_id, "network_condition": network.profile_id,
            "firmware_mode": firmware_mode,
            "standby_signing_keys": standby_signing_keys,
            "boot_stack_profiling": stack_profiling,
        }
        if mqtt_transport == "plaintext":
            public_choices["mqtt_transport"] = "plaintext"
        if transfer:
            public_choices["payload_bytes"] = int(transfer["payload_bytes"])
            public_choices["chunk_bytes"] = int(transfer["chunk_bytes"])
        if iterations:
            public_choices["handshakes_per_run"] = int(iterations["handshakes_per_run"])
        selection_record = {
            "target": target.profile_id, "gateway": gateway.profile_id,
            "services": {"experiment_broker": exp.profile_id, "reporting_broker": rep.profile_id},
            "workload": workload.profile_id,
        }
        if instruments:
            selection_record["instruments"] = {k: v.profile_id for k, v in instruments.items()}
        identity_input = {"schema_version": SCHEMA_VERSION, "resolver_version": RESOLVER_VERSION,
                          "selections": selection_record, "choices": public_choices,
                          "profile_hashes": hashes}
        config_id = _identity(identity_input)
        firmware_choices = {
            "tls_kex": tls_kex.profile_id,
            "tls_auth": tls_auth.profile_id,
            "auth_mode": auth_mode,
            "secure_boot": secure_boot.profile_id,
            "workload": workload.profile_id,
            "firmware_mode": firmware_mode,
            "standby_signing_keys": standby_signing_keys,
            "boot_stack_profiling": stack_profiling,
        }
        if mqtt_transport == "plaintext":
            firmware_choices["mqtt_transport"] = "plaintext"
        if transfer:
            firmware_choices["payload_bytes"] = int(transfer["payload_bytes"])
            firmware_choices["chunk_bytes"] = int(transfer["chunk_bytes"])
        if iterations:
            firmware_choices["handshakes_per_run"] = int(iterations["handshakes_per_run"])
        firmware_id = _identity({
            "schema_version": SCHEMA_VERSION,
            "resolver_version": RESOLVER_VERSION,
            "target": target.profile_id,
            "choices": firmware_choices,
            "firmware_profile_hashes": {
                k: v for k, v in hashes.items()
                if k.startswith(("target:", "workload:", "tls_kex:", "tls_auth:", "secure_boot:"))
            },
        })
        return {
            "schema_version": SCHEMA_VERSION, "kind": "resolved_case",
            "id": f"{campaign_id}-{case_index:04d}-{config_id[:12]}",
            "campaign": {"id": campaign_id, "case_index": case_index},
            "selections": selection_record, "choices": public_choices,
            "overrides": {"workload": workload_overrides} if workload_overrides else {},
            "execution": execution,
            "provenance": {"resolver_version": RESOLVER_VERSION, "profile_hashes": hashes,
                           "configuration_identity": config_id, "firmware_identity": firmware_id},
        }

    def materialize_campaign(self, campaign: Path | str, output_root: Path | None = None) -> Path:
        path, campaign_data = self.load_campaign(campaign)
        cases = self.expand_campaign(path)
        root = output_root or self.repo_root / ".pqc-generated-state" / "campaigns" / str(campaign_data["id"])
        cases_dir = root / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)
        # Materialized campaign state is derivative. Remove prior generated case
        # files before writing the new expansion so callers cannot accidentally
        # select a stale case left behind after profile/content changes.
        for stale_case in cases_dir.glob("*.yaml"):
            stale_case.unlink()
        summary = {"schema_version": SCHEMA_VERSION, "resolver_version": RESOLVER_VERSION,
                   "campaign": campaign_data["id"], "source": path.relative_to(self.repo_root).as_posix(),
                   "case_count": len(cases), "cases": []}
        for case in cases:
            case_path = cases_dir / f"{case['campaign']['case_index']:04d}_{case['id']}.yaml"
            case_path.write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
            summary["cases"].append({"id": case["id"], "path": case_path.relative_to(root).as_posix(),
                                     "configuration_identity": case["provenance"]["configuration_identity"]})
        (root / "campaign-resolved.yaml").write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
        return root

    def load_resolved_case(self, path: Path | str) -> dict[str, Any]:
        data = self._read_yaml(Path(path))
        if data.get("kind") != "resolved_case":
            raise ResolutionError(f"{path}: kind must be resolved_case")
        # Re-resolve to detect source-profile drift and reject stale generated state.
        selections = _require_mapping(data.get("selections"), f"{path}: selections")
        choices = _require_mapping(data.get("choices"), f"{path}: choices")
        workload_overrides = _require_mapping(data.get("overrides", {}).get("workload", {}), f"{path}: workload overrides")
        fresh = self.resolve_case(campaign_id=str(data.get("campaign", {}).get("id", "generated")),
                                  case_index=int(data.get("campaign", {}).get("case_index", 1)),
                                  selections=selections, choices=choices, workload_overrides=workload_overrides,
                                  execution=dict(data.get("execution", {})))
        if fresh["provenance"]["configuration_identity"] != data.get("provenance", {}).get("configuration_identity"):
            raise ResolutionError("resolved case is stale: selected source profile content has changed")
        return fresh

    def to_legacy_bundle(self, case: dict[str, Any], *, resolve_secrets: bool = True) -> dict[str, dict[str, Any]]:
        """Derive the existing execution bundle without making generated state a second source of truth."""
        s, c = case["selections"], case["choices"]
        target = self.load_profile("target", s["target"]).data
        gateway = self.load_profile("gateway", s["gateway"]).data
        workload = self.load_profile("workload", s["workload"]).data
        workload = _deep_merge(workload, case.get("overrides", {}).get("workload", {}))
        kex = self.load_profile("tls_kex", c["tls_kex"]).data
        auth = self.load_profile("tls_auth", c["tls_auth"]).data
        network = self.load_profile("network_condition", c["network_condition"]).data
        exp_service = self.load_service("mqtt_broker", s["services"]["experiment_broker"]).data
        reporting_service = self.load_service("mqtt_broker", s["services"]["reporting_broker"]).data
        auth_mode = c["auth_mode"]
        klass = kex["class"]
        mode_prefix = "classical_tls" if klass == "classical" else ("pqc_hybrid_tls" if klass == "hybrid_pqc" else "pqc_tls")
        tls_mode = f"{mode_prefix}_{'mutual' if auth_mode == 'mutual' else 'server_auth'}"
        broker_profile = "classical" if klass == "classical" and auth_mode == "mutual" else "classical-server-auth" if klass == "classical" else "oqs-mtls" if auth_mode == "mutual" else "oqs"
        broker = exp_service["listener"]
        topics_prefix = f"pqc/experiments/stm32/{kex['id']}/{auth_mode}"
        transfer = workload.get("transfer", {})
        iterations = workload.get("iterations", {}) if isinstance(workload.get("iterations", {}), dict) else {}
        handshakes_per_run = int(iterations.get("handshakes_per_run", 1)) if iterations else 1
        runtime_hard_limit_seconds = max(180, handshakes_per_run * 60)
        mqtt: dict[str, Any] = {
            "schema_version": 1, "enabled": True,
            "evidence_class": "stm32_st67_classical_tls_e2e" if klass == "classical" else "stm32_st67_pqc_hybrid_tls_e2e" if klass == "hybrid_pqc" else "stm32_st67_pqc_tls_e2e",
            "transport_backend": "st67w61m1_lwip_wolfssl", "broker_profile": broker_profile,
            "broker": {"host": broker["host"], "port": int(broker["tls_port"]), "server_name": broker["server_name"], "dns_required": True},
            "client_id": f"pqc-stm32-{kex['id']}-{auth_mode}",
            "topics": {"command": topics_prefix + "/command", "response": topics_prefix + "/response"},
            "command_payload": "run", "correlation_payload": f"pqc-stm32-{kex['id']}-{auth_mode}-ok",
            "reconnect_attempts": 1,
            "orchestration": {"host": gateway["network"]["address"], "completion_grace_seconds": 3,
                              "hard_limit_seconds": runtime_hard_limit_seconds,
                              "expected_stm32_result_epochs": handshakes_per_run},
            "tls": {"tls_version": "tls1.3", "mode": tls_mode, "authentication": auth_mode,
                    "certificate_profile": auth["id"], "server_signature_algorithm": auth["tls"]["signature_scheme"],
                    "key_exchange_group": kex["id"]},
            "result_schema": {"unavailable_metrics": {"latency_ms": "No synchronized end-to-end latency metric is recorded."}},
        }
        if c.get("mqtt_transport", "tls") == "plaintext":
            mqtt.update({
                "evidence_class": "stm32_st67_plaintext_e2e",
                "transport_backend": "st67w61m1_lwip_sockets",
                # The existing classical broker Compose profile exposes port 1883.
                "broker_profile": "classical",
                "broker": {"host": broker["host"], "port": int(broker["plaintext_port"]),
                           "server_name": broker["server_name"], "dns_required": True},
                "tls": {"mode": "plaintext", "authentication": "server"},
            })
        if transfer:
            mqtt["transfer"] = {"payload_bytes": int(transfer["payload_bytes"]), "chunk_bytes": int(transfer["chunk_bytes"]),
                                "request_topic": topics_prefix + "/response/transfer/request", "response_topic": topics_prefix + "/response/transfer/response",
                                "request_payload": transfer.get("request_payload", "send")}
        wifi = target["network"]["wifi"]
        ssid, psk = "", ""
        if resolve_secrets:
            ssid = self._resolve_secret_ref(wifi["ssid_ref"])
            psk = self._resolve_secret_ref(wifi["psk_ref"])
        resolved_instruments = {}
        for instrument_type, instrument_id in (s.get("instruments") or {}).items():
            instrument = self.load_instrument(instrument_type, instrument_id).data
            resolved_instruments[instrument_type] = {
                "profile": instrument_id,
                "endpoint": instrument.get("endpoint", {}),
                "sampling": instrument.get("sampling", {}),
                "synchronisation": instrument.get("synchronisation", {}),
                "calibration": instrument.get("calibration", {}),
                "evidence": instrument.get("evidence", {}),
                "result_transfer": instrument.get("result_transfer", {}),
            }
        board_id = str(target.get("legacy", {}).get("board_id") or target["id"])
        host_id = str(gateway.get("legacy", {}).get("host_id") or gateway["id"])
        board = {
            "id": board_id,
            "name": target["hardware"]["board"],
            "mcu": target["hardware"]["mcu"],
            "description": target.get("description", target["id"]),
            "stlink": {"serial": gateway["control"]["stlink_serial"]},
            "uart": {"baud": int(target["uart"]["baud"])},
        }
        host = {
            "id": host_id,
            "alias": gateway["identity"].get("fqdn") or gateway["identity"]["alias"],
            "short_alias": gateway["identity"]["alias"],
            "fqdn": gateway["identity"].get("fqdn"),
            "user": gateway["identity"]["ssh_user"],
            "description": gateway.get("description", gateway["id"]),
            "network": dict(gateway.get("network", {})),
            "flash": {"helper": gateway["control"]["flash_helper"]},
            "reset": {"helper": gateway["control"]["reset_helper"]},
            "uart": {
                "device": gateway["uart"]["device"],
                "baud": int(gateway["uart"]["baud"]),
            },
        }
        boot = {
            "id": "direct_flash",
            "mode": "direct_flash",
            "description": "Canonical direct-flash compatibility view derived from selected profiles.",
            "runnable": True,
        }
        experiment = {
            "id": case["id"], "description": f"Resolved canonical case {case['id']}",
            "board": board_id, "host": host_id, "boot": "direct_flash",
            "firmware": {"application": workload["firmware_application"], "uart_log_level": workload.get("uart_log_level", "info"),
                         "uart_output_mode": workload.get("uart_output_mode", "minimal"),
                         "mode": "direct_flash", "artifact": target["build"]["artifact"],
                         "firmware_mode": str(c.get("firmware_mode", "single_bank")),
                         "dual_bank_enabled": str(c.get("firmware_mode", "single_bank")) != "single_bank",
                         "ota_enabled": str(c.get("firmware_mode", "single_bank")) == "dual_bank_ota",
                         "standby_signing_keys": int(c.get("standby_signing_keys", 0))},
            "network": {"wifi": {"ssid": ssid, "psk": psk}, "ipv4": {"mode": target["network"]["ipv4_mode"]},
                        "packet_capture": {"enabled": True, "interface": gateway["network"]["capture_interface"]},
                        "degradation": network.get("impairment", {})},
            "mqtt": mqtt,
            "uart": {"expected_boot_message": target["uart"]["expected_boot_message"], "expected_tick_message": target["uart"]["expected_tick_message"]},
            "services": {"experiment_broker": s["services"]["experiment_broker"], "reporting_broker": s["services"]["reporting_broker"]},
            "workload": {"id": workload["id"], "iterations": dict(iterations)},
            "structured_reporting": {"enabled": True, "schema_version": 1},
            "reporting": {
                "host": reporting_service["listener"]["host"],
                "port": int(reporting_service["listener"]["port"]),
                "transport": "plaintext",
                "tls_enabled": False,
                "impairment_exempt": True,
                "control_run_id_topic": "pqc/control/run-id/current",
                "stm32_topic_prefix": "pqc/result/stm32",
                "instrument_topic_prefix": "pqc/instrument",
            },
            "instruments": resolved_instruments,
            "resolved_configuration": {
                "schema_version": SCHEMA_VERSION,
                "resolver_version": RESOLVER_VERSION,
                "configuration_identity": case["provenance"]["configuration_identity"],
                "firmware_identity": case["provenance"]["firmware_identity"],
                "selected_profiles": s,
                "choices": c,
                "profile_hashes": dict(case.get("provenance", {}).get("profile_hashes", {})),
                "secret_references": {
                    "wifi_ssid": wifi.get("ssid_ref"),
                    "wifi_psk": wifi.get("psk_ref"),
                },
            },
        }
        return {"experiment": experiment, "board": board, "host": host, "boot": boot}

    def _resolve_secret_ref(self, reference: str) -> str:
        if not isinstance(reference, str) or not reference.startswith("env:"):
            raise ResolutionError(f"unsupported secret reference '{reference}'; expected env:<NAME>")
        name = reference[4:]
        value = os.getenv(name)
        if value is None:
            raise ResolutionError(f"required secret environment variable is unavailable: {name}")
        return value


def render_wolfboot_config(target: dict[str, Any], secure_boot: dict[str, Any]) -> str:
    """Generate complete wolfBoot .config from one target and secure-boot profile."""
    common = _require_mapping(target.get("wolfboot", {}).get("config"), "target.wolfboot.config")
    algorithm = _require_mapping(secure_boot.get("wolfboot"), "secure_boot.wolfboot")
    values = _deep_merge(common, algorithm.get("config", {}))
    lines = ["# Generated by PQC canonical resolver; do not edit."]
    for key, value in values.items():
        if isinstance(value, list):
            lines.extend(f"{key}+={item}" for item in value)
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
