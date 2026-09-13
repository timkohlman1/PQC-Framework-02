from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = REPO_ROOT / "configs" / "campaigns" / "secure_boot.yaml"
SECURE_BOOT_DIR = REPO_ROOT / "configs" / "secure_boot"

EXPECTED_SECURE_BOOT_PROFILES = [
    "integrity_sha256",
    "ecdsa_p256",
    "ecdsa_p384",
    "ecdsa_p521",
    "ed25519",
    "ed448",
    "rsa2048",
    "rsa3072",
    "rsa4096",
    "mldsa44",
    "mldsa65",
    "mldsa87",
]


def _campaign() -> dict:
    return yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))


def test_secure_boot_campaign_selects_complete_canonical_matrix() -> None:
    campaign = _campaign()
    assert campaign["matrix"]["secure_boot"] == EXPECTED_SECURE_BOOT_PROFILES


def test_secure_boot_campaign_matrix_has_no_duplicate_profiles() -> None:
    selected = _campaign()["matrix"]["secure_boot"]
    assert len(selected) == len(set(selected))


def test_secure_boot_campaign_profiles_exist_and_match_ids() -> None:
    for profile_id in _campaign()["matrix"]["secure_boot"]:
        path = SECURE_BOOT_DIR / f"{profile_id}.yaml"
        assert path.is_file(), f"missing canonical secure-boot profile: {path}"
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["id"] == profile_id
        assert profile["profile_type"] == "secure_boot"


def test_secure_boot_campaign_uses_canonical_generated_case_execution_model() -> None:
    campaign = _campaign()
    assert campaign["id"] == "secure_boot"
    assert campaign["execution"]["evidence"] == "per_run"
    assert campaign["execution"]["reset_between_runs"] == "hardware_reset"
    assert campaign["execution"]["build"] == "once_per_firmware_identity"
    assert campaign["execution"]["flash"] == "once_per_firmware_identity"


def test_pytest_startup_cleanup_does_not_delete_wolfboot_tuple_keys() -> None:
    conftest_text = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    cleanup_block = conftest_text.split("WOLFBOOT_GENERATED_FILES_TO_CLEAN = (", 1)[1].split(")", 1)[0]
    assert "wolfboot_signing_private_key.der" not in cleanup_block
    assert "wolfboot_signing_public_key.der" not in cleanup_block
    assert "src/keystore.c" not in cleanup_block
