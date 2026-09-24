"""Static integration contracts; not a substitute for firmware-build/hardware evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_measurement_is_pre_scheduler_and_preserved_until_reporting():
    main = (ROOT / "Core/Src/main.c").read_text()
    before = main.index("PQC_BenchmarkSTM32_Run();")
    after = main.index("osKernelInitialize();", before)
    assert before < after
    assert main.index("PQC_BenchmarkSTM32_AppendResults();", before) < after
    assert "#if !PQC_BAREMETAL_BENCHMARK_ENABLED\n  PQC_ResultBufferReset();" in main
    runner = (ROOT / "Core/Src/pqc_benchmark_stm32.c").read_text()
    assert runner.index("PQC_WolfSSL_BenchmarkMemoryEnable(false);") < runner.index("void PQC_BenchmarkSTM32_AppendResults(void)")
    assert "HAL_RCC_GetHCLKFreq()" in runner


def test_benchmark_has_own_build_mode_and_no_default_arena():
    cmake = (ROOT / "CMakeLists.txt").read_text()
    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "baremetal_benchmark"' in cmake
    assert "Core/Src/pqc_benchmark_stm32.c" in cmake
    memory = (ROOT / "Core/Src/pqc_wolfssl_memory.c").read_text()
    assert "#if PQC_BAREMETAL_BENCHMARK_ENABLED\n#define PQC_BENCHMARK_ARENA_BYTES" in memory
    assert 'section(".pqc_benchmark_arena")' in memory
    assert "PQC_WolfSSL_BenchmarkMemoryEnable(false)" in (ROOT / "Core/Src/pqc_benchmark_stm32.c").read_text()
    for ld in ("STM32L4R5XX_FLASH.ld", "STM32L4R5XX_FLASH_RELOCATED.ld"):
        assert ".pqc_benchmark_arena (NOLOAD)" in (ROOT / ld).read_text()


def test_benchmark_profile_is_versioned_and_has_bounded_repetitions():
    import sys
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    from framework.config_resolver import ConfigResolver, ResolutionError
    import yaml
    import pytest
    if not (ROOT / "configs/gateways/pqc_gateway1.yaml").is_file():
        pytest.skip("minimal AI context archive lacks the gateway/algorithm profiles")
    resolver = ConfigResolver(ROOT)
    profile = resolver.load_profile("workload", "baremetal_benchmark")
    assert profile.data["iterations"]["operations_per_run"] == 10
    assert profile.data["evidence"]["reporting_inside_measurement"] is False
    cases = resolver.expand_campaign("baremetal_benchmark")
    # Three firmware/campaign cases (ML-KEM-512/768/1024); each case runs ten operation repetitions.
    assert len(cases) == 3
    for case in cases:
        assert case["selections"]["workload"] == "baremetal_benchmark"
        assert case["provenance"]["firmware_identity"]
    # Validate bounds before initiating any compilation or hardware actions.
    import pytest
    selections = cases[0]["selections"]
    choices = cases[0]["choices"]
    with pytest.raises(ResolutionError, match="operations_per_run"):
        resolver.resolve_case(campaign_id="negative", case_index=1,
            selections=selections, choices=choices,
            workload_overrides={"iterations": {"operations_per_run": 11}},
            execution=cases[0]["execution"])


def test_mldsa_is_isolated_to_benchmark_build_selection():
    source = (ROOT / "scripts/framework/build.py").read_text()
    assert 'if _resolved_firmware_application(bundle) == "baremetal_benchmark":' in source
    assert 'selected["mldsa_65_sign"] = True' in source
    benchmark = (ROOT / "Core/Src/pqc_benchmark_stm32.c").read_text()
    assert "wc_MlDsaKey_MakeKeyFromSeed" in benchmark
    assert "wc_MlDsaKey_SignCtxWithSeed" in benchmark
    assert "wc_MlDsaKey_VerifyCtx" in benchmark
    assert benchmark.index('PQC_WolfSSL_BenchmarkMemoryEnable(false);') < benchmark.index('void PQC_BenchmarkSTM32_AppendResults(void)')


def test_experiment_runner_accepts_ten_benchmark_repetitions():
    runner = (ROOT / "scripts/experiment.py").read_text()
    assert "1 <= iterations[\"operations_per_run\"] <= 10" in runner
    assert "baremetal_benchmark requires 1-10 workload.iterations.operations_per_run" in runner
