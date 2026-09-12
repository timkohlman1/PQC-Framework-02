from pathlib import Path
import re

import pytest

from scripts.framework.tls_algorithms import TLS_GROUPS, resolve_tls_algorithm_set


PROFILE_DIR = Path("configs/experiments")
GROUPS = list(TLS_GROUPS)


def _scalar(text: str, key: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(key)}:\s*([^#\n]+?)\s*$", text, re.MULTILINE)
    assert matches, f"missing YAML scalar: {key}"
    return matches[-1].strip().strip('"\'')


def test_exact_group_profile_matrix_exists():
    canonical = Path("configs/tls_kex")
    assert {path.stem for path in canonical.glob("*.yaml")} == set(GROUPS)

    # Legacy concrete experiment YAMLs remain temporarily for migration equivalence.
    # They are not required for the three new standalone ML-KEM groups.
    legacy_groups = {
        "x25519", "secp256r1", "secp384r1", "secp521r1",
        "X25519MLKEM768", "SecP256r1MLKEM768", "SecP384r1MLKEM1024",
    }
    profiles = list(PROFILE_DIR.glob("mqtt_tls_*_st67_e2e.yaml"))
    tls_profiles = [p for p in profiles if "plaintext" not in p.name and "schema_fake" not in p.name]
    expected = {f"mqtt_tls_{group}_{auth}_st67_e2e.yaml" for group in legacy_groups for auth in ("server_auth", "mutual_auth")}
    assert expected <= {path.name for path in tls_profiles}


@pytest.mark.parametrize("group", ["x25519", "secp256r1", "secp384r1", "secp521r1", "X25519MLKEM768", "SecP256r1MLKEM768", "SecP384r1MLKEM1024"])
@pytest.mark.parametrize("auth", ["server_auth", "mutual_auth"])
def test_profile_resolves_only_selected_group(group, auth):
    path = PROFILE_DIR / f"mqtt_tls_{group}_{auth}_st67_e2e.yaml"
    text = path.read_text(encoding="utf-8")
    experiment = {
        "mqtt": {
            "tls": {
                "mode": _scalar(text, "mode"),
                "key_exchange_group": _scalar(text, "key_exchange_group"),
                "certificate_profile": _scalar(text, "certificate_profile"),
            }
        }
    }
    selected = resolve_tls_algorithm_set({"experiment": experiment})
    assert selected["key_exchange_groups"] == [group]
    assert selected["ecc"] is bool(TLS_GROUPS[group].get("ecc", False))
    assert selected["curve25519"] is bool(
        TLS_GROUPS[group].get("curve25519", False)
    )
    assert selected["mlkem_768"] is bool(
        TLS_GROUPS[group].get("mlkem_768", False)
    )
    assert selected["mlkem_1024"] is bool(
        TLS_GROUPS[group].get("mlkem_1024", False)
    )


def test_cmake_conditionally_includes_algorithm_sources():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    assert "if(PQC_TLS_ENABLE_ECC OR PQC_TLS_ENABLE_CERT_ECC)" in cmake
    assert "wolfcrypt/src/ecc.c" in cmake
    assert "PQC_TLS_ENABLE_CERT_ECC" in cmake
    assert "if(PQC_TLS_ENABLE_CURVE25519)" in cmake
    assert "wolfcrypt/src/curve25519.c" in cmake
    assert "wolfcrypt/src/fe_low_mem.c" in cmake
    assert "wolfcrypt/src/fe_operations.c" not in cmake
    assert "PQC_TLS_ENABLE_MLKEM_512 OR PQC_TLS_ENABLE_MLKEM_768 OR PQC_TLS_ENABLE_MLKEM_1024" in cmake


def test_runtime_forces_and_verifies_selected_group():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert "int groups[] = { PQC_TLS_GROUP_ID };" in source
    assert "PQC_WolfMQTT_TLSGroupNamesMatch(PQC_TLS_GROUP_NAME, curve_name)" in source
    assert "configured_group=%s negotiated_group=%s key_exchange_group=%s" in source


def test_tls_profiles_use_single_line_scalar_descriptions():
    """The repository YAML loader does not support folded continuation lines."""
    for path in sorted(PROFILE_DIR.glob("mqtt_tls_*_st67_e2e.yaml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2, path
        assert lines[1].startswith("description: "), path
        if len(lines) >= 3:
            assert not lines[2].startswith("  "), (
                f"{path} contains a wrapped top-level description that the minimal "
                "YAML loader interprets as an invalid mapping line"
            )


def test_generated_tls_selection_records_independent_ecc_minimum_bits(tmp_path):
    from scripts.framework.build import _write_tls_algorithm_selection

    bundle = {
        "experiment": {
            "mqtt": {
                "tls": {
                    "mode": "classical_tls_server_auth",
                    "key_exchange_group": "secp521r1",
                    "server_signature_algorithm": "ecdsa_secp256r1_sha256",
                    "certificate_profile": "ecdsa-p256",
                }
            }
        }
    }
    path, selected = _write_tls_algorithm_selection(bundle, tmp_path)
    generated = path.read_text(encoding="utf-8")
    assert selected["ecc_bits"] == 521
    assert selected["ecc_min_bits"] == 256
    assert "set(PQC_TLS_ECC_BITS 521)" in generated
    assert "set(PQC_TLS_ECC_MIN_BITS 256)" in generated
