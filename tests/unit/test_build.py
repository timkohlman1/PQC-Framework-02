from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path



def materialize_baseline_case(tmp_path: Path, monkeypatch) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    shutil.copytree(repo_root / "configs", tmp_path / "configs")
    monkeypatch.setenv("PQC_WIFI_SSID", "pqc")
    monkeypatch.setenv("PQC_WIFI_PSK", "test-psk")
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    from framework.config_resolver import ConfigResolver
    resolver = ConfigResolver(tmp_path)
    root = resolver.materialize_campaign(
        "baseline", tmp_path / ".pqc-generated-state" / "campaigns" / "baseline"
    )
    return sorted((root / "cases").glob("*.yaml"))[0]

def load_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = repo_root / "scripts" / "framework" / "build.py"
    spec = importlib.util.spec_from_file_location("framework_build", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
                "artifact": "build/Release/stm32_basic_hal1.elf",
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


def write_initial_manifest(result_dir: Path) -> None:
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-25_001_baseline_direct_uart",
                "timestamp": "2026-06-25T10:30:00+00:00",
                "experiment": "baseline_direct_uart",
                "board": "board_a",
                "gateway": "gateway",
                "boot_mode": "direct_flash",
                "transport_mode": "direct_uart",
                "network_profile": "none",
                "result": "pending",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_build_fingerprint_inputs(repo_root: Path) -> None:
    """Create the required fingerprint input set without invoking toolchains."""

    files = {
        "configs/targets/stm32l4r5_st67.yaml": "id: stm32l4r5_st67\nprofile_type: target\n",
        "configs/gateways/pqc_gateway1.yaml": "id: pqc_gateway1\nprofile_type: gateway\n",
        "configs/workloads/baseline.yaml": "id: baseline\nprofile_type: workload\n",
        "CMakeLists.txt": "add_executable(stm32_basic_hal1 Core/Src/main.c startup_stm32l4r5xx.s)\n",
        "cmake/stm32cubemx/CMakeLists.txt": "target_sources(stm32cubemx INTERFACE Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c)\n",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": '#include "main.h"\nint main(void) { return 0; }\n',
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c": "HAL driver source\n",
        "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h": "CMSIS device header\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_build_command_construction_uses_cmake_presets():
    build = load_build_module()

    assert build.construct_configure_command("Debug") == ["cmake", "--preset", "Debug"]
    assert build.construct_build_command("Debug") == ["cmake", "--build", "--preset", "Debug"]










def test_run_build_command_reports_no_flash_or_network_actions(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    monkeypatch.setattr(experiment_cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    experiment_path = materialize_baseline_case(tmp_path, monkeypatch)

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_execute_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["configure_preset"] == "Debug"
        assert kwargs["build_preset"] == "Debug"
        return FakeBuildResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)

    exit_code = experiment_cli.run_build_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            artifact=None,
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Firmware build completed" in output
    assert "No flash, UART access, SSH, hardware access, or network access was performed." in output


def test_run_build_flash_command_uses_one_result_directory_for_build_and_flash(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    monkeypatch.setattr(experiment_cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    experiment_path = materialize_baseline_case(tmp_path, monkeypatch)

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 0
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    fake_flash_result = FakeFlashResult()

    def fake_execute_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["configure_preset"] == "Debug"
        assert kwargs["build_preset"] == "Debug"
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(seen_result_dirs) == 2
    assert seen_result_dirs[0] == seen_result_dirs[1]
    assert "Build-flash completed" in output
    assert "Build log:" in output
    assert "Flash log:" in output
    assert manifest["result"] == "build_flash_passed"
    assert manifest["build_flash"]["build_return_code"] == 0
    assert manifest["build_flash"]["flash_return_code"] == 0
    assert manifest["build_flash"]["flash_skipped"] is False


def test_run_build_flash_command_returns_flash_failure_after_successful_build(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    monkeypatch.setattr(experiment_cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    experiment_path = materialize_baseline_case(tmp_path, monkeypatch)

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 7
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    fake_flash_result = FakeFlashResult()

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 7
    assert len(seen_result_dirs) == 2
    assert seen_result_dirs[0] == seen_result_dirs[1]
    assert "Build-flash failed during flash" in output
    assert "Flash log:" in output
    assert manifest["result"] == "build_flash_failed"
    assert manifest["build_flash"]["build_return_code"] == 0
    assert manifest["build_flash"]["flash_return_code"] == 7
    assert manifest["build_flash"]["flash_skipped"] is False
    assert manifest["build_flash"]["failure_stage"] == "flash"


def test_run_build_flash_command_skips_flash_when_build_fails(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    monkeypatch.setattr(experiment_cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    experiment_path = materialize_baseline_case(tmp_path, monkeypatch)

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 9
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def forbidden_execute_flash(**kwargs):
        raise AssertionError("flash must not run after a failed build")

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", forbidden_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 9
    assert "Build-flash failed during build" in output
    assert "Flash step skipped because the build failed." in output
    assert manifest["result"] == "build_flash_failed"
    assert manifest["build_flash"]["build_return_code"] == 9
    assert manifest["build_flash"]["flash_return_code"] is None
    assert manifest["build_flash"]["flash_skipped"] is True
    assert manifest["build_flash"]["failure_stage"] == "build"

def test_run_build_flash_command_captures_uart_after_successful_flash(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    monkeypatch.setattr(experiment_cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    experiment_path = materialize_baseline_case(tmp_path, monkeypatch)

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 0
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    class FakeUartResult:
        return_code = 0
        duration_seconds = 1.25
        log_path = tmp_path / "results" / "run" / "uart.log"

    fake_flash_result = FakeFlashResult()
    fake_uart_result = FakeUartResult()

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    def fake_execute_uart_capture(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["duration_seconds"] == 12
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_uart_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)
    monkeypatch.setattr(experiment_cli, "execute_uart_capture", fake_execute_uart_capture)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=True,
            uart_duration_seconds=12,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(seen_result_dirs) == 3
    assert seen_result_dirs[0] == seen_result_dirs[1] == seen_result_dirs[2]
    assert "UART log:" in output
    assert manifest["result"] == "build_flash_passed"
    assert manifest["build_flash"]["uart_return_code"] == 0
    assert manifest["build_flash"]["uart_log"] == "uart.log"
    assert manifest["build_flash"]["uart_skipped"] is False
    assert manifest["build_flash"]["failure_stage"] == "none"


def _successful_runner_that_writes_artifact(build, artifact_path: Path, calls: list[list[str]]):
    def fake_runner(command: list[str], cwd: Path):
        calls.append(command)
        if command == ["cmake", "--build", "--preset", "Debug"]:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("fresh elf", encoding="utf-8")
        return build.CommandExecution(
            command=command,
            return_code=0,
            stdout="ran command",
            stderr="",
            duration_seconds=0.1,
        )

    return fake_runner


def _create_matching_build_record(
    build,
    *,
    repo_root: Path,
    result_dir: Path,
    build_number: int,
    content: str,
) -> Path:
    source_elf = repo_root / f"source-{build_number}.elf"
    source_elf.write_text(content, encoding="utf-8")
    source_log = result_dir / f"source-{build_number}.log"
    source_log.write_text("original compilation log\n", encoding="utf-8")
    fingerprint = build.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    record_dir, _ = build.write_build_record(
        bundle=sample_bundle(),
        result_dir=result_dir,
        build_number=build_number,
        firmware_elf_path=source_elf,
        firmware_artifact="build/Release/stm32_basic_hal1.elf",
        firmware_artifact_path=str(source_elf),
        firmware_sha256=hashlib.sha256(source_elf.read_bytes()).hexdigest(),
        source={},
        build={
            "return_code": 0,
            "fingerprint": fingerprint.fingerprint,
            "fingerprint_inputs": fingerprint.inputs,
            "fingerprint_file_hashes": fingerprint.file_hashes,
            "fingerprint_algorithm": fingerprint.algorithm,
            "candidate_fingerprint": fingerprint.fingerprint,
            "candidate_fingerprint_algorithm": fingerprint.algorithm,
            "skipped": False,
        },
        source_run_id=f"source-{build_number}",
        build_log_path=source_log,
    )
    return record_dir














def test_run_build_command_applies_artifact_override_for_relocated_provenance(
    tmp_path, monkeypatch
):
    experiment_cli = load_experiment_module()
    original_bundle = {
        "experiment": {
            "id": "baseline_direct_uart",
            "firmware": {
                "mode": "direct_flash",
                "artifact": "build/Release/stm32_basic_hal1.elf",
            },
        },
        "board": {},
        "host": {},
        "boot": {},
    }
    captured = {}

    monkeypatch.setattr(
        experiment_cli, "load_experiment_bundle", lambda _path: original_bundle
    )
    monkeypatch.setattr(
        experiment_cli,
        "create_result_folder",
        lambda bundle, _results_dir: (
            captured.setdefault("bundle", bundle) or tmp_path / "results" / "run",
            {"run_id": "run"},
        ),
    )
    # The lambda above cannot return both values after setdefault cleanly; replace it.
    def fake_create_result_folder(bundle, _results_dir):
        captured["bundle"] = bundle
        result_dir = tmp_path / "results" / "run"
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_dir, {"run_id": "run"}

    monkeypatch.setattr(experiment_cli, "create_result_folder", fake_create_result_folder)
    monkeypatch.setattr(
        experiment_cli, "repo_root_from_experiment_path", lambda _path: tmp_path
    )

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build/Release/stm32_basic_hal1.elf"
        log_path = tmp_path / "results/run/build.log"
        build_skipped = False
        build_skip_reason = None
        build_number = 1
        build_record_dir = tmp_path / "results/builds/1"

    def fake_execute_build(**kwargs):
        captured["execute_bundle"] = kwargs["bundle"]
        assert kwargs["configure_preset"] == "Release"
        assert kwargs["build_preset"] == "Release"
        return FakeBuildResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)

    exit_code = experiment_cli.run_build_command(
        Namespace(
            experiment=Path(".pqc-generated-state/campaigns/baseline/cases/0001_baseline.yaml"),
            results_dir=tmp_path / "results",
            configure_preset="Release",
            build_preset="Release",
            artifact=Path("build/Release/stm32_basic_hal1.elf"),
            force=False,
        )
    )

    assert exit_code == 0
    expected = "build/Release/stm32_basic_hal1.elf"
    assert captured["bundle"]["experiment"]["firmware"]["artifact"] == expected
    assert captured["execute_bundle"]["experiment"]["firmware"]["artifact"] == expected
    assert original_bundle["experiment"]["firmware"]["artifact"] == (
        "build/Release/stm32_basic_hal1.elf"
    )


def test_wifi_header_generation_uses_experiment_values(tmp_path):
    from framework.build import _write_wifi_config_header
    bundle={"experiment":{"network":{"wifi":{"ssid":"hiphopopotamus","psk":"lukeisadog"},"ipv4":{"mode":"dhcp"}}}}
    path = _write_wifi_config_header(bundle, tmp_path, "Debug")
    text = path.read_text(encoding="utf-8")
    assert path.name == "pqc_wifi_config_generated.h"
    assert '#define PQC_WIFI_SSID "hiphopopotamus"' in text
    assert '#define PQC_WIFI_PSK "lukeisadog"' in text




def test_full_baseline_flash_uses_selected_build_result_artifact():
    """The normal run must flash the ELF chosen by build-record reuse."""

    experiment_source = (
        Path(__file__).resolve().parents[2] / "scripts" / "experiment.py"
    ).read_text(encoding="utf-8")

    expected_call_fragment = '''flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=manifest["run_id"],
        source_build_number=getattr(build_result, "build_number", None),
        source_build_manifest_path=getattr(build_result, "build_record_manifest_path", None),
        artifact_path_override=build_result.elf_path,
    )'''
    assert expected_call_fragment in experiment_source


def test_generated_wifi_header_contains_experiment_dns_requirement(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "network": {"wifi": {}, "ipv4": {}},
            "mqtt": {
                "enabled": True,
                "broker": {
                    "host": "pqc-gateway1.pqcnet",
                    "port": 8883,
                    "dns_required": True,
                },
                "topics": {},
                "tls": {},
            },
        }
    }
    header = _write_wifi_config_header(bundle, tmp_path, "Debug").read_text(encoding="utf-8")
    assert '#define PQC_MQTT_BROKER_HOST "pqc-gateway1.pqcnet"' in header
    assert "#define PQC_MQTT_DNS_REQUIRED 1" in header


def test_pqc_hybrid_wifi_header_requires_explicit_supported_server_signature_algorithm(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "mqtt": {
                "enabled": True,
                "tls": {"mode": "pqc_hybrid_tls_server_auth"},
            }
        }
    }

    try:
        _write_wifi_config_header(bundle, tmp_path, "Debug")
    except ValueError as error:
        assert "missing tls.server_signature_algorithm" in str(error)
    else:
        raise AssertionError("missing PQC server signature algorithm was accepted")


def test_pqc_hybrid_wifi_header_rejects_falcon_leaf_profile(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "mqtt": {
                "enabled": True,
                "tls": {
                    "mode": "pqc_hybrid_tls_server_auth",
                    "server_signature_algorithm": "falcon512",
                },
            }
        }
    }

    try:
        _write_wifi_config_header(bundle, tmp_path, "Debug")
    except ValueError as error:
        assert "falcon512 is incompatible" in str(error)
        assert "classical" in str(error)
    else:
        raise AssertionError("incompatible Falcon server signature algorithm was accepted")


def test_pqc_hybrid_wifi_header_accepts_canonical_rsa_pss_signature_algorithm(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "mqtt": {
                "enabled": True,
                "tls": {
                    "mode": "pqc_hybrid_tls_server_auth",
                    "server_signature_algorithm": "rsa_pss_rsae_sha256",
                },
            }
        }
    }

    path = _write_wifi_config_header(bundle, tmp_path, "Debug")
    text = path.read_text(encoding="utf-8")
    assert '#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM "rsa_pss_rsae_sha256"' in text


def test_pqc_standalone_wifi_header_accepts_canonical_rsa_pss_signature_algorithm(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "mqtt": {
                "enabled": True,
                "tls": {
                    "mode": "pqc_tls_server_auth",
                    "server_signature_algorithm": "rsa_pss_rsae_sha256",
                },
            }
        }
    }

    path = _write_wifi_config_header(bundle, tmp_path, "Debug")
    text = path.read_text(encoding="utf-8")
    assert '#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM "rsa_pss_rsae_sha256"' in text


def test_pqc_hybrid_wifi_header_records_ca_hash_and_signature_algorithm(tmp_path):
    from framework.build import _write_wifi_config_header

    ca_path = tmp_path / "runtime" / "ca.crt"
    ca_path.parent.mkdir(parents=True)
    ca_pem = "-----BEGIN CERTIFICATE-----\ntest-public-ca\n-----END CERTIFICATE-----\n"
    ca_path.write_text(ca_pem, encoding="utf-8")
    bundle = {
        "experiment": {
            "mqtt": {
                "enabled": True,
                "tls": {
                    "mode": "pqc_hybrid_tls_server_auth",
                    "server_signature_algorithm": "classical",
                    "certificate_refs": {"ca_certificate": "runtime/ca.crt"},
                },
            }
        }
    }

    path = _write_wifi_config_header(bundle, tmp_path, "Debug")
    text = path.read_text(encoding="utf-8")
    expected_hash = hashlib.sha256(ca_pem.encode("utf-8")).hexdigest()
    assert f'#define PQC_MQTT_TLS_CA_PEM_SHA256 "{expected_hash}"' in text
    assert '#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM "classical"' in text



def test_execute_build_always_invokes_configure_and_build(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = repo_root / "results" / "run-1"
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.elf"
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[:2] == ["cmake", "--build"]:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"firmware")
        return build.CommandExecution(command, 0, "ok", "", 0.01)

    result = build.execute_build(sample_bundle(), repo_root, result_dir, runner=runner)
    assert result.return_code == 0
    assert calls == [["cmake", "--preset", "Release"], ["cmake", "--build", "--preset", "Release"]]
    assert result.build_skipped is False
    assert result.build_fingerprint is None
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["build"]["reuse_enabled"] is False
    assert manifest["build"]["artifact_identity"] == manifest["firmware"]["sha256"]
    generated_state = json.loads(
        (repo_root / ".pqc-generated-state" / "scopes" / "cmake-Release.json").read_text(
            encoding="utf-8"
        )
    )
    assert generated_state["status"] == "success"
    assert generated_state["scope"] == "cmake-Release"
    assert generated_state["artifacts"][0]["path"] == "build/Release/stm32_basic_hal1.elf"
    assert generated_state["artifacts"][0]["sha256"] == manifest["firmware"]["sha256"]
    assert generated_state["identity"]["input_fingerprint"]["status"] == "disabled"


def test_failed_build_output_is_surfaced_in_ci_console():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "def _print_build_failure_diagnostics(" in source
    assert "Failed {stage} diagnostics" in source
    assert "lines[-max_lines:]" in source
    assert source.count("_print_build_failure_diagnostics(build_result)") >= 2


def test_write_application_selection_uses_profile_application(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["application"] = "mqtt_validation"
    path, application = build._write_application_selection(bundle, tmp_path, "Release")
    assert application == "mqtt_validation"
    assert path == tmp_path / "build" / "Release" / "pqc_generated" / "pqc_application_selection.cmake"
    assert path.read_text(encoding="utf-8") == (
        'set(PQC_STM32_MQTT_APPLICATION "mqtt_validation")\n'
        'set(PQC_UART_LOG_LEVEL "info")\n'
    )



def test_write_application_selection_uses_profile_uart_log_level(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["uart_log_level"] = "debug"
    path, _ = build._write_application_selection(bundle, tmp_path, "Debug")
    assert 'set(PQC_UART_LOG_LEVEL "debug")' in path.read_text(encoding="utf-8")


def test_write_application_selection_rejects_unknown_uart_log_level(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["uart_log_level"] = "verbose"
    try:
        build._write_application_selection(bundle, tmp_path, "Release")
    except ValueError as exc:
        assert "Unsupported UART log level" in str(exc)
    else:
        raise AssertionError("unknown UART log level should be rejected")



def test_write_application_selection_supports_ready_metrics_2_and_uart_off(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["application"] = "mqtt_ready_metrics_2"
    bundle["experiment"]["firmware"]["uart_log_level"] = "off"
    path, application = build._write_application_selection(bundle, tmp_path, "Release")
    assert application == "mqtt_ready_metrics_2"
    text = path.read_text(encoding="utf-8")
    assert 'set(PQC_STM32_MQTT_APPLICATION "mqtt_ready_metrics_2")' in text
    assert 'set(PQC_UART_LOG_LEVEL "off")' in text

def test_write_application_selection_rejects_unknown_application(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["application"] = "unknown"
    try:
        build._write_application_selection(bundle, tmp_path, "Release")
    except ValueError as exc:
        assert "Unsupported STM32 MQTT application" in str(exc)
    else:
        raise AssertionError("unknown application should be rejected")


def test_write_application_selection_supports_ready_metrics(tmp_path):
    build = load_build_module()
    bundle = sample_bundle()
    bundle["experiment"]["firmware"]["application"] = "mqtt_ready_metrics"
    path, application = build._write_application_selection(bundle, tmp_path, "Release")
    assert application == "mqtt_ready_metrics"
    assert 'set(PQC_STM32_MQTT_APPLICATION "mqtt_ready_metrics")' in path.read_text(encoding="utf-8")


def test_ready_metrics_2_wifi_header_contains_transfer_contract(tmp_path):
    from framework.build import _write_wifi_config_header

    bundle = {
        "experiment": {
            "network": {"wifi": {}, "ipv4": {}},
            "mqtt": {
                "enabled": True,
                "broker": {"host": "broker", "port": 1883, "dns_required": True},
                "topics": {"command": "cmd", "response": "result"},
                "transfer": {
                    "payload_bytes": 204800,
                    "chunk_bytes": 400,
                    "request_topic": "result/transfer/request",
                    "response_topic": "result/transfer/response",
                    "request_payload": "send",
                },
                "tls": {},
            },
        }
    }
    header = _write_wifi_config_header(bundle, tmp_path, "Debug").read_text(encoding="utf-8")
    assert '#define PQC_MQTT_TRANSFER_REQUEST_TOPIC "result/transfer/request"' in header
    assert '#define PQC_MQTT_TRANSFER_RESPONSE_TOPIC "result/transfer/response"' in header
    assert '#define PQC_MQTT_TRANSFER_REQUEST_PAYLOAD "send"' in header
    assert "#define PQC_MQTT_TRANSFER_PAYLOAD_BYTES 204800U" in header
    assert "#define PQC_MQTT_TRANSFER_CHUNK_BYTES 400U" in header
