from pathlib import Path
import pytest
from scripts.framework.build import _certificate_requires_ecc
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


def test_hybrid_profile_selects_mldsa65_server_signature_without_rsa():
    selected = resolve_tls_algorithm_set(
        _bundle("pqc_hybrid_tls_server_auth", "SecP256r1MLKEM768", "mldsa65")
    )
    assert selected["mldsa_65"] is True
    assert selected["mldsa_65_sign"] is False
    assert selected["rsa"] is False
    assert selected["rsa_pss"] is False
    assert selected["signature_schemes"] == ["mldsa65"]


def test_hybrid_mutual_profile_enables_mldsa65_signing_for_client_certificate_verify():
    selected = resolve_tls_algorithm_set(
        _bundle("pqc_hybrid_tls_mutual", "SecP256r1MLKEM768", "mldsa65")
    )
    assert selected["mldsa_65"] is True
    assert selected["mldsa_65_sign"] is True
    assert selected["signature_schemes"] == ["mldsa65"]


def test_mode_and_group_family_must_match():
    with pytest.raises(ValueError, match="incompatible"):
        resolve_tls_algorithm_set(_bundle("classical_tls_server_auth", "X25519MLKEM768"))


def test_settings_expose_independent_group_capability_guards():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text()
    for marker in ("PQC_TLS_ENABLE_ECC", "PQC_TLS_ECC_BITS", "PQC_TLS_ECC_MIN_BITS", "PQC_TLS_ENABLE_CURVE25519", "PQC_TLS_ENABLE_MLKEM_768", "PQC_TLS_ENABLE_MLKEM_1024"):
        assert marker in settings
    assert "WOLFSSL_NO_ML_KEM_768" in settings
    assert "WOLFSSL_NO_ML_KEM_1024" in settings


def test_settings_disable_tls12_for_tls13_only_group_pruning():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text()
    assert "#define WOLFSSL_TLS13" in settings
    assert "#define WOLFSSL_NO_TLS12" in settings






def test_settings_keep_certificate_curve_floor_separate_from_kex_curve():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text()
    assert "#define ECC_MIN_KEY_SZ PQC_TLS_ECC_MIN_BITS" in settings
    assert "#define ECC_USER_CURVES" in settings
    assert "PQC_TLS_ENABLE_CERT_ECC || PQC_TLS_ECC_BITS == 256" in settings
    assert "#define WOLFSSL_SP_384" in settings
    assert "#define WOLFSSL_SP_521" in settings


def test_settings_expose_profile_selective_mldsa65_verification_support():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text()
    cmake = Path("CMakeLists.txt").read_text()
    for marker in (
        "PQC_TLS_ENABLE_MLDSA_65",
        "WOLFSSL_HAVE_MLDSA",
        "WOLFSSL_MLDSA_VERIFY_ONLY",
        "WOLFSSL_NO_ML_DSA_44",
        "WOLFSSL_NO_ML_DSA_87",
        "wolfcrypt/src/wc_mldsa.c",
    ):
        assert marker in settings + cmake

def test_x25519_mldsa65_build_guards_cover_certificate_verify_and_pk_oid():
    tls13 = Path("Middlewares/Third_Party/wolfSSL/src/tls13.c").read_text(encoding="utf-8")
    internal_h = Path("Middlewares/Third_Party/wolfSSL/wolfssl/internal.h").read_text(
        encoding="utf-8"
    )

    dcv_guard_start = tls13.index(
        "#if !defined(NO_RSA) || defined(HAVE_ECC) || defined(HAVE_ED25519)"
    )
    dcv_type = tls13.index("typedef struct Dcv13Args", dcv_guard_start)
    dcv_guard = tls13[dcv_guard_start:dcv_type]
    assert "defined(WOLFSSL_HAVE_MLDSA)" in dcv_guard

    ssl_struct_start = internal_h.index("word16          certHashSigAlgoSz")
    pk_curve = internal_h.index("word32          pkCurveOID;", ssl_struct_start)
    guard_start = internal_h.rfind("#if ", ssl_struct_start, pk_curve)
    guard = internal_h[guard_start:pk_curve]
    assert "defined(WOLFSSL_HAVE_MLDSA)" in guard



def test_ecdsa_p256_profile_enables_certificate_ecc_independently_of_x25519_kex():
    bundle = _bundle("classical_tls_server_auth", "x25519", "ecdsa_secp256r1_sha256")
    bundle["experiment"]["mqtt"]["tls"]["certificate_profile"] = "ecdsa-p256"
    selected = resolve_tls_algorithm_set(bundle)
    assert selected["curve25519"] is True
    assert selected["signature_schemes"] == ["ecdsa_secp256r1_sha256"]
    assert _certificate_requires_ecc(bundle) is True


def test_certificate_profile_can_supply_default_signature_scheme():
    bundle = _bundle("classical_tls_server_auth", "secp384r1", "")
    bundle["experiment"]["mqtt"]["tls"]["certificate_profile"] = "ecdsa-p384"
    selected = resolve_tls_algorithm_set(bundle)
    assert selected["signature_schemes"] == ["ecdsa_secp384r1_sha384"]


def test_ed25519_profile_fails_explicitly_until_target_build_support_exists():
    bundle = _bundle("classical_tls_server_auth", "x25519", "")
    bundle["experiment"]["mqtt"]["tls"]["certificate_profile"] = "ed25519"
    with pytest.raises(ValueError, match="Ed25519 certificate profiles can be provisioned"):
        resolve_tls_algorithm_set(bundle)


@pytest.mark.parametrize("signature", ["falcon512", "unsupported-pqc-signature"])
def test_unknown_signature_is_rejected(signature):
    with pytest.raises(ValueError, match="Unsupported or missing TLS server signature algorithm"):
        resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth", "SecP256r1MLKEM768", signature))
