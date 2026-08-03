from pathlib import Path
import pytest
from scripts.framework.tls_algorithms import TLS_GROUPS, resolve_tls_algorithm_set


def _bundle(mode: str, group: str, signature: str = "classical"):
    return {"experiment": {"mqtt": {"tls": {"mode": mode, "key_exchange_group": group, "server_signature_algorithm": signature}}}}


def test_classical_profile_selects_only_requested_classical_group():
    selected = resolve_tls_algorithm_set(_bundle("classical_tls_server_auth", "secp384r1"))
    assert selected["key_exchange_groups"] == ["secp384r1"]
    assert selected["ecc"] is True
    assert selected["ecc_bits"] == 384
    assert selected["curve25519"] is False
    assert selected["mlkem_768"] is False
    assert selected["mlkem_1024"] is False


def test_hybrid_profile_selects_only_requested_hybrid_group():
    selected = resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth", "SecP384r1MLKEM1024"))
    assert selected["key_exchange_groups"] == ["SecP384r1MLKEM1024"]
    assert selected["ecc_bits"] == 384
    assert selected["mlkem_1024"] is True
    assert selected["mlkem_768"] is False


@pytest.mark.parametrize("signature", ["falcon512", "unsupported-pqc-signature"])
def test_hybrid_profile_rejects_nonclassical_server_signatures(signature):
    with pytest.raises(ValueError, match="classical RSA server authentication"):
        resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth", "SecP256r1MLKEM768", signature))


def test_mode_and_group_family_must_match():
    with pytest.raises(ValueError, match="incompatible"):
        resolve_tls_algorithm_set(_bundle("classical_tls_server_auth", "X25519MLKEM768"))


def test_settings_expose_independent_group_capability_guards():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text()
    for marker in ("PQC_TLS_ENABLE_ECC", "PQC_TLS_ECC_BITS", "PQC_TLS_ENABLE_CURVE25519", "PQC_TLS_ENABLE_MLKEM_768", "PQC_TLS_ENABLE_MLKEM_1024"):
        assert marker in settings
    assert "WOLFSSL_NO_ML_KEM_768" in settings
    assert "WOLFSSL_NO_ML_KEM_1024" in settings
