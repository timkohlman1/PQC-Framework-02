from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from argparse import Namespace
from pathlib import Path


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_sample_configs(configs_root: Path) -> Path:
    repo_root = configs_root.parent
    source_repo = Path(__file__).resolve().parents[2]
    shutil.copytree(source_repo / "configs", configs_root, dirs_exist_ok=True)
    os.environ.setdefault("PQC_WIFI_SSID", "pqc")
    os.environ.setdefault("PQC_WIFI_PSK", "test-psk")
    scripts_path = source_repo / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    from framework.config_resolver import ConfigResolver
    generated = ConfigResolver(repo_root).materialize_campaign(
        "baseline", repo_root / ".pqc-generated-state" / "campaigns" / "baseline"
    )
    return sorted((generated / "cases").glob("*.yaml"))[0]


def args_for(experiment_path: Path, results_dir: Path) -> Namespace:
    return Namespace(
        experiment=experiment_path,
        results_dir=results_dir,
        configure_preset=None,
        build_preset="Debug",
        uart_duration_seconds=10,
        boot_mode="direct_flash",
        boot_algorithm=None,
        target_profile=Path("configs/targets/stm32l4r5_wolfboot.yaml"),
        firmware_mode="single_bank",
        standby_signing_keys=0,
        ota_plan=None,
        build_number=None,
        force=False,
    )


def test_run_command_success_orchestrates_all_stages_in_one_result_directory(
    tmp_path, monkeypatch, capsys
):
    cli = load_experiment_module()
    monkeypatch.setattr(cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    monkeypatch.setattr(cli, "_is_st67_mqtt_e2e", lambda bundle: False)
    monkeypatch.setattr(
        cli,
        "_execute_uart_capture_with_optional_gateway_packet_capture",
        lambda **kwargs: (
            (r := cli.execute_uart_capture(**{k: v for k, v in kwargs.items() if k in {"bundle", "repo_root", "result_dir", "duration_seconds", "restart_command"}})),
            r.return_code,
            None if r.return_code == 0 else "uart",
        ),
    )
    experiment_path = write_sample_configs(tmp_path / "configs")
    results_dir = tmp_path / "results"
    seen_result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 0
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    class UartResult:
        return_code = 0
        duration_seconds = 0.3
        log_path = tmp_path / "results" / "run" / "uart.log"

    def fake_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    def fake_copy(artifact_path, result_dir):
        assert artifact_path == BuildResult.elf_path
        seen_result_dirs.append(result_dir)
        copied = result_dir / BuildResult.elf_path.name
        copied.write_bytes(b"elf")
        return copied

    def fake_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        assert kwargs["source_build_run_id"] == kwargs["result_dir"].name
        return FlashResult()

    def fake_uart(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        assert kwargs["restart_command"] == "reset-stm32a"
        return UartResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", fake_copy)
    monkeypatch.setattr(cli, "execute_flash", fake_flash)
    monkeypatch.setattr(cli, "execute_uart_capture", fake_uart)

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, results_dir))

    assert exit_code == 0
    assert len(seen_result_dirs) == 4
    assert all(path == seen_result_dirs[0] for path in seen_result_dirs)
    manifest = json.loads((seen_result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_outcome"] == {
        "status": "completed",
        "result": "baseline_run_passed",
        "failure_stage": None,
    }
    assert "result" not in manifest
    assert manifest["run"]["failure_stage"] is None
    assert "firmware" not in manifest
    assert "Baseline run passed" in capsys.readouterr().out


def test_run_command_stops_after_build_failure(tmp_path, monkeypatch):
    cli = load_experiment_module()
    monkeypatch.setattr(cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    monkeypatch.setattr(cli, "_is_st67_mqtt_e2e", lambda bundle: False)
    monkeypatch.setattr(
        cli,
        "_execute_uart_capture_with_optional_gateway_packet_capture",
        lambda **kwargs: (
            (r := cli.execute_uart_capture(**{k: v for k, v in kwargs.items() if k in {"bundle", "repo_root", "result_dir", "duration_seconds", "restart_command"}})),
            r.return_code,
            None if r.return_code == 0 else "uart",
        ),
    )
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 4
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("copy must not run")))
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: (_ for _ in ()).throw(AssertionError("flash must not run")))
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: (_ for _ in ()).throw(AssertionError("uart must not run")))

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 4
    assert manifest["execution_outcome"] == {
        "status": "not_executed",
        "result": "baseline_run_failed",
        "failure_stage": "build",
    }
    assert "result" not in manifest
    assert manifest["run"]["failure_stage"] == "build"
    assert "flash_return_code" not in manifest["run"]
    assert "uart_return_code" not in manifest["run"]


def test_run_command_stops_after_flash_failure_and_marks_uart_skipped(tmp_path, monkeypatch):
    cli = load_experiment_module()
    monkeypatch.setattr(cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    monkeypatch.setattr(cli, "_is_st67_mqtt_e2e", lambda bundle: False)
    monkeypatch.setattr(
        cli,
        "_execute_uart_capture_with_optional_gateway_packet_capture",
        lambda **kwargs: (
            (r := cli.execute_uart_capture(**{k: v for k, v in kwargs.items() if k in {"bundle", "repo_root", "result_dir", "duration_seconds", "restart_command"}})),
            r.return_code,
            None if r.return_code == 0 else "uart",
        ),
    )
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 7
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda artifact_path, result_dir: result_dir / "stm32_basic_hal1.elf")
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: FlashResult())
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: (_ for _ in ()).throw(AssertionError("uart must not run")))

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 7
    assert manifest["execution_outcome"] == {
        "status": "not_executed",
        "result": "baseline_run_failed",
        "failure_stage": "flash",
    }
    assert "result" not in manifest
    assert manifest["run"]["failure_stage"] == "flash"
    assert "uart_return_code" not in manifest["run"]
    assert "uart" not in manifest


def test_run_command_returns_uart_marker_failure(tmp_path, monkeypatch):
    cli = load_experiment_module()
    monkeypatch.setattr(cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    monkeypatch.setattr(cli, "_is_st67_mqtt_e2e", lambda bundle: False)
    monkeypatch.setattr(
        cli,
        "_execute_uart_capture_with_optional_gateway_packet_capture",
        lambda **kwargs: (
            (r := cli.execute_uart_capture(**{k: v for k, v in kwargs.items() if k in {"bundle", "repo_root", "result_dir", "duration_seconds", "restart_command"}})),
            r.return_code,
            None if r.return_code == 0 else "uart",
        ),
    )
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 0
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    class UartResult:
        return_code = 9
        duration_seconds = 0.3
        log_path = tmp_path / "results" / "run" / "uart.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda artifact_path, result_dir: result_dir / "stm32_basic_hal1.elf")
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: FlashResult())
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: UartResult())

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 9
    assert manifest["execution_outcome"] == {
        "status": "failed",
        "result": "baseline_run_failed",
        "failure_stage": "uart",
    }
    assert "result" not in manifest
    assert manifest["run"]["failure_stage"] == "uart"
    assert "uart_return_code" not in manifest["run"]


def test_run_subcommand_is_registered_with_mandatory_uart_capture():
    cli = load_experiment_module()
    parser = cli.build_arg_parser()
    args = parser.parse_args(
        [
            "run",
            "--experiment",
            ".pqc-generated-state/campaigns/baseline/cases/case.yaml",
        ]
    )

    assert args.func is cli.run_full_baseline_command
    assert args.build_preset == "Release"
    assert args.configure_preset is None
    assert args.uart_duration_seconds == cli.DEFAULT_CAPTURE_DURATION_SECONDS
    assert args.boot_mode is None
    assert args.boot_algorithm is None
    assert not hasattr(args, "capture_uart")


def test_wolfboot_run_forwards_debug_build_presets(tmp_path, monkeypatch):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = "wolfboot"
    args.boot_algorithm = "ecdsa_p256"
    args.configure_preset = None
    args.build_preset = "Debug"
    observed = {}
    result_dir = tmp_path / "results" / "run"
    result_dir.mkdir(parents=True)

    class WolfbootResult:
        return_code = 0
        result_dir = tmp_path / "results" / "wolfboot"
        log_path = result_dir / "wolfboot.log"
        artifact_path = tmp_path / "tools" / "wolfboot" / "wolfboot.elf"
        artifact_sha256 = "wolfboot-sha256"

    class BuildResult:
        return_code = 1
        build_number = None
        firmware_sha256 = None
        build_record_manifest_path = None

    def fake_execute_build(**kwargs):
        observed["configure_preset"] = kwargs["configure_preset"]
        observed["build_preset"] = kwargs["build_preset"]
        return BuildResult()

    monkeypatch.setattr(cli, "repo_root_from_experiment_path", lambda path: tmp_path)
    monkeypatch.setattr(cli, "_compose_wolfboot_run_bundle", lambda **kwargs: {
        "experiment": {"firmware": {"artifact": "build/Release/stm32_basic_hal1_v1_signed.bin"}},
        "board": {},
        "host": {},
        "boot": {},
    })
    monkeypatch.setattr(cli, "create_result_folder", lambda bundle, results, **kwargs: (result_dir, {"run_id": "run"}))
    monkeypatch.setattr(cli, "finalize_run_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_report_experiment_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "update_manifest", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "emit_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_prepare_dependencies_for_result", lambda **kwargs: kwargs["bundle"])
    monkeypatch.setattr(cli, "load_secure_boot_profile_section", lambda **kwargs: (
        {"input_image": "build/Release/stm32_basic_hal1.bin",
         "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin"}
        if kwargs["section"] == "signing" else {},
        None,
    ))
    monkeypatch.setattr(cli, "validate_wolfboot_build_profile_config", lambda profile: None)
    monkeypatch.setattr(cli, "validate_application_signing_profile_config", lambda profile: None)
    monkeypatch.setattr(cli, "execute_wolfboot_build", lambda **kwargs: WolfbootResult())
    monkeypatch.setattr(cli, "_record_wolfboot_run_stage", lambda **kwargs: None)
    monkeypatch.setattr(cli, "_record_run_summary", lambda **kwargs: None)
    monkeypatch.setattr(cli, "execute_build", fake_execute_build)

    assert cli._run_full_wolfboot_command(args) == 1
    assert observed == {
        "configure_preset": "Debug",
        "build_preset": "Debug",
    }


def test_run_subcommand_accepts_explicit_wolfboot_selection():
    cli = load_experiment_module()
    parser = cli.build_arg_parser()
    args = parser.parse_args(
        [
            "run",
            "--experiment",
            ".pqc-generated-state/campaigns/tls_key_exchange/cases/case.yaml",
            "--boot-mode",
            "wolfboot",
            "--boot-algorithm",
            "ecdsa_p256",
        ]
    )

    assert args.func is cli.run_full_baseline_command
    assert args.boot_mode == "wolfboot"
    assert args.boot_algorithm == "ecdsa_p256"
    assert args.target_profile == Path("configs/targets/stm32l4r5_wolfboot.yaml")


def test_run_rejects_boot_algorithm_for_direct_flash(tmp_path, capsys):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = "direct_flash"
    args.boot_algorithm = "ecdsa_p256"

    assert cli.run_full_baseline_command(args) == 2
    assert "cannot be combined with --boot-mode direct_flash" in capsys.readouterr().err




def test_run_defaults_to_integrity_wolfboot(monkeypatch, tmp_path):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = None
    args.boot_algorithm = None
    observed = {}

    def fake_wolfboot(run_args):
        observed["mode"] = run_args.boot_mode
        observed["algorithm"] = run_args.boot_algorithm
        return 0

    monkeypatch.setattr(cli, "_run_full_wolfboot_command", fake_wolfboot)
    assert cli.run_full_baseline_command(args) == 0
    assert observed == {"mode": "wolfboot", "algorithm": "integrity_sha256"}


def test_run_uses_canonical_resolved_case_secure_boot_selection(monkeypatch, tmp_path):
    cli = load_experiment_module()
    experiment_path = tmp_path / "0002_secure_boot.yaml"
    experiment_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "kind: resolved_case",
                "id: secure_boot-0002-test",
                "choices:",
                "  secure_boot: ecdsa_p256",
                "",
            ]
        ),
        encoding="utf-8",
    )
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = None
    args.boot_algorithm = None
    observed = {}

    def fake_wolfboot(run_args):
        observed["mode"] = run_args.boot_mode
        observed["algorithm"] = run_args.boot_algorithm
        return 0

    monkeypatch.setattr(cli, "_run_full_wolfboot_command", fake_wolfboot)
    assert cli.run_full_baseline_command(args) == 0
    assert observed == {"mode": "wolfboot", "algorithm": "ecdsa_p256"}


def test_explicit_boot_algorithm_overrides_canonical_resolved_case(monkeypatch, tmp_path):
    cli = load_experiment_module()
    experiment_path = tmp_path / "0011_secure_boot.yaml"
    experiment_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "kind: resolved_case",
                "id: secure_boot-0011-test",
                "choices:",
                "  secure_boot: mldsa65",
                "",
            ]
        ),
        encoding="utf-8",
    )
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = None
    args.boot_algorithm = "rsa3072"
    observed = {}

    def fake_wolfboot(run_args):
        observed["mode"] = run_args.boot_mode
        observed["algorithm"] = run_args.boot_algorithm
        return 0

    monkeypatch.setattr(cli, "_run_full_wolfboot_command", fake_wolfboot)
    assert cli.run_full_baseline_command(args) == 0
    assert observed == {"mode": "wolfboot", "algorithm": "rsa3072"}


def test_run_algorithm_implies_wolfboot(monkeypatch, tmp_path):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = None
    args.boot_algorithm = "mldsa87"
    observed = {}

    def fake_wolfboot(run_args):
        observed["mode"] = run_args.boot_mode
        observed["algorithm"] = run_args.boot_algorithm
        return 0

    monkeypatch.setattr(cli, "_run_full_wolfboot_command", fake_wolfboot)
    assert cli.run_full_baseline_command(args) == 0
    assert observed == {"mode": "wolfboot", "algorithm": "mldsa87"}

def test_record_run_summary_preserves_signed_firmware_hash(tmp_path):
    cli = load_experiment_module()
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    signed_hash = "51cfe24582e70d204c737d8a75edf1f3d01a283703e3e69fff09fae52cadbbba"
    build_hash = "77deb8bc6aa276457ed4415fa78bb652bb587b798b6ecb1dc7f76f4efe610014"
    retained_artifact = result_dir / "application_signed.bin"
    retained_artifact.write_bytes(b"signed application")
    (result_dir / "manifest.json").write_text(
        json.dumps(
            {
                "firmware": {
                    "artifact": "build/Release/stm32_basic_hal1_v1_signed.bin",
                    "artifact_path": "/workspace/build/Release/stm32_basic_hal1_v1_signed.bin",
                    "sha256": signed_hash,
                }
            }
        ),
        encoding="utf-8",
    )

    cli._record_run_summary(
        result_dir=result_dir,
        final_return_code=0,
        failure_stage="none",
        build_return_code=0,
        flash_return_code=0,
        uart_return_code=0,
        artifact_copy_return_code=0,
        copied_artifact_path=retained_artifact,
        duration_seconds=1.0,
        referenced_build_number=106,
        referenced_build_artifact_sha256=build_hash,
        referenced_build_manifest=tmp_path / "build-manifest.json",
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["firmware"]["sha256"] == signed_hash
    assert manifest["build_reference"]["artifact_sha256"] == build_hash
    assert manifest["run"]["referenced_build_artifact_sha256"] == build_hash


def test_record_run_summary_uses_build_hash_when_firmware_hash_is_missing(tmp_path):
    cli = load_experiment_module()
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    build_hash = "77deb8bc6aa276457ed4415fa78bb652bb587b798b6ecb1dc7f76f4efe610014"
    (result_dir / "manifest.json").write_text(
        json.dumps({"firmware": {"artifact": "build/Release/firmware.elf"}}),
        encoding="utf-8",
    )

    cli._record_run_summary(
        result_dir=result_dir,
        final_return_code=0,
        failure_stage="none",
        build_return_code=0,
        flash_return_code=0,
        uart_return_code=0,
        artifact_copy_return_code=0,
        copied_artifact_path=None,
        duration_seconds=1.0,
        referenced_build_artifact_sha256=build_hash,
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["firmware"]["sha256"] == build_hash

def test_wolfboot_signing_paths_follow_selected_debug_preset():
    cli = load_experiment_module()
    profile = {
        "input_elf": "build/Release/stm32_basic_hal1.elf",
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
        "private_key": "secrets/wolfboot/private_key.der",
    }

    selected = cli._retarget_signing_profile_build_preset(profile, "Debug")

    assert selected["input_elf"] == "build/Debug/stm32_basic_hal1.elf"
    assert selected["input_image"] == "build/Debug/stm32_basic_hal1.bin"
    assert selected["signed_image"] == "build/Debug/stm32_basic_hal1_v1_signed.bin"
    assert selected["build_preset"] == "Debug"
    assert selected["private_key"] == "secrets/wolfboot/private_key.der"
    assert profile["input_elf"] == "build/Release/stm32_basic_hal1.elf"


def test_wolfboot_application_build_uses_relocated_elf_before_signing():
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "firmware": {
                "mode": "wolfboot_ecdsa_p256",
                "artifact": "build/Release/stm32_basic_hal1_v1_signed.bin",
            }
        },
        "board": {},
        "host": {},
        "boot": {},
    }
    signing_profile = {
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
    }

    build_bundle = cli._wolfboot_application_build_bundle(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    assert build_bundle["experiment"]["firmware"]["artifact"] == (
        "build/Release/stm32_basic_hal1.elf"
    )
    assert bundle["experiment"]["firmware"]["artifact"] == (
        "build/Release/stm32_basic_hal1_v1_signed.bin"
    )
    assert "secure_boot_flash" not in bundle["experiment"]


def test_wolfboot_application_build_prefers_configured_input_elf_for_algorithm_specific_bin():
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "firmware": {
                "mode": "wolfboot_mldsa65",
                "artifact": "build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin",
            }
        },
        "board": {},
        "host": {},
        "boot": {},
    }
    signing_profile = {
        "input_elf": "build/Release/stm32_basic_hal1.elf",
        "input_image": "build/Release/stm32_basic_hal1_mldsa65.bin",
        "signed_image": "build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin",
    }

    build_bundle = cli._wolfboot_application_build_bundle(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    assert build_bundle["experiment"]["firmware"]["artifact"] == (
        "build/Release/stm32_basic_hal1.elf"
    )
    assert bundle["experiment"]["firmware"]["artifact"] == (
        "build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin"
    )


def test_wolfboot_signed_firmware_is_selected_only_after_signing():
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "firmware": {
                "mode": "wolfboot_ecdsa_p256",
                "artifact": "build/Release/stm32_basic_hal1.elf",
            },
            "secure_boot_flash": {
                "unsigned_application_artifact": "build/Release/stm32_basic_hal1.bin",
                "signed_application_artifact": "build/Release/stm32_basic_hal1_v1_signed.bin",
            },
        }
    }
    signing_profile = {
        "input_image": "build/Debug/stm32_basic_hal1.bin",
        "signed_image": "build/Debug/stm32_basic_hal1_v1_signed.bin",
    }

    cli._select_signed_firmware_artifact(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    assert bundle["experiment"]["firmware"]["artifact"] == (
        "build/Debug/stm32_basic_hal1_v1_signed.bin"
    )
    assert bundle["experiment"]["secure_boot_flash"]["unsigned_application_artifact"] == (
        "build/Debug/stm32_basic_hal1.bin"
    )
    assert bundle["experiment"]["secure_boot_flash"]["signed_application_artifact"] == (
        "build/Debug/stm32_basic_hal1_v1_signed.bin"
    )


def test_integrity_signing_profile_does_not_require_signing_tuple(tmp_path, monkeypatch):
    cli = load_experiment_module()
    profile = {
        "id": "wolfboot_integrity_sha256_app",
        "signature_algorithm": "integrity_sha256",
    }

    monkeypatch.setattr(
        cli,
        "resolve_signing_material",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("integrity-only mode must not resolve signing material")),
    )

    prepared = cli._prepare_signing_profile_dependencies(profile=profile, repo_root=tmp_path)

    assert prepared is profile
    assert "private_key" not in prepared
    assert "resolved_signing_context" not in prepared


def test_authenticated_signing_profile_still_requires_resolved_tuple(tmp_path, monkeypatch):
    cli = load_experiment_module()
    profile = {
        "id": "wolfboot_mldsa65_app",
        "signature_algorithm": "mldsa65",
        "private_key": "placeholder.der",
    }
    private_key = tmp_path / "secrets" / "wolfboot" / "tuples" / "mldsa65-development" / "private_key.der"

    class SigningContext:
        def __init__(self):
            self.private_key = private_key

        def public_manifest(self, repo_root):
            return {"tuple_id": "mldsa65-development"}

    observed = {}

    def fake_resolve_signing_material(**kwargs):
        observed.update(kwargs)
        return SigningContext()

    monkeypatch.setattr(cli, "resolve_signing_material", fake_resolve_signing_material)

    prepared = cli._prepare_signing_profile_dependencies(profile=profile, repo_root=tmp_path)

    assert observed == {"profile": profile, "repo_root": tmp_path}
    assert prepared["private_key"] == "secrets/wolfboot/tuples/mldsa65-development/private_key.der"
    assert prepared["resolved_signing_context"] == {"tuple_id": "mldsa65-development"}


def test_crypto_progress_lines_show_auth_profile_and_derived_signature_scheme(monkeypatch):
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "mqtt": {
                "tls": {
                    "mode": "classical_tls_server_auth",
                    "certificate_profile": "rsa3072",
                }
            },
            "resolved_configuration": {
                "choices": {
                    "tls_auth": "rsa3072",
                }
            },
        }
    }

    monkeypatch.setattr(
        cli,
        "resolve_tls_algorithm_set",
        lambda _bundle: {
            "key_exchange_groups": ["secp256r1"],
            "signature_schemes": ["rsa_pss_rsae_sha256"],
        },
    )

    assert cli._crypto_progress_lines(bundle) == [
        "MQTT TLS mode=classical_tls_server_auth; key exchange=secp256r1; "
        "auth profile=rsa3072; signature scheme=rsa_pss_rsae_sha256"
    ]
