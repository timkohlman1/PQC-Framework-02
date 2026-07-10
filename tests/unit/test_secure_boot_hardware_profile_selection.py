from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tests" / "hardware" / "test_secure_boot_algorithm_benchmarks.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("secure_boot_hw_profiles", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mldsa65_is_the_default_selected_profile() -> None:
    module = _load_module()
    assert module._selected_benchmark_profile_names({}) == {"mldsa65"}


def test_named_profiles_are_added_to_default_mldsa65() -> None:
    module = _load_module()
    selected = module._selected_benchmark_profile_names(
        {"PQC_HARDWARE_SECURE_BOOT_PROFILES": "ecc256, mldsa44"}
    )
    assert selected == {"mldsa65", "ecc256", "mldsa44"}


def test_all_profiles_environment_selects_complete_matrix() -> None:
    module = _load_module()
    selected = module._selected_benchmark_profile_names(
        {"PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES": "1"}
    )
    assert selected == {profile.name for profile in module.BENCHMARK_PROFILES}


def test_unknown_profile_is_rejected() -> None:
    module = _load_module()
    with pytest.raises(pytest.UsageError, match="Unknown secure-boot hardware profile"):
        module._selected_benchmark_profile_names(
            {"PQC_HARDWARE_SECURE_BOOT_PROFILES": "not-a-profile"}
        )


def test_pytest_startup_cleanup_does_not_delete_wolfboot_tuple_keys() -> None:
    conftest_text = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    cleanup_block = conftest_text.split("WOLFBOOT_GENERATED_FILES_TO_CLEAN = (", 1)[1].split(")", 1)[0]
    assert "wolfboot_signing_private_key.der" not in cleanup_block
    assert "wolfboot_signing_public_key.der" not in cleanup_block
    assert "src/keystore.c" not in cleanup_block
