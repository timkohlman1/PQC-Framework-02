from pathlib import Path
import re

import pytest

from scripts.framework.tls_algorithms import TLS_GROUPS, resolve_tls_algorithm_set


GROUPS = list(TLS_GROUPS)


def _scalar(text: str, key: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(key)}:\s*([^#\n]+?)\s*$", text, re.MULTILINE)
    assert matches, f"missing YAML scalar: {key}"
    return matches[-1].strip().strip('"\'')


def test_exact_group_profile_matrix_exists():
    profiles = list(Path("configs/experiments").glob("mqtt_tls_*_st67_e2e.yaml"))
    tls_profiles = [p for p in profiles if "plaintext" not in p.name and "schema_fake" not in p.name]
    expected = {f"mqtt_tls_{g}_{a}_st67_e2e.yaml" for g in GROUPS for a in ("server_auth", "mutual_auth")}
    assert {p.name for p in tls_profiles} == expected


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("auth", ["server_auth", "mutual_auth"])
def test_profile_resolves_only_selected_group(group, auth):
    path = Path("configs/experiments") / f"mqtt_tls_{group}_{auth}_st67_e2e.yaml"
    text = path.read_text(encoding="utf-8")
    experiment = {
        "mqtt": {
            "tls": {
                "mode": _scalar(text, "mode"),
                "key_exchange_group": _scalar(text, "key_exchange_group"),
                "server_signature_algorithm": _scalar(text, "server_certificate_algorithm"),
            }
        }
    }
    selected = resolve_tls_algorithm_set({"experiment": experiment})
    assert selected["key_exchange_groups"] == [group]
    assert selected["ecc"] is bool(TLS_GROUPS[group].get("ecc", False))
    assert selected["curve25519"] is bool(TLS_GROUPS[group].get("curve25519", False))
    assert selected["mlkem_768"] is bool(TLS_GROUPS[group].get("mlkem_768", False))
    assert selected["mlkem_1024"] is bool(TLS_GROUPS[group].get("mlkem_1024", False))


def test_cmake_conditionally_includes_algorithm_sources():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    assert "if(PQC_TLS_ENABLE_ECC)" in cmake and "wolfcrypt/src/ecc.c" in cmake
    assert "if(PQC_TLS_ENABLE_CURVE25519)" in cmake and "wolfcrypt/src/curve25519.c" in cmake
    assert "PQC_TLS_ENABLE_MLKEM_768 OR PQC_TLS_ENABLE_MLKEM_1024" in cmake


def test_runtime_forces_and_verifies_selected_group():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert "int groups[] = { PQC_TLS_GROUP_ID };" in source
    assert "strcmp(curve_name, PQC_TLS_GROUP_NAME) == 0" in source
