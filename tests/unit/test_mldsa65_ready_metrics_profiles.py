from pathlib import Path


ROOT = Path("configs/experiments/applications/ready_metrics")
GROUPS = ("SecP256r1MLKEM768", "SecP384r1MLKEM1024", "X25519MLKEM768")


def test_mldsa65_ready_metrics_matrix_is_additive_and_complete():
    for group in GROUPS:
        for auth in ("server_auth", "mutual_auth"):
            classical = ROOT / f"ready_metrics_mqtt_tls_{group}_{auth}_st67_e2e.yaml"
            pqc_auth = ROOT / f"ready_metrics_mqtt_tls_{group}_mldsa65_{auth}_st67_e2e.yaml"
            assert classical.is_file()
            assert pqc_auth.is_file()
            text = pqc_auth.read_text(encoding="utf-8")
            assert f"key_exchange_group: {group}" in text
            assert "server_signature_algorithm: mldsa65" in text
            assert "certificate_profile: mldsa65" in text
            if auth == "mutual_auth":
                assert "authentication: mutual" in text
                assert "broker_profile: oqs-mtls" in text
            else:
                assert "broker_profile: oqs" in text


def test_classical_ready_metrics_profiles_use_explicit_rsa3072_certificate_profile():
    for group in GROUPS:
        for auth in ("server_auth", "mutual_auth"):
            text = (ROOT / f"ready_metrics_mqtt_tls_{group}_{auth}_st67_e2e.yaml").read_text(encoding="utf-8")
            assert "certificate_profile: rsa3072" in text


def test_mldsa65_certificate_profile_is_config_driven():
    profile = Path("configs/certificate_profile/mldsa65.yaml").read_text(encoding="utf-8")
    assert "id: mldsa65" in profile
    assert "openssl_algorithm: ML-DSA-65" in profile
    assert "tls_signature_scheme: mldsa65" in profile


def test_mldsa65_mutual_tls_does_not_retain_temporary_no_identity_profile():
    diagnostic = ROOT / "ready_metrics_mqtt_tls_SecP256r1MLKEM768_mldsa65_mutual_auth_no_client_identity_st67_e2e.yaml"
    assert not diagnostic.exists()
