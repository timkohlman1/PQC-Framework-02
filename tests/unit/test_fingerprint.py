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
        "CMakeLists.txt": """cmake_minimum_required(VERSION 3.22)\nset(PQC_WOLFSSL_SOURCE_DIR ${CMAKE_SOURCE_DIR}/tools/wolfboot/lib/wolfssl)\ntarget_sources(app PRIVATE Core/Src/main.c)\n""",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": "#include \"main.h\"\nint main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c": "HAL driver source\n",
        "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h": "CMSIS device header\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
        "cmake/stm32cubemx/CMakeLists.txt": "target_sources(STM32_Drivers PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c)\n",
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












def mqtt_tls_bundle() -> dict[str, dict[str, object]]:
    bundle = sample_bundle()
    bundle["experiment"] = dict(bundle["experiment"])
    bundle["experiment"]["mqtt"] = {
        "tls": {
            "certificate_refs": {
                "ca_certificate": "experiment/mqtt-broker/runtime/classical/certs/ca.crt"
            }
        }
    }
    return bundle














