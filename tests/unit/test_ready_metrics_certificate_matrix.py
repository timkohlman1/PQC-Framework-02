from pathlib import Path

ROOT = Path("configs/experiments/applications/ready_metrics")

KEX_FAMILIES = ("secp256r1", "SecP256r1MLKEM768")
CERTIFICATE_PROFILES = ("rsa3072", "ecdsa-p256", "ecdsa-p384", "mldsa65")
AUTH_MODES = ("server_auth", "mutual_auth")


def _profile_path(kex: str, certificate_profile: str, auth: str) -> Path:
    # The already-validated RSA profiles predate the explicit certificate token
    # in filenames. Keep those canonical files rather than creating duplicates.
    if certificate_profile == "rsa3072":
        name = f"ready_metrics_mqtt_tls_{kex}_{auth}_st67_e2e.yaml"
    else:
        name = (
            f"ready_metrics_mqtt_tls_{kex}_{certificate_profile}_{auth}_st67_e2e.yaml"
        )
    return ROOT / name


def _expected_mode(kex: str, auth: str) -> str:
    if kex == "SecP256r1MLKEM768":
        return (
            "pqc_hybrid_tls_mutual"
            if auth == "mutual_auth"
            else "pqc_hybrid_tls_server_auth"
        )
    return (
        "classical_tls_mutual"
        if auth == "mutual_auth"
        else "classical_tls_server_auth"
    )


def _expected_server_signature_algorithm(certificate_profile: str) -> str:
    return {
        "rsa3072": "classical",
        "ecdsa-p256": "ecdsa_secp256r1_sha256",
        "ecdsa-p384": "ecdsa_secp384r1_sha384",
        "mldsa65": "mldsa65",
    }[certificate_profile]


def _expected_broker(kex: str, certificate_profile: str, auth: str) -> tuple[str, int]:
    oqs_required = kex == "SecP256r1MLKEM768" or certificate_profile == "mldsa65"
    if oqs_required:
        return ("oqs-mtls", 8885) if auth == "mutual_auth" else ("oqs", 8884)
    return ("classical", 8883) if auth == "mutual_auth" else ("classical-server-auth", 8883)


def test_controlled_certificate_comparison_matrix_is_complete():
    expected = {
        _profile_path(kex, certificate_profile, auth)
        for kex in KEX_FAMILIES
        for certificate_profile in CERTIFICATE_PROFILES
        for auth in AUTH_MODES
    }
    missing = sorted(str(path) for path in expected if not path.is_file())
    assert not missing, "missing ready-metrics certificate-comparison profiles:\n" + "\n".join(missing)


def test_controlled_certificate_comparison_matrix_selects_exact_variables():
    for kex in KEX_FAMILIES:
        for certificate_profile in CERTIFICATE_PROFILES:
            for auth in AUTH_MODES:
                path = _profile_path(kex, certificate_profile, auth)
                text = path.read_text(encoding="utf-8")
                broker_profile, broker_port = _expected_broker(kex, certificate_profile, auth)

                assert f"certificate_profile: {certificate_profile}" in text
                assert f"key_exchange_group: {kex}" in text
                assert f"mode: {_expected_mode(kex, auth)}" in text
                assert f"broker_profile: {broker_profile}" in text
                assert f"port: {broker_port}" in text

                if kex == "SecP256r1MLKEM768":
                    expected_signature = _expected_server_signature_algorithm(certificate_profile)
                    assert f"server_signature_algorithm: {expected_signature}" in text

                if auth == "mutual_auth":
                    assert "authentication: mutual" in text
                else:
                    assert "authentication: mutual" not in text


def test_matrix_does_not_create_ed25519_runtime_profiles_before_target_support_exists():
    names = [path.name.lower() for path in ROOT.glob("ready_metrics_mqtt_tls_*_st67_e2e.yaml")]
    assert not any("ed25519" in name for name in names)
