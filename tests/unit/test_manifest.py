from __future__ import annotations

import importlib.util
import json
import struct
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path


def load_manifest_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "framework" / "manifest.py"
    spec = importlib.util.spec_from_file_location("manifest", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minimal_elf32(path: Path) -> None:
    shstrtab = b"\x00.text\x00.data\x00.bss\x00.rodata\x00.shstrtab\x00"
    name_offsets = {
        ".text": shstrtab.index(b".text"),
        ".data": shstrtab.index(b".data"),
        ".bss": shstrtab.index(b".bss"),
        ".rodata": shstrtab.index(b".rodata"),
        ".shstrtab": shstrtab.index(b".shstrtab"),
    }

    text = b"T" * 11
    data = b"D" * 7
    rodata = b"R" * 3
    header_size = 52
    text_offset = header_size
    data_offset = text_offset + len(text)
    rodata_offset = data_offset + len(data)
    shstrtab_offset = rodata_offset + len(rodata)
    section_header_offset = shstrtab_offset + len(shstrtab)
    section_header_size = 40

    elf_ident = b"\x7fELF" + bytes([1, 1, 1]) + b"\x00" * 9
    header = struct.pack(
        "<16sHHIIIIIHHHHHH",
        elf_ident,
        2,
        40,
        1,
        0,
        0,
        section_header_offset,
        0,
        header_size,
        0,
        0,
        section_header_size,
        6,
        5,
    )

    def section_header(name: str, section_type: int, flags: int, offset: int, size: int) -> bytes:
        return struct.pack(
            "<IIIIIIIIII",
            name_offsets.get(name, 0),
            section_type,
            flags,
            0,
            offset,
            size,
            0,
            0,
            4,
            0,
        )

    section_headers = b"".join(
        [
            section_header("", 0, 0, 0, 0),
            section_header(".text", 1, 0x6, text_offset, len(text)),
            section_header(".data", 1, 0x3, data_offset, len(data)),
            section_header(".bss", 8, 0x3, 0, 5),
            section_header(".rodata", 1, 0x2, rodata_offset, len(rodata)),
            section_header(".shstrtab", 3, 0, shstrtab_offset, len(shstrtab)),
        ]
    )
    path.write_bytes(header + text + data + rodata + shstrtab + section_headers)


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_bundle() -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "id": "baseline_direct_uart",
            "description": "Test experiment.",
            "board": "board_a",
            "host": "gateway",
            "boot": "direct_flash",
            "firmware": {
                "mode": "direct_flash",
                "artifact": "build/Debug/stm32_basic_hal1.elf",
            },
            "uart": {
                "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
                "expected_tick_message": "tick",
            },
        },
        "board": {
            "id": "board_a",
            "name": "NUCLEO-L4R5ZI-P",
            "mcu": "STM32L4R5",
            "stlink": {
                "serial": "123",
            },
            "uart": {
                "baud": 115200,
            },
        },
        "boot": {
            "id": "direct_flash",
            "mode": "direct_flash",
            "description": "Direct-flash test boot config.",
            "runnable": True,
        },
        "host": {
            "id": "gateway",
            "alias": "pqc-gateway1",
            "user": "timk",
            "flash": {
                "helper": "flash-stm32a",
            },
            "uart": {
                "device": "/dev/example",
                "baud": 115200,
            },
        },
    }


def write_sample_configs(configs_root: Path) -> Path:
    boards_dir = configs_root / "boards"
    hosts_dir = configs_root / "hosts"
    boot_dir = configs_root / "boot"
    experiments_dir = configs_root / "experiments"

    boards_dir.mkdir(parents=True)
    hosts_dir.mkdir(parents=True)
    boot_dir.mkdir(parents=True)
    experiments_dir.mkdir(parents=True)

    (boards_dir / "board_a.yaml").write_text(
        "\n".join(
            [
                "id: board_a",
                "name: NUCLEO-L4R5ZI-P",
                "mcu: STM32L4R5",
                "description: Test board.",
                "stlink:",
                '  serial: "123"',
                "uart:",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (boot_dir / "direct_flash.yaml").write_text(
        "\n".join(
            [
                "id: direct_flash",
                "mode: direct_flash",
                "description: Direct-flash test boot config.",
                "runnable: true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (hosts_dir / "gateway.yaml").write_text(
        "\n".join(
            [
                "id: gateway",
                "alias: pqc-gateway1",
                "user: timk",
                "description: Test gateway.",
                "flash:",
                "  helper: flash-stm32a",
                "uart:",
                "  device: /dev/example",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    experiment_path = experiments_dir / "baseline_direct_uart.yaml"
    experiment_path.write_text(
        "\n".join(
            [
                "id: baseline_direct_uart",
                "description: Test experiment.",
                "board: board_a",
                "host: gateway",
                "boot: direct_flash",
                "firmware:",
                "  mode: direct_flash",
                "  artifact: build/Debug/stm32_basic_hal1.elf",
                "uart:",
                "  expected_boot_message: stm32-basic_hal1 boot v0.1.0",
                "  expected_tick_message: tick",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return experiment_path


def test_next_run_id_uses_date_and_next_sequence(tmp_path):
    manifest = load_manifest_module()
    results_root = tmp_path / "results"
    results_root.mkdir()
    (results_root / "2026-06-25_001_baseline_direct_uart").mkdir()
    (results_root / "2026-06-25_002_other_experiment").mkdir()
    (results_root / "not-a-run-id").mkdir()

    run_id = manifest.next_run_id(
        "baseline_direct_uart",
        results_root,
        datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc),
    )

    assert run_id == "2026-06-25_003_baseline_direct_uart"


def test_build_manifest_contains_initial_fields():
    manifest = load_manifest_module()
    timestamp = datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc)

    data = manifest.build_manifest(sample_bundle(), "2026-06-25_001_baseline_direct_uart", timestamp)

    assert data == {
        "run_id": "2026-06-25_001_baseline_direct_uart",
        "timestamp": "2026-06-25T10:30:00+00:00",
        "experiment": "baseline_direct_uart",
        "board": "board_a",
        "gateway": "gateway",
        "boot_mode": "direct_flash",
        "transport_mode": "direct_uart",
        "network_profile": "none",
        "result": "pending",
    }


def test_create_result_folder_writes_manifest_and_notes(tmp_path):
    manifest = load_manifest_module()
    results_root = tmp_path / "results"
    timestamp = datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc)

    result_dir, data = manifest.create_result_folder(sample_bundle(), results_root, timestamp)

    assert result_dir.name == "2026-06-25_001_baseline_direct_uart"
    assert (result_dir / "manifest.json").is_file()
    assert (result_dir / "notes.md").is_file()

    written_manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert written_manifest == data
    assert written_manifest["result"] == "pending"
    assert "Add manual observations" in (result_dir / "notes.md").read_text(encoding="utf-8")


def test_create_run_command_creates_result_folder_without_hardware_actions(tmp_path, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    results_root = tmp_path / "results"

    exit_code = experiment_cli.run_create_run_command(
        Namespace(experiment=experiment_path, results_dir=results_root)
    )

    output = capsys.readouterr().out
    result_dirs = list(results_root.iterdir())

    assert exit_code == 0
    assert len(result_dirs) == 1
    assert (result_dirs[0] / "manifest.json").is_file()
    assert (result_dirs[0] / "notes.md").is_file()
    assert "No build, flash, UART access, SSH, hardware access, or network access was performed." in output


def test_build_secure_boot_benchmark_model_records_phase_11_1_schema_and_unavailable_metrics():
    manifest = load_manifest_module()

    benchmark = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
        image_version=1,
        wolfboot_artifact_path="tools/wolfboot/wolfboot.elf",
        wolfboot_sha256="abc",
        wolfboot_elf_size_bytes=12345,
        signed_application_artifact_path="build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        signed_application_sha256="def",
        signed_application_size_bytes=54321,
        verification_time_ms=17,
        verification_cycles=1360000,
        verification_cpu_hz=80000000,
        verification_result_code=0,
        verification_time_source="uart_explicit_verification_time_marker",
        verification_cycles_source="uart_explicit_verification_cycles_marker",
        runtime_measurement_method="Explicit UART marker parsed from application mailbox output.",
        runtime_limitations="Host-side capture duration is not verification time.",
    )

    assert benchmark["schema_version"] == 1
    assert benchmark["model_phase"] == "phase_11_1_schema_only"
    assert benchmark["benchmark_scope"] == "secure_boot_classical_signing_algorithm"
    assert benchmark["profile_id"] == "wolfboot_ecdsa_p256_uart"
    assert benchmark["build_time_metrics"]["status"] == "unavailable"
    assert benchmark["build_time_metrics"]["bootloader_text_bytes"] is None
    assert benchmark["signed_artifact_metrics"]["status"] == "partial"
    assert benchmark["signed_artifact_metrics"]["wolfboot_elf_size_bytes"] == 12345
    assert benchmark["signed_artifact_metrics"]["signed_application_size_bytes"] == 54321
    assert benchmark["signed_artifact_metrics"]["unsigned_application_size_unavailable"]["status"] == "unavailable"
    assert benchmark["runtime_verification_metrics"]["status"] == "available"
    assert benchmark["runtime_verification_metrics"]["verification_time_ms"] == 17
    assert benchmark["runtime_memory_metrics"]["status"] == "unavailable"
    assert benchmark["runtime_memory_metrics"]["max_stack_used_bytes"] is None
    assert benchmark["repeated_run_samples"]["status"] == "not_configured"
    assert benchmark["repeated_run_samples"]["samples"] == []
    assert benchmark["repeated_run_samples"]["sample_schema"]["verification_time_source"] is None
    assert benchmark["repeated_run_samples"]["sample_schema"]["verification_cycles_source"] is None
    assert benchmark["aggregate_statistics"]["status"] == "unavailable"
    assert benchmark["aggregate_statistics"]["verification_time_ms"]["median"] is None


def test_phase_11_2_repeated_run_samples_and_aggregate_statistics_use_valid_samples_only():
    manifest = load_manifest_module()

    base = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
    )
    artifact_identity = {
        "wolfboot_sha256": "wolfboot-sha",
        "signed_application_sha256": "app-sha",
    }
    samples = [
        manifest.build_secure_boot_benchmark_sample(
            run_index=1,
            timestamp="2026-06-30T10:00:00+10:00",
            verification_time_ms=17,
            verification_cycles=1360000,
            verification_cpu_hz=80000000,
            verification_result_code=0,
            verification_time_source="uart_explicit_verification_time_marker",
            verification_cycles_source="uart_explicit_verification_cycles_marker",
            uart_marker_detection_result={"boot_marker_present": True, "tick_present": True, "secure_boot_marker_present": True},
            sample_verdict="passed",
            referenced_artifact_identity=artifact_identity,
        ),
        manifest.build_secure_boot_benchmark_sample(
            run_index=2,
            timestamp="2026-06-30T10:01:00+10:00",
            verification_time_ms=19,
            verification_cycles=1520000,
            verification_cpu_hz=80000000,
            verification_result_code=0,
            verification_time_source="uart_explicit_verification_time_marker",
            verification_cycles_source="uart_explicit_verification_cycles_marker",
            uart_marker_detection_result={"boot_marker_present": True, "tick_present": True, "secure_boot_marker_present": True},
            sample_verdict="passed",
            referenced_artifact_identity=artifact_identity,
        ),
        manifest.build_secure_boot_benchmark_sample(
            run_index=3,
            timestamp="2026-06-30T10:02:00+10:00",
            verification_time_ms=None,
            verification_cycles=None,
            verification_cpu_hz=None,
            verification_result_code=None,
            verification_time_source="unavailable",
            verification_cycles_source="unavailable",
            uart_marker_detection_result={"boot_marker_present": False, "tick_present": False, "secure_boot_marker_present": False},
            sample_verdict="failed",
            referenced_artifact_identity=artifact_identity,
        ),
    ]

    updated = manifest.apply_repeated_run_samples_to_benchmark_model(base, samples)

    assert updated["model_phase"] == "phase_11_2_repeated_run_support"
    assert updated["repeated_run_samples"]["status"] == "completed"
    assert updated["repeated_run_samples"]["samples"] == samples
    assert samples[0]["valid_for_statistics"] is True
    assert samples[2]["valid_for_statistics"] is False
    aggregate = updated["aggregate_statistics"]
    assert aggregate["status"] == "available"
    assert aggregate["sample_count"] == 3
    assert aggregate["valid_sample_count"] == 2
    assert aggregate["failed_sample_count"] == 1
    assert aggregate["verification_time_ms"]["minimum"] == 17
    assert aggregate["verification_time_ms"]["mean"] == 18
    assert aggregate["verification_time_ms"]["median"] == 18.0
    assert aggregate["verification_time_ms"]["maximum"] == 19
    assert round(aggregate["verification_time_ms"]["standard_deviation"], 6) == 1.414214
    assert aggregate["verification_time_ms"]["range"] == 2
    assert round(aggregate["verification_time_ms"]["coefficient_of_variation_percent"], 6) == 7.856742
    assert aggregate["verification_cycles"]["median"] == 1440000.0
    assert aggregate["verification_cycles"]["range"] == 160000
    assert aggregate["headline_metrics"] == {
        "primary_verification_time_ms": 18.0,
        "primary_verification_cycles": 1440000.0,
        "primary_statistic": "median",
    }
    assert "Repeated execution has not been configured for this run." not in updated["limitations"]
    assert (
        "Aggregate statistics require repeated-run samples; no repeated samples are available for this run."
        not in updated["limitations"]
    )


def test_secure_boot_benchmark_sample_records_metric_sources_and_unavailable_memory():
    manifest = load_manifest_module()

    sample = manifest.build_secure_boot_benchmark_sample(
        run_index=1,
        timestamp="2026-07-01T10:00:00+10:00",
        verification_time_ms=12,
        verification_cycles=960000,
        verification_cpu_hz=80000000,
        verification_result_code=0,
        verification_time_source="uart_explicit_verification_time_marker",
        verification_cycles_source="uart_explicit_verification_cycles_marker",
        uart_marker_detection_result={"secure_boot_marker_present": True},
        sample_verdict="passed",
        referenced_artifact_identity={"signed_application_sha256": "abc"},
    )

    assert sample["verification_time_source"] == "uart_explicit_verification_time_marker"
    assert sample["verification_cycles_source"] == "uart_explicit_verification_cycles_marker"
    assert sample["valid_for_statistics"] is True
    assert sample["runtime_memory_metrics"]["max_stack_used_bytes"] is None
    assert sample["runtime_memory_metrics"]["stack_metric_source"] == "unavailable"
    assert sample["runtime_memory_metrics"]["heap_metric_source"] == "unavailable"


def test_read_elf_alloc_section_metrics_reads_static_resource_sizes(tmp_path):
    manifest = load_manifest_module()
    elf_path = tmp_path / "wolfboot.elf"
    write_minimal_elf32(elf_path)

    metrics = manifest.read_elf_alloc_section_metrics(elf_path)

    assert metrics["bootloader_text_bytes"] == 11
    assert metrics["bootloader_data_bytes"] == 7
    assert metrics["bootloader_bss_bytes"] == 5
    assert metrics["bootloader_flash_bytes"] == 21
    assert metrics["bootloader_static_ram_bytes"] == 12
    assert metrics["static_ram_bytes"] == 12


def test_build_secure_boot_benchmark_model_records_phase_11_3_static_metrics_and_overhead():
    manifest = load_manifest_module()

    benchmark = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
        wolfboot_artifact_path="tools/wolfboot/wolfboot.elf",
        wolfboot_elf_size_bytes=1000,
        retained_wolfboot_artifact_path="tools/wolfboot/wolfboot.elf",
        retained_wolfboot_artifact_size_bytes=1000,
        unsigned_application_artifact_path="build/RelocatedDebug/stm32_basic_hal1.bin",
        unsigned_application_size_bytes=500,
        signed_application_artifact_path="build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        signed_application_size_bytes=564,
        bootloader_text_bytes=300,
        bootloader_data_bytes=40,
        bootloader_bss_bytes=80,
        bootloader_flash_bytes=340,
        bootloader_static_ram_bytes=120,
        static_metrics_source="wolfboot_elf_section_headers",
    )

    assert benchmark["model_phase"] == "phase_11_3_static_build_resource_metrics"
    assert benchmark["build_time_metrics"]["status"] == "available"
    assert benchmark["build_time_metrics"]["bootloader_text_bytes"] == 300
    assert benchmark["build_time_metrics"]["bootloader_data_bytes"] == 40
    assert benchmark["build_time_metrics"]["bootloader_bss_bytes"] == 80
    assert benchmark["build_time_metrics"]["bootloader_flash_bytes"] == 340
    assert benchmark["build_time_metrics"]["bootloader_static_ram_bytes"] == 120
    assert benchmark["build_time_metrics"]["static_ram_bytes"] == 120
    signed_metrics = benchmark["signed_artifact_metrics"]
    assert signed_metrics["status"] == "available"
    assert signed_metrics["retained_wolfboot_artifact_size_bytes"] == 1000
    assert signed_metrics["unsigned_application_size_bytes"] == 500
    assert signed_metrics["signed_application_size_bytes"] == 564
    assert signed_metrics["signed_image_overhead_bytes"] == 64
    assert signed_metrics["signed_image_overhead_percent"] == 12.8
    assert signed_metrics["unsigned_application_size_unavailable"] is None
    assert signed_metrics["signed_image_overhead_unavailable"] is None
    assert benchmark["runtime_memory_metrics"]["status"] == "unavailable"
    assert benchmark["runtime_memory_metrics"]["max_stack_used_bytes"] is None


def test_apply_repeated_run_samples_preserves_phase_11_3_static_metrics():
    manifest = load_manifest_module()
    base = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
        wolfboot_artifact_path="tools/wolfboot/wolfboot.elf",
        wolfboot_elf_size_bytes=1000,
        unsigned_application_artifact_path="build/RelocatedDebug/stm32_basic_hal1.bin",
        unsigned_application_size_bytes=500,
        signed_application_artifact_path="build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        signed_application_size_bytes=564,
        bootloader_text_bytes=300,
        bootloader_data_bytes=40,
        bootloader_bss_bytes=80,
        bootloader_flash_bytes=340,
        bootloader_static_ram_bytes=120,
        static_metrics_source="wolfboot_elf_section_headers",
    )
    sample = manifest.build_secure_boot_benchmark_sample(
        run_index=1,
        timestamp="2026-06-30T00:00:00+10:00",
        verification_time_ms=41,
        verification_cycles=3253764,
        verification_cpu_hz=80000000,
        verification_result_code=0,
        verification_time_source="uart_explicit_verification_time_marker",
        verification_cycles_source="uart_explicit_verification_cycles_marker",
        uart_marker_detection_result={"secure_boot_marker_present": True},
        sample_verdict="passed",
        referenced_artifact_identity={"wolfboot_sha256": "abc", "signed_application_sha256": "def"},
    )

    updated = manifest.apply_repeated_run_samples_to_benchmark_model(base, [sample])

    assert updated["model_phase"] == "phase_11_3_static_build_resource_metrics"
    assert updated["build_time_metrics"]["status"] == "available"
    assert updated["build_time_metrics"]["bootloader_text_bytes"] == 300
    assert updated["signed_artifact_metrics"]["unsigned_application_size_bytes"] == 500
    assert updated["signed_artifact_metrics"]["signed_image_overhead_bytes"] == 64
    assert updated["aggregate_statistics"]["sample_count"] == 1


def test_build_secure_boot_benchmark_model_records_phase_11_4_runtime_stack_metrics():
    manifest = load_manifest_module()

    benchmark = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
        bootloader_text_bytes=300,
        bootloader_data_bytes=40,
        bootloader_bss_bytes=80,
        bootloader_flash_bytes=340,
        bootloader_static_ram_bytes=120,
        static_metrics_source="wolfboot_elf_section_headers",
        max_stack_used_bytes=2048,
        stack_metric_source="uart_explicit_stack_high_water_marker",
        runtime_memory_limitations="Stack evidence came from explicit firmware-side instrumentation.",
    )

    assert benchmark["model_phase"] == "phase_11_4_runtime_memory_metrics"
    memory = benchmark["runtime_memory_metrics"]
    assert memory["status"] == "available"
    assert memory["unavailable"] is None
    assert memory["max_stack_used_bytes"] == 2048
    assert memory["stack_metric_source"] == "uart_explicit_stack_high_water_marker"
    assert memory["heap_used_bytes"] is None
    assert memory["heap_metric_source"] == "unavailable"
    assert memory["static_ram_bytes"] == 120
    assert memory["estimated_total_ram_pressure_bytes"] == 2168
    assert "Runtime stack and heap metrics require explicit firmware-side measurement evidence" not in "\n".join(benchmark["limitations"])


def test_build_secure_boot_benchmark_model_records_phase_11_5a_classical_profile_metadata():
    manifest = load_manifest_module()

    benchmark = manifest.build_secure_boot_benchmark_model(
        experiment_id="wolfboot_ecdsa_p256_uart",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        signature_algorithm="ecdsa_p256",
        signature_size_bytes=64,
        bootloader_text_bytes=300,
        bootloader_data_bytes=40,
        bootloader_bss_bytes=80,
        bootloader_flash_bytes=340,
        bootloader_static_ram_bytes=120,
        static_metrics_source="wolfboot_elf_section_headers",
        classical_profile_metadata={
            "model_phase": "phase_11_5a_classical_profile_model",
            "profile_id": "ecc256_reference",
            "algorithm": "ECC256",
            "signature_algorithm": "ecdsa_p256",
            "minimum_comparison_scope": {
                "required_algorithms": ["ED25519", "ECC256", "RSA2048"],
                "implemented_reference_algorithm": "ECC256",
                "planned_non_runnable_algorithms": ["ED25519", "RSA2048"],
            },
            "capability_status": {
                "ed25519": {"runnable": False, "status": "planned_phase_11_5b_not_implemented"},
                "rsa2048": {"runnable": False, "status": "planned_phase_11_5c_not_implemented"},
            },
        },
    )

    assert benchmark["model_phase"] == "phase_11_5a_classical_profile_model"
    profile = benchmark["classical_profile_metadata"]
    assert profile["profile_id"] == "ecc256_reference"
    assert profile["algorithm"] == "ECC256"
    assert profile["minimum_comparison_scope"]["required_algorithms"] == ["ED25519", "ECC256", "RSA2048"]
    assert profile["capability_status"]["ed25519"]["runnable"] is False
    assert profile["capability_status"]["rsa2048"]["runnable"] is False
