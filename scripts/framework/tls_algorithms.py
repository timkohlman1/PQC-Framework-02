"""Resolve experiment TLS profiles into deterministic build capabilities."""
from __future__ import annotations

from typing import Any


def resolve_tls_algorithm_set(bundle: dict[str, dict[str, Any]]) -> dict[str, Any]:
    experiment = bundle.get("experiment", {})
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    mode = str(tls.get("mode", "plaintext")).strip().lower()
    server_signature = str(tls.get("server_signature_algorithm", "")).strip().lower()

    selected = {
        "schema_version": 2,
        "mode": mode,
        "rsa": False,
        "rsa_pss": False,
        "mlkem_768": False,
        "signature_schemes": [],
        "key_exchange_groups": [],
    }
    if mode in {"plaintext", "", "none"}:
        return selected
    if mode in {"classical_tls_server_auth", "classical_tls_mutual"}:
        selected.update(
            rsa=True,
            rsa_pss=True,
            signature_schemes=["rsa_pss_rsae_sha256"],
            key_exchange_groups=["secp256r1"],
        )
        return selected
    if mode in {"pqc_hybrid_tls_server_auth", "pqc_hybrid_tls_mutual"}:
        if server_signature not in {"", "classical", "rsa", "rsa_pss_rsae_sha256"}:
            raise ValueError(
                "Unsupported TLS server signature algorithm: "
                f"{server_signature}. PQC hybrid MQTT TLS uses classical RSA server authentication."
            )
        selected.update(
            rsa=True,
            rsa_pss=True,
            mlkem_768=True,
            signature_schemes=["rsa_pss_rsae_sha256"],
            key_exchange_groups=["p256_mlkem768"],
        )
        return selected
    raise ValueError(f"Unsupported MQTT TLS mode for STM32 algorithm selection: {mode}")


def cmake_boolean(value: bool) -> str:
    return "ON" if value else "OFF"
