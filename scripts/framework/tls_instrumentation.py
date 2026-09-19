"""Profile-aware qualification helpers for raw STM32 TLS instrumentation.

The execution path captures raw records without inserting scientific metrics into
manifest.json.  This module derives the semantic event set expected from a
resolved/legacy experiment bundle and can qualify a retained raw text stream.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable


_EVENT_LINE = re.compile(r"(?:^|\s)PQC_TLS_EVENT\s+(?P<body>.*)$")
_BUFFER_LINE = re.compile(r"(?:^|\s)PQC_TLS_EVENT_BUFFER\s+(?P<body>.*)$")
_PRIMITIVE_LINE = re.compile(r"(?:^|\s)PQC_TLS_PRIMITIVE\s+(?P<body>.*)$")


@dataclass(frozen=True)
class TLSInstrumentationValidation:
    passed: bool
    expected_events: tuple[str, ...]
    recorded_events: tuple[str, ...]
    unavailable_events: tuple[dict[str, str], ...]
    overflowed: bool
    truncated: bool
    hierarchy_incomplete: bool
    invalid_sequence_count: int
    reasons: tuple[str, ...]


def _tls_dict(bundle: dict[str, Any]) -> dict[str, Any]:
    # Final run-capture snapshots store effective non-secret parameters at the
    # top level. Retain the legacy experiment.mqtt.tls path for older fixtures
    # and historical schema-v1 inputs.
    effective = bundle.get("effective_non_secret_parameters", {})
    if isinstance(effective, dict):
        mqtt = effective.get("mqtt", {})
        if isinstance(mqtt, dict):
            tls = mqtt.get("tls", {})
            if isinstance(tls, dict) and tls:
                return tls

    experiment = bundle.get("experiment", {})
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    return tls if isinstance(tls, dict) else {}


def expected_tls_instrumentation_events(bundle: dict[str, Any]) -> tuple[str, ...]:
    """Return ordered semantic events required by the resolved TLS profile."""
    tls = _tls_dict(bundle)
    if not tls:
        return ()

    expected: list[str] = [
        "handshake",
        "server_hello",
        "encrypted_extensions",
        "certificate",
        "certificate_verify",
        "finished",
        "sha256",
        "hkdf_extract",
        "hkdf_expand",
        "x509_verify",
    ]

    group = str(tls.get("key_exchange_group", "")).strip().lower()
    if "secp256r1" in group:
        expected.extend(("p256_keygen", "p256_shared_secret"))
    elif "secp384r1" in group:
        expected.extend(("p384_keygen", "p384_shared_secret"))
    elif "secp521r1" in group:
        expected.extend(("p521_keygen", "p521_shared_secret"))
    elif "x25519" in group:
        expected.extend(("x25519_keygen", "x25519_shared_secret"))

    if "mlkem512" in group or "ml_kem_512" in group:
        expected.extend(("mlkem512_keygen", "mlkem512_decapsulate"))
    if "mlkem768" in group or "ml_kem_768" in group:
        expected.extend(("mlkem768_keygen", "mlkem768_decapsulate"))
    if "mlkem1024" in group or "ml_kem_1024" in group:
        expected.extend(("mlkem1024_keygen", "mlkem1024_decapsulate"))

    certificate_profile = str(tls.get("certificate_profile", "")).strip().lower()
    if certificate_profile == "ecdsa-p384":
        expected.append("sha384")

    signature = str(tls.get("server_signature_algorithm", "")).strip().lower()
    if not signature:
        signature = {
            "rsa3072": "rsa_pss_rsae_sha256",
            "ecdsa-p256": "ecdsa_secp256r1_sha256",
            "ecdsa-p384": "ecdsa_secp384r1_sha384",
            "mldsa65": "mldsa65",
        }.get(certificate_profile, "")

    if signature == "mldsa65":
        verify_event, sign_event = "mldsa65_verify", "mldsa65_sign"
    elif signature in {
        "ecdsa-p256",
        "ecdsa_secp256r1_sha256",
        "ecdsa-p384",
        "ecdsa_secp384r1_sha384",
    }:
        verify_event, sign_event = "ecdsa_verify", "ecdsa_sign"
    else:
        verify_event, sign_event = "rsa_verify", "rsa_sign"

    expected.append(verify_event)
    if str(tls.get("authentication", "server")).strip().lower() == "mutual":
        expected.append(sign_event)

    # Stable de-duplication preserves hierarchy/coverage readability.
    return tuple(dict.fromkeys(expected))


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in body.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return fields


def _iter_payload_lines(text: str) -> Iterable[str]:
    """Yield instrumentation payload text from raw or structured logical records."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = None
            if isinstance(record, dict) and isinstance(record.get("text"), str):
                for payload_line in record["text"].splitlines():
                    if payload_line.strip():
                        yield payload_line.strip()
                continue
        yield line


def validate_tls_instrumentation_text(
    bundle: dict[str, Any], text: str
) -> TLSInstrumentationValidation:
    """Qualify hierarchy/completeness without changing the raw evidence."""
    expected = expected_tls_instrumentation_events(bundle)
    if not expected:
        return TLSInstrumentationValidation(
            passed=True,
            expected_events=(),
            recorded_events=(),
            unavailable_events=(),
            overflowed=False,
            truncated=False,
            hierarchy_incomplete=False,
            invalid_sequence_count=0,
            reasons=(),
        )

    status: dict[str, str] | None = None
    events: list[dict[str, str]] = []
    primitive_aggregates: set[str] = set()
    for line in _iter_payload_lines(text):
        if "PQC_TLS_EVENT" in line:
            buffer_match = _BUFFER_LINE.search(line)
            if buffer_match:
                status = _parse_fields(buffer_match.group("body"))
                continue
            event_match = _EVENT_LINE.search(line)
            if event_match:
                fields = _parse_fields(event_match.group("body"))
                if fields.get("name"):
                    events.append(fields)
                continue
        if "PQC_TLS_PRIMITIVE" in line:
            primitive_match = _PRIMITIVE_LINE.search(line)
            if primitive_match:
                fields = _parse_fields(primitive_match.group("body"))
                name = fields.get("name")
                try:
                    count = int(fields.get("count", "0"))
                except ValueError:
                    count = 0
                if name and count > 0:
                    primitive_aggregates.add(name)

    reasons: list[str] = []
    if status is None:
        reasons.append("event_buffer_status_missing")
        overflowed = truncated = hierarchy_incomplete = True
        invalid_sequence_count = 0
    else:
        overflowed = status.get("overflow") != "0"
        truncated = status.get("truncated") != "0"
        hierarchy_incomplete = status.get("incomplete") != "0"
        try:
            invalid_sequence_count = int(status.get("invalid_sequence_count", "0"))
        except ValueError:
            invalid_sequence_count = 1
            reasons.append("invalid_sequence_count_malformed")
        if overflowed:
            reasons.append("event_buffer_overflow")
        if truncated:
            reasons.append("event_buffer_truncated")
        if hierarchy_incomplete or invalid_sequence_count:
            reasons.append("event_hierarchy_incomplete")

    completed_events = [e for e in events if e.get("completed") == "1"]
    ordered_names = tuple(e["name"] for e in completed_events)
    # Aggregate-only SHA-2 helpers are still valid recorded primitive evidence.
    # The ordered hierarchy intentionally reserves its bounded slots for TLS
    # phases, security functions, KEX/signature operations and HKDF boundaries.
    recorded_set = set(ordered_names) | primitive_aggregates
    recorded_names = tuple(dict.fromkeys((*ordered_names, *sorted(primitive_aggregates))))
    unavailable = tuple(
        {"event": name, "status": "unavailable", "reason": "required_record_missing"}
        for name in expected
        if name not in recorded_set
    )
    if unavailable:
        reasons.append("required_event_unavailable")

    # Sequence must be unique and monotonically ordered in the serialized event
    # stream. A parent must precede its child; -1 is the root sentinel.
    seen_sequences: set[int] = set()
    last_sequence = -1
    for event in completed_events:
        try:
            sequence = int(event.get("sequence", "-1"))
            parent = int(event.get("parent_sequence", "-2"))
        except ValueError:
            reasons.append("event_sequence_malformed")
            continue
        if sequence in seen_sequences or sequence <= last_sequence:
            reasons.append("event_sequence_invalid")
        if parent >= sequence or (parent != -1 and parent not in seen_sequences):
            reasons.append("event_parent_invalid")
        seen_sequences.add(sequence)
        last_sequence = max(last_sequence, sequence)

    passed = not reasons
    return TLSInstrumentationValidation(
        passed=passed,
        expected_events=expected,
        recorded_events=recorded_names,
        unavailable_events=unavailable,
        overflowed=overflowed,
        truncated=truncated,
        hierarchy_incomplete=hierarchy_incomplete,
        invalid_sequence_count=invalid_sequence_count,
        reasons=tuple(dict.fromkeys(reasons)),
    )
