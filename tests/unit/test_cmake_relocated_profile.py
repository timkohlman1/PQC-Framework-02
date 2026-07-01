import json
from pathlib import Path


def test_relocated_debug_cmake_preset_selects_relocated_linker_script():
    presets = json.loads(Path("CMakePresets.json").read_text(encoding="utf-8"))

    configure_presets = {preset["name"]: preset for preset in presets["configurePresets"]}
    build_presets = {preset["name"]: preset for preset in presets["buildPresets"]}

    relocated = configure_presets["RelocatedDebug"]

    assert relocated["inherits"] == "default"
    assert relocated["binaryDir"] == "${sourceDir}/build/${presetName}"
    assert relocated["cacheVariables"]["CMAKE_BUILD_TYPE"] == "Debug"
    assert (
        relocated["cacheVariables"]["STM32_LINKER_SCRIPT"]
        == "${sourceDir}/STM32L4R5XX_FLASH_RELOCATED.ld"
    )
    assert relocated["cacheVariables"]["STM32_APP_VECTOR_OFFSET"] == "0x00022000"
    assert build_presets["RelocatedDebug"]["configurePreset"] == "RelocatedDebug"


def test_relocated_linker_script_places_flash_at_bootloader_entry_address():
    linker_script = Path("STM32L4R5XX_FLASH_RELOCATED.ld").read_text(encoding="utf-8")

    assert "ORIGIN = 0x08022000" in linker_script
    assert "LENGTH = 0x000DE000" in linker_script
    assert "wolfBoot image header is reserved at 0x08020000..0x08021FFF" in linker_script


def test_linker_script_is_selected_once_by_toolchain_file():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    toolchain = Path("cmake/gcc-arm-none-eabi.cmake").read_text(encoding="utf-8")

    assert "target_link_options(${CMAKE_PROJECT_NAME} PRIVATE" not in root_cmake
    assert "STM32_LINKER_SCRIPT" in toolchain
    assert '-T \\\"${STM32_LINKER_SCRIPT}\\\"' in toolchain
    assert '-T \\\"${CMAKE_SOURCE_DIR}/STM32L4R5XX_FLASH.ld\\\"' not in toolchain
