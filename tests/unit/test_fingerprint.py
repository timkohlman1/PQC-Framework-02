from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_fingerprint_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "fingerprint.py"
    spec = importlib.util.spec_from_file_location("framework_fingerprint", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_required_inputs(repo_root: Path) -> None:
    files = {
        "configs/experiments/baseline_direct_uart.yaml": "id: baseline_direct_uart\nboard: board_a\nhost: gateway\n",
        "configs/boards/board_a.yaml": "id: board_a\n",
        "configs/hosts/gateway.yaml": "id: gateway\n",
        "CMakeLists.txt": "cmake minimum\n",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c": "HAL driver source\n",
        "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h": "CMSIS device header\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def sample_bundle() -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "id": "baseline_direct_uart",
            "board": "board_a",
            "host": "gateway",
        },
        "board": {
            "id": "board_a",
        },
        "host": {
            "id": "gateway",
        },
    }


def test_build_fingerprint_is_deterministic(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    first = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    second = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert first == second
    assert first.algorithm == "sha256-build-inputs-and-tools-v2"
    assert len(first.fingerprint) == 64
    assert first.inputs == sorted(first.inputs)
    assert list(first.file_hashes) == first.inputs
    assert all(len(value) == 64 for value in first.file_hashes.values())


def test_default_build_fingerprint_covers_phase_9_required_inputs(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    result = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert "Core/Inc/main.h" in result.inputs
    assert "Core/Src/main.c" in result.inputs
    assert "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h" in result.inputs
    assert "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c" in result.inputs
    assert "CMakeLists.txt" in result.inputs
    assert "CMakePresets.json" in result.inputs
    assert "cmake/gcc-arm-none-eabi.cmake" in result.inputs
    assert "STM32L4R5XX_FLASH.ld" in result.inputs
    assert "startup_stm32l4r5xx.s" in result.inputs
    assert "stm32_basic_hal1.ioc" in result.inputs


def test_changing_fingerprinted_file_changes_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    (repo_root / "Core" / "Src" / "main.c").write_text(
        "int main(void) { return 1; }\n",
        encoding="utf-8",
    )
    after = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert before.fingerprint != after.fingerprint
    assert before.file_hashes["Core/Src/main.c"] != after.file_hashes["Core/Src/main.c"]
    unchanged_paths = set(before.file_hashes) - {"Core/Src/main.c"}
    assert all(
        before.file_hashes[path] == after.file_hashes[path]
        for path in unchanged_paths
    )


def test_changing_excluded_file_does_not_change_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    excluded_file = repo_root / "docs" / "notes.md"
    excluded_file.parent.mkdir()
    excluded_file.write_text("documentation-only change\n", encoding="utf-8")
    (repo_root / "results" / "run").mkdir(parents=True)
    (repo_root / "results" / "run" / "manifest.json").write_text("generated\n", encoding="utf-8")
    (repo_root / "build" / "Debug").mkdir(parents=True)
    (repo_root / "build" / "Debug" / "stm32_basic_hal1.elf").write_text("generated\n", encoding="utf-8")
    after = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert before.fingerprint == after.fingerprint


def test_changing_driver_file_changes_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    (
        repo_root
        / "Drivers"
        / "STM32L4xx_HAL_Driver"
        / "Src"
        / "stm32l4xx_hal.c"
    ).write_text("changed HAL driver source\n", encoding="utf-8")
    after = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert before.fingerprint != after.fingerprint


def test_changing_ioc_file_changes_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    (repo_root / "stm32_basic_hal1.ioc").write_text("changed CubeMX project source\n", encoding="utf-8")
    after = fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)

    assert before.fingerprint != after.fingerprint


def test_missing_required_input_fails_clearly(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)
    (repo_root / "CMakeLists.txt").unlink()

    try:
        fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    except fingerprint.FingerprintInputError as exc:
        assert "Required build fingerprint input is missing: CMakeLists.txt" in str(exc)
    else:
        raise AssertionError("missing input must raise FingerprintInputError")


def test_missing_required_directory_fails_clearly(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)
    for path in sorted((repo_root / "Drivers").rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    (repo_root / "Drivers").rmdir()

    try:
        fingerprint.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    except fingerprint.FingerprintInputError as exc:
        assert "Required build fingerprint input is missing: Drivers" in str(exc)
    else:
        raise AssertionError("missing directory input must raise FingerprintInputError")


def test_secure_boot_existing_inputs_fingerprint_records_exact_coverage(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "framework").mkdir(parents=True)
    (repo_root / "scripts" / "framework" / "wolfboot_build.py").write_text("patch source\n", encoding="utf-8")
    (repo_root / "configs" / "builds").mkdir(parents=True)
    (repo_root / "configs" / "builds" / "wolfboot_stm32l4_ecdsa_p256.yaml").write_text("profile\n", encoding="utf-8")

    requested = fingerprint.default_wolfboot_fingerprint_inputs(
        profile_id="wolfboot_stm32l4_ecdsa_p256",
        source_dir="tools/wolfboot",
        config_template=None,
    )
    result = fingerprint.calculate_existing_inputs_fingerprint(repo_root, requested)

    assert result.algorithm == "sha256-secure-boot-inputs-v1"
    assert len(result.fingerprint) == 64
    assert result.inputs == [
        "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
        "scripts/framework/wolfboot_build.py",
    ]


def test_signing_fingerprint_inputs_cover_relocated_linker_script():
    fingerprint = load_fingerprint_module()

    inputs = fingerprint.default_signing_fingerprint_inputs(
        profile_id="wolfboot_ecdsa_p256_app"
    )

    assert "configs/signing/wolfboot_ecdsa_p256_app.yaml" in inputs
    assert "scripts/framework/signing.py" in inputs
    assert "STM32L4R5XX_FLASH_RELOCATED.ld" in inputs
    assert "STM32L4R5XX_FLASH.ld" not in inputs


def test_secure_boot_flash_fingerprint_inputs_cover_artifact_producers():
    fingerprint = load_fingerprint_module()

    inputs = fingerprint.default_secure_boot_flash_fingerprint_inputs(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_id="wolfboot_ecdsa_p256",
    )

    assert "scripts/framework/secure_boot_flash.py" in inputs
    assert "scripts/framework/wolfboot_build.py" in inputs
    assert "scripts/framework/signing.py" in inputs
    assert "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml" in inputs
    assert "configs/signing/wolfboot_ecdsa_p256_app.yaml" in inputs
    assert "configs/wolfboot/stm32l4r5_ecdsa_p256.config" in inputs
    assert "STM32L4R5XX_FLASH_RELOCATED.ld" in inputs
    assert "tools/wolfboot/src/image.c" in inputs


def test_added_source_under_build_relevant_middleware_changes_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "fixed"}
    )
    source = repo_root / "Middlewares" / "Third_Party" / "wolfMQTT" / "src" / "new_component.c"
    source.parent.mkdir(parents=True)
    source.write_text("int new_component(void) { return 1; }\n", encoding="utf-8")
    after = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "fixed"}
    )

    assert before.fingerprint != after.fingerprint
    assert "Middlewares/Third_Party/wolfMQTT/src/new_component.c" in after.inputs


def test_generated_and_unrelated_third_party_files_are_excluded(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    generated = repo_root / "Drivers" / "STM32L4xx_HAL_Driver" / "Src" / "stale.o"
    generated.write_bytes(b"object")
    example = repo_root / "Middlewares" / "Third_Party" / "wolfMQTT" / "examples" / "demo.c"
    example.parent.mkdir(parents=True)
    example.write_text("int demo(void) { return 0; }\n", encoding="utf-8")
    key = repo_root / "Middlewares" / "Third_Party" / "wolfMQTT" / "certs" / "client-key.pem"
    key.parent.mkdir(parents=True)
    key.write_text("test key\n", encoding="utf-8")

    result = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "fixed"}
    )

    assert "Drivers/STM32L4xx_HAL_Driver/Src/stale.o" not in result.inputs
    assert "Middlewares/Third_Party/wolfMQTT/examples/demo.c" not in result.inputs
    assert "Middlewares/Third_Party/wolfMQTT/certs/client-key.pem" not in result.inputs


def test_missing_compiled_source_roots_are_now_covered(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)
    files = {
        "ST67W6X/Target/spi_port.c": "int spi_port(void) { return 0; }\n",
        "LWIP/App/lwip.c": "int lwip_app(void) { return 0; }\n",
        "tools/wolfboot/lib/wolfssl/src/ssl.c": "int wolfssl_ssl(void) { return 0; }\n",
    }
    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    result = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "fixed"}
    )

    for relative_path in files:
        assert relative_path in result.inputs


def test_tool_version_change_changes_fingerprint(tmp_path):
    fingerprint = load_fingerprint_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_required_inputs(repo_root)

    before = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "cmake 3.30", "gcc": "13.2"}
    )
    after = fingerprint.calculate_default_build_fingerprint(
        sample_bundle(), repo_root, tool_versions={"cmake": "cmake 3.31", "gcc": "13.2"}
    )

    assert before.fingerprint != after.fingerprint
    assert after.tool_versions == {"cmake": "cmake 3.31", "gcc": "13.2"}
