from pathlib import Path

import pytest

from scripts.framework.tls_algorithms import resolve_tls_algorithm_set


def _bundle(mode: str, signature: str = ""):
    return {"experiment": {"mqtt": {"tls": {"mode": mode, "server_signature_algorithm": signature}}}}


def test_classical_profile_selects_only_classical_tls_algorithms():
    selected = resolve_tls_algorithm_set(_bundle("classical_tls_server_auth", "classical"))
    assert selected["rsa"] is True
    assert selected["rsa_pss"] is True
    assert selected["mlkem_768"] is False
    assert selected["signature_schemes"] == ["rsa_pss_rsae_sha256"]


def test_hybrid_profile_adds_mlkem_but_keeps_classical_authentication():
    selected = resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth", "classical"))
    assert selected["rsa"] is True
    assert selected["rsa_pss"] is True
    assert selected["mlkem_768"] is True
    assert selected["signature_schemes"] == ["rsa_pss_rsae_sha256"]
    assert selected["key_exchange_groups"] == ["p256_mlkem768"]


@pytest.mark.parametrize("signature", ["falcon512", "unsupported-pqc-signature"])
def test_hybrid_profile_rejects_nonclassical_server_signatures(signature):
    with pytest.raises(ValueError, match="classical RSA server authentication"):
        resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth", signature))


def test_tls_build_files_exclude_unselected_signature_sources():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    build = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    assert "wolfcrypt/src/wc_mlkem.c" in cmake
    assert "wolfcrypt/src/wc_mlkem_poly.c" in cmake


def test_rsa_pss_native_wolfssl_macro_is_enabled():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    assert "#if PQC_TLS_ENABLE_RSA && PQC_TLS_ENABLE_RSA_PSS" in settings
    assert "#define WC_RSA_PSS" in settings
    assert "#define NO_RSA_PSS" in settings
