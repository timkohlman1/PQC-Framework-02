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

def test_stm32cubemx_cmake_includes_freertos_application_sources():
    stm32cubemx_cmake = Path("cmake/stm32cubemx/CMakeLists.txt").read_text(encoding="utf-8")

    assert "Core/Src/freertos.c" in stm32cubemx_cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/include" in stm32cubemx_cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS" in stm32cubemx_cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F" in stm32cubemx_cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/portable/MemMang/heap_4.c" in stm32cubemx_cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F/port.c" in stm32cubemx_cmake
    assert "add_library(FreeRTOS OBJECT)" in stm32cubemx_cmake
    assert "FreeRTOS" in stm32cubemx_cmake

def test_application_emits_freertos_scheduler_uart_markers():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "FreeRTOS defaultTask created: name=defaultTask priority=osPriorityNormal stack_words=512" in main_c
    assert "FreeRTOS scheduler starting: cmsis_rtos=v1 default_task=defaultTask" in main_c
    assert "tick_hz=" in main_c
    assert "heap_bytes=" in main_c
    assert "default_task_stack_words=512" in main_c
    assert "FreeRTOS defaultTask started: periodic tick task active" in main_c
    assert "APP_PrintFreeRTOSSchedulerStarting();" in main_c
    assert "osKernelStart();" in main_c


def _macro_define_line(config_text: str, macro_name: str) -> str:
    prefix = f"#define {macro_name}"
    for line in config_text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"Missing FreeRTOSConfig macro: {macro_name}")


def test_freertos_config_preserves_expected_scheduler_baseline_settings():
    freertos_config = Path("Core/Inc/FreeRTOSConfig.h").read_text(encoding="utf-8")

    assert "1000" in _macro_define_line(freertos_config, "configTICK_RATE_HZ")
    assert "8192" in _macro_define_line(freertos_config, "configTOTAL_HEAP_SIZE")
    assert " 2" in _macro_define_line(freertos_config, "configCHECK_FOR_STACK_OVERFLOW")
    assert " 1" in _macro_define_line(freertos_config, "configUSE_MALLOC_FAILED_HOOK")
    assert " 1" in _macro_define_line(
        freertos_config,
        "INCLUDE_uxTaskGetStackHighWaterMark",
    )
    assert " 1" in _macro_define_line(
        freertos_config,
        "INCLUDE_uxTaskGetStackHighWaterMark2",
    )


def test_stm32cubemx_ioc_records_freertos_and_tim6_timebase_settings():
    ioc_text = Path("stm32_basic_hal1.ioc").read_text(encoding="utf-8")

    assert "FREERTOS.configTOTAL_HEAP_SIZE=8192" in ioc_text
    assert "FREERTOS.configCHECK_FOR_STACK_OVERFLOW=2" in ioc_text
    assert "FREERTOS.INCLUDE_uxTaskGetStackHighWaterMark=1" in ioc_text
    assert "FREERTOS.INCLUDE_uxTaskGetStackHighWaterMark2=1" in ioc_text
    assert "FREERTOS.Tasks01=defaultTask,0,512,StartDefaultTask,Default,NULL,Dynamic" in ioc_text
    assert "NVIC.TimeBase=TIM6_DAC_IRQn" in ioc_text
    assert "NVIC.TimeBaseIP=TIM6" in ioc_text
    assert "VP_SYS_VS_tim6.Mode=TIM6" in ioc_text


def test_freertos_scheduler_marker_is_emitted_before_scheduler_start():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    marker_index = main_c.index("APP_PrintFreeRTOSSchedulerStarting();")
    scheduler_start_index = main_c.index("osKernelStart();")

    assert marker_index < scheduler_start_index


def test_freertos_tick_runs_from_default_task_not_main_loop():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    task_definition = "void StartDefaultTask(void const * argument)"
    task_start = main_c.rindex(task_definition)
    task_body = main_c[task_start:]

    assert "FreeRTOS defaultTask started: periodic tick task active" in task_body
    assert 'const char tick_msg[] = "tick\\r\\n";' in task_body
    assert "HAL_UART_Transmit(&hlpuart1, (uint8_t *)tick_msg" in task_body
    assert "osDelay(1000);" in task_body
    assert "HAL_Delay(1000);" not in task_body

