from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

pytestmark = pytest.mark.integration

from framework.tls_instrumentation import (
    expected_tls_instrumentation_events,
    validate_tls_instrumentation_text,
)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _bundle(kex_id: str, auth_id: str, auth_mode: str) -> dict:
    auth = _load_yaml(ROOT / "configs" / "tls_auth" / f"{auth_id}.yaml")
    return {
        "experiment": {
            "mqtt": {
                "tls": {
                    "key_exchange_group": kex_id,
                    "certificate_profile": auth_id,
                    "server_signature_algorithm": auth.get("tls", {}).get("signature_scheme", ""),
                    "authentication": auth_mode,
                }
            }
        }
    }


def _canonical_bundles() -> list[dict]:
    key_exchange = _load_yaml(ROOT / "configs" / "campaigns" / "tls_key_exchange.yaml")
    authentication = _load_yaml(ROOT / "configs" / "campaigns" / "tls_authentication.yaml")

    bundles = [
        _bundle(kex_id, key_exchange["fixed"]["tls_auth"], key_exchange["fixed"]["auth_mode"])
        for kex_id in key_exchange["matrix"]["tls_kex"]
    ]
    bundles.extend(
        _bundle(authentication["fixed"]["tls_kex"], auth_id, auth_mode)
        for auth_id in authentication["matrix"]["tls_auth"]
        for auth_mode in authentication["matrix"]["auth_mode"]
    )
    return bundles


def _synthetic_stream(events: tuple[str, ...]) -> str:
    lines = [
        "PQC_TLS_EVENT_BUFFER schema=1 iteration=0 handshake=0 count=%d capacity=64 "
        "dropped=0 overflow=0 truncated=0 incomplete=0 invalid_sequence_count=0"
        % len(events)
    ]
    for sequence, name in enumerate(events):
        parent = -1 if sequence == 0 else 0
        level = 2 if sequence == 0 else 5
        lines.append(
            "PQC_TLS_EVENT sequence=%d parent_sequence=%d level=%d depth=%d "
            "kind=test name=%s completed=1 result_available=0 result=-2147483648 "
            "start_cycle=1 end_cycle=2 elapsed_cycles=1 start_us=1 end_us=2 elapsed_us=1"
            % (sequence, parent, level, 0 if sequence == 0 else 1, name)
        )
    return "\n".join(lines)


def test_every_canonical_tls_profile_has_complete_profile_aware_expectations():
    bundles = _canonical_bundles()
    assert bundles

    saw_mlkem512 = False
    for bundle in bundles:
        expected = expected_tls_instrumentation_events(bundle)
        assert "handshake" in expected
        assert "server_hello" in expected
        assert "encrypted_extensions" in expected
        assert "certificate" in expected
        assert "certificate_verify" in expected
        assert "finished" in expected
        assert "x509_verify" in expected
        if "mlkem512_keygen" in expected:
            saw_mlkem512 = True
            assert "mlkem512_decapsulate" in expected

        validation = validate_tls_instrumentation_text(bundle, _synthetic_stream(expected))
        assert validation.passed, validation
        assert validation.unavailable_events == ()

    assert saw_mlkem512, "standalone ML-KEM-512 must participate in the canonical coverage matrix"


def test_missing_required_event_is_reported_explicitly_unavailable():
    bundle = _canonical_bundles()[0]
    expected = expected_tls_instrumentation_events(bundle)
    assert len(expected) > 2

    missing = expected[-1]
    validation = validate_tls_instrumentation_text(bundle, _synthetic_stream(expected[:-1]))
    assert not validation.passed
    assert {"event": missing, "status": "unavailable", "reason": "required_record_missing"} in validation.unavailable_events
    assert "required_event_unavailable" in validation.reasons


def test_overflow_rejects_complete_qualification():
    bundle = _canonical_bundles()[0]
    expected = expected_tls_instrumentation_events(bundle)
    stream = _synthetic_stream(expected).replace("overflow=0", "overflow=1", 1)
    validation = validate_tls_instrumentation_text(bundle, stream)
    assert not validation.passed
    assert validation.overflowed
    assert "event_buffer_overflow" in validation.reasons


def test_final_resolved_case_snapshot_layout_is_supported():
    bundle = {
        "effective_non_secret_parameters": {
            "mqtt": {
                "tls": {
                    "key_exchange_group": "x25519",
                    "certificate_profile": "rsa3072",
                    "server_signature_algorithm": "rsa_pss_rsae_sha256",
                    "authentication": "server",
                }
            }
        }
    }
    expected = expected_tls_instrumentation_events(bundle)
    assert "handshake" in expected
    assert "x25519_keygen" in expected
    assert "rsa_verify" in expected


def test_sha_helpers_can_satisfy_coverage_from_aggregate_records():
    bundle = _bundle("x25519", "rsa3072", "server")
    expected = expected_tls_instrumentation_events(bundle)
    ordered = tuple(name for name in expected if name != "sha256")
    stream = _synthetic_stream(ordered) + "\n" + (
        "PQC_TLS_PRIMITIVE name=sha256 count=223 total_cycles=100 min_cycles=1 "
        "max_cycles=10 first_start_cycle=1 last_end_cycle=100 total_us=10 min_us=1 "
        "max_us=2 first_start_us=1 last_end_us=11 timing_source=dwt_cycles "
        "elapsed_time_source=monotonic_us"
    )
    validation = validate_tls_instrumentation_text(bundle, stream)
    assert validation.passed, validation
    assert "sha256" in validation.recorded_events


def test_structured_logical_result_records_are_parsed_directly():
    import json

    bundle = _bundle("x25519", "rsa3072", "server")
    expected = expected_tls_instrumentation_events(bundle)
    plain = _synthetic_stream(expected)
    structured = "\n".join(
        json.dumps(
            {
                "schema_version": 1,
                "source": "stm32",
                "iteration": 0,
                "context": "tls",
                "text": line + "\r\n",
            }
        )
        for line in plain.splitlines()
    )
    validation = validate_tls_instrumentation_text(bundle, structured)
    assert validation.passed, validation
