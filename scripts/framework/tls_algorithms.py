"""Resolve experiment TLS profiles into deterministic build capabilities."""
from __future__ import annotations

from typing import Any

TLS_GROUPS: dict[str, dict[str, Any]] = {
    "x25519": {"token": "WOLFSSL_ECC_X25519", "curve25519": True},
    "secp256r1": {"token": "WOLFSSL_ECC_SECP256R1", "ecc": True, "ecc_bits": 256},
    "secp384r1": {"token": "WOLFSSL_ECC_SECP384R1", "ecc": True, "ecc_bits": 384},
    "secp521r1": {"token": "WOLFSSL_ECC_SECP521R1", "ecc": True, "ecc_bits": 521},
    "X25519MLKEM768": {"token": "WOLFSSL_X25519MLKEM768", "curve25519": True, "mlkem_768": True, "hybrid": True},
    "SecP256r1MLKEM768": {"token": "WOLFSSL_SECP256R1MLKEM768", "ecc": True, "ecc_bits": 256, "mlkem_768": True, "hybrid": True},
    "SecP384r1MLKEM1024": {"token": "WOLFSSL_SECP384R1MLKEM1024", "ecc": True, "ecc_bits": 384, "mlkem_1024": True, "hybrid": True},
}

def resolve_tls_algorithm_set(bundle: dict[str, dict[str, Any]]) -> dict[str, Any]:
    experiment = bundle.get("experiment", {})
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    mode = str(tls.get("mode", "plaintext")).strip().lower()
    certificate_profile = str(tls.get("certificate_profile", "")).strip().lower()
    server_signature = str(tls.get("server_signature_algorithm", "")).strip().lower()
    if not server_signature:
        server_signature = {
            "rsa3072": "rsa_pss_rsae_sha256",
            "ecdsa-p256": "ecdsa_secp256r1_sha256",
            "ecdsa-p384": "ecdsa_secp384r1_sha384",
            "ed25519": "ed25519",
            "mldsa65": "mldsa65",
        }.get(certificate_profile, "")
    selected = {
        "schema_version": 3, "mode": mode, "rsa": False, "rsa_pss": False,
        "ecc": False, "ecc_bits": 0, "curve25519": False,
        "mlkem_768": False, "mlkem_1024": False, "mldsa_65": False, "mldsa_65_sign": False, "hybrid": False,
        "signature_schemes": [], "key_exchange_groups": [],
        "group_name": "none", "group_token": "0",
    }
    if mode in {"plaintext", "", "none"}:
        return selected
    if mode not in {"classical_tls_server_auth", "classical_tls_mutual", "pqc_hybrid_tls_server_auth", "pqc_hybrid_tls_mutual"}:
        raise ValueError(f"Unsupported MQTT TLS mode for STM32 algorithm selection: {mode}")
    group = str(tls.get("key_exchange_group", "")).strip()
    if group not in TLS_GROUPS:
        raise ValueError("Unsupported or missing MQTT TLS key-exchange group: " + (group or "<missing>") + ". Supported groups: " + ", ".join(TLS_GROUPS))
    capabilities = TLS_GROUPS[group]
    mode_is_hybrid = mode.startswith("pqc_hybrid_")
    if mode_is_hybrid != bool(capabilities.get("hybrid", False)):
        raise ValueError(f"MQTT TLS mode '{mode}' is incompatible with key-exchange group '{group}'")
    mutual_auth = mode.endswith("_mutual") or str(tls.get("authentication", "")).strip().lower() == "mutual"
    if server_signature in {"classical", "rsa", "rsa3072", "rsa_pss_rsae_sha256"}:
        signature = {"rsa": True, "rsa_pss": True, "mldsa_65": False, "mldsa_65_sign": False, "signature_schemes": ["rsa_pss_rsae_sha256"]}
    elif server_signature in {"ecdsa-p256", "ecdsa_secp256r1_sha256"}:
        signature = {"rsa": False, "rsa_pss": False, "mldsa_65": False, "mldsa_65_sign": False, "signature_schemes": ["ecdsa_secp256r1_sha256"]}
    elif server_signature in {"ecdsa-p384", "ecdsa_secp384r1_sha384"}:
        signature = {"rsa": False, "rsa_pss": False, "mldsa_65": False, "mldsa_65_sign": False, "signature_schemes": ["ecdsa_secp384r1_sha384"]}
    elif server_signature in {"mldsa65", "ml-dsa-65"}:
        signature = {"rsa": False, "rsa_pss": False, "mldsa_65": True, "mldsa_65_sign": mutual_auth, "signature_schemes": ["mldsa65"]}
    elif server_signature == "ed25519":
        raise ValueError("Ed25519 certificate profiles can be provisioned, but STM32 TLS Ed25519 build support is not configured yet")
    else:
        raise ValueError(
            "Unsupported or missing TLS server signature algorithm for certificate profile "
            + (certificate_profile or "<missing>")
        )
    selected.update(capabilities)
    selected.update(signature)
    selected.update(key_exchange_groups=[group], group_name=group, group_token=capabilities["token"] )
    return selected

def cmake_boolean(value: bool) -> str:
    return "ON" if value else "OFF"
