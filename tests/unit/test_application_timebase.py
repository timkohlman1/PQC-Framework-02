from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_application_timebase_uses_dedicated_tim2_at_1mhz_from_active_clock_tree():
    header = _text("Core/Inc/pqc_timebase.h")
    source = _text("Core/Src/pqc_timebase.c")
    ioc = _text("stm32_basic_hal1.ioc")

    assert "PQC_APPLICATION_TIMEBASE_HZ 1000000UL" in header
    assert "PQC_APPLICATION_TIMEBASE_COUNTER_BITS 32U" in header
    assert "s_timebase_tim2.Instance = TIM2" in source
    assert "HAL_RCC_GetPCLK1Freq" in source
    assert "clocks.APB1CLKDivider == RCC_HCLK_DIV1" in source
    assert "timer_input_hz % PQC_APPLICATION_TIMEBASE_HZ" in source
    assert "divider - 1U" in source

    match = re.search(r"RCC\.APB1TimFreq_Value=(\d+)", ioc)
    assert match is not None
    timer_hz = int(match.group(1))
    assert timer_hz == 120_000_000
    assert timer_hz // 1_000_000 - 1 == 119


def test_timebase_is_wrap_extended_and_reads_pending_wrap_safely():
    source = _text("Core/Src/pqc_timebase.c")
    assert "s_timebase_overflow_count++" in source
    assert "TIM_SR_UIF" in source
    assert "(uint64_t)high_before << 32" in source
    assert "high_before != high_after" in source
    assert "PQC_TimebaseElapsedUs" in source


def test_hal_tick_remains_owned_by_tim1_and_research_timer_uses_tim2():
    hal_timebase = _text("Core/Src/stm32l4xx_hal_timebase_tim.c")
    app_timebase = _text("Core/Src/pqc_timebase.c")
    assert "htim1.Instance = TIM1" in hal_timebase
    assert "HAL_IncTick" in _text("Core/Src/main.c")
    assert "TIM1" not in app_timebase
    assert "TIM2" in app_timebase


def test_research_measurement_paths_no_longer_use_hal_gettick():
    mqtt = _text("Core/Src/pqc_wolfmqtt_build_only.c")
    tls = _text("Core/Src/pqc_tls_instrumentation.c")
    assert "HAL_GetTick" not in mqtt
    assert "HAL_GetTick" not in tls
    assert "PQC_TimebaseNowUs" in mqtt
    assert "PQC_TimebaseNowUs" in tls


def test_dwt_cycle_measurement_remains_separate_from_microsecond_timebase():
    tls = _text("Core/Src/pqc_tls_instrumentation.c")
    assert "DWT->CYCCNT" in tls
    assert "handshake_elapsed_cycles" in tls
    assert "handshake_elapsed_us" in tls
    assert "PQC_TimebaseNowUs" in tls


def test_result_contract_identifies_microseconds_and_cycles_separately():
    mqtt = _text("Core/Src/pqc_wolfmqtt_build_only.c")
    parser = _text("scripts/experiment.py")
    assert 'application_timebase' in mqtt
    assert 'counter_hz' in mqtt
    assert 'timing_source' in mqtt and 'dwt_cycles' in mqtt
    assert 'elapsed_us' in mqtt
    assert 'timebase.get("counter_hz") == 1_000_000' in parser
    assert 'x509.get("timing_source") == "dwt_cycles"' in parser
    assert 'handshake.get("timing_sources") == "dwt_cycles+application_timebase_us"' in parser


def test_manifest_boundary_keeps_application_timings_in_raw_result_stream():
    manifest = _text("scripts/framework/manifest.py")
    run_evidence = _text("scripts/framework/run_evidence.py")
    # Request 16 architecture keeps scientific timing fields out of the immutable
    # run manifest; exact ELF identity remains build/deployment provenance.
    assert "application_ttfb_us" not in manifest
    assert "application_ttfb_us" not in run_evidence
    assert "sha256" in manifest.lower() or "sha256" in run_evidence.lower()


def test_hardware_timebase_test_is_self_contained_and_uses_wolfboot_run_path():
    hardware_test = _text("tests/hardware/test_application_timebase_hw.py")
    assert 'resolver.load_campaign("baseline")' in hardware_test
    assert '"-DPQC_TIMEBASE_HARDWARE_SELF_TEST=ON"' in hardware_test
    assert '"scripts/experiment.py"' in hardware_test
    assert '"run"' in hardware_test
    assert '"wolfBoot verification result: 0"' in hardware_test
    assert 'PQC_TIMEBASE_UART_LOG' not in hardware_test.split("def test_application_timebase_known_delay_and_hal_tick_unchanged", 1)[1]


def test_microsecond_serialization_avoids_newlib_nano_long_long_printf():
    tls = _text("Core/Src/pqc_tls_instrumentation.c")
    mqtt = _text("Core/Src/pqc_wolfmqtt_build_only.c")
    toolchain = _text("cmake/gcc-arm-none-eabi.cmake")

    assert "--specs=nano.specs" in toolchain
    assert "%llu" not in tls
    assert "%llu" not in mqtt
    assert "PQC_TLS_FormatU64" in tls
    assert "PQC_WolfMQTT_FormatU64" in mqtt
    assert '"start_us=%s end_us=%s elapsed_us=%s' in tls
    assert '\"elapsed_us\":%s' in mqtt
    assert '\"reset_origin_to_application_timebase_us\":%s' in mqtt
