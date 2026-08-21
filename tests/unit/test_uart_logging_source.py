from pathlib import Path


def test_uart_logger_prefixes_complete_lines_with_hal_tick():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "static void APP_UART_FlushLine(void)" in source
    assert "static void APP_UART_WriteTickPrefix(void)" in source
    assert "uint32_t tick = HAL_GetTick();" in source
    assert "APP_UART_WriteRaw(\"\\r\\n\", 2U);" in source


def test_uart_logger_supports_off_error_info_and_debug_levels():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "APP_UART_LOG_LEVEL_OFF  (-1)" in source
    assert "APP_UART_LOG_LEVEL_ERROR 0" in source
    assert "APP_UART_LOG_LEVEL_INFO  1" in source
    assert "APP_UART_LOG_LEVEL_DEBUG 2" in source
    assert "APP_UART_ShouldEmitLine" in source


def test_bounded_validation_no_longer_emits_standalone_tick_heartbeat():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert 'const char tick_msg[] = "tick\\r\\n"' not in source
    assert "heartbeat_seconds" not in source


def test_cmake_maps_profile_uart_log_level_to_compile_definition():
    source = Path("cmake/stm32cubemx/CMakeLists.txt").read_text(encoding="utf-8")
    assert 'PQC_UART_LOG_LEVEL STREQUAL "off"' in source
    assert 'set(PQC_UART_LOG_LEVEL_VALUE -1)' in source
    assert 'PQC_UART_LOG_LEVEL STREQUAL "error"' in source
    assert 'PQC_UART_LOG_LEVEL STREQUAL "info"' in source
    assert 'PQC_UART_LOG_LEVEL STREQUAL "debug"' in source
    assert "PQC_UART_LOG_LEVEL=${PQC_UART_LOG_LEVEL_VALUE}" in source


def test_uart_uint32_conversion_does_not_reverse_in_place():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "char reversed_digits[10];" in source
    assert "char output[11];" in source
    assert "output[index++] = reversed_digits[count - 1U];" in source
    assert "digits[index++] = digits[--count];" not in source


def test_info_filter_suppresses_whitespace_and_complete_st67_banner_tail():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "APP_UART_LineIsWhitespaceOnly" in source
    assert '"Trim BLE:"' in source
    assert '"Trim XTAL:"' in source
    assert '"MAC Address:"' in source
    assert '"Anti-rollback Bootloader:"' in source
    assert '"Anti-rollback App:"' in source
