from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_result_buffer_is_explicitly_in_ram3():
    src = (ROOT / "Core/Src/pqc_result_buffer.c").read_text()
    assert 'section(".pqc_result_buffer")' in src
    for linker in ("STM32L4R5XX_FLASH.ld", "STM32L4R5XX_FLASH_RELOCATED.ld"):
        text = (ROOT / linker).read_text()
        section = text[text.index(".pqc_result_buffer"):text.index(".pqc_mldsa_workspace")]
        assert ".pqc_result_buffer (NOLOAD)" in section
        assert "} >RAM3" in section
        assert "__pqc_result_buffer_size__" in section


def test_dualbank_firmware_modes_are_resolved_and_build_affecting():
    resolver = (ROOT / "scripts/framework/config_resolver.py").read_text()
    assert 'FIRMWARE_MODES = {"single_bank", "dual_bank_no_ota", "dual_bank_ota"}' in resolver
    assert '"firmware_mode": firmware_mode' in resolver
    assert '"standby_signing_keys": standby_signing_keys' in resolver
    build = (ROOT / "scripts/framework/build.py").read_text()
    assert 'set(PQC_FIRMWARE_MODE' in build
    assert 'set(PQC_DUAL_BANK_ENABLED' in build
    assert 'set(PQC_OTA_ENABLED' in build


def test_wolfboot_config_selects_legacy_or_hardware_dualbank_layout():
    text = (ROOT / "scripts/experiment.py").read_text()
    assert 'firmware_mode == "single_bank"' in text
    assert '"DUALBANK_SWAP?": "0"' in text
    assert '"WOLFBOOT_PARTITION_UPDATE_ADDRESS": "0x08100000"' in text
    assert '"WOLFBOOT_PARTITION_SWAP_ADDRESS": "0x081E0000"' in text
    assert '"DUALBANK_SWAP?": "1"' in text
    assert '"WOLFBOOT_PARTITION_UPDATE_ADDRESS": "0x08120000"' in text
    assert '"WOLFBOOT_PARTITION_SWAP_ADDRESS": "0x0"' in text


def test_ota_code_is_compile_time_guarded():
    cmake = (ROOT / "CMakeLists.txt").read_text()
    firmware = (ROOT / "Core/Src/pqc_wolfmqtt_build_only.c").read_text()
    assert 'PQC_OTA_ENABLED=${PQC_OTA_ENABLED}' in cmake
    assert '#if PQC_OTA_ENABLED' in firmware
    assert 'PQC_WolfMQTT_ProcessRetainedOta' in firmware


def test_zero_standby_keys_compile_out_keyslot_iteration():
    image = (ROOT / "tools/wolfboot/src/image.c").read_text()
    assert '#if PQC_WOLFBOOT_STANDBY_KEYS == 0' in image
    single = image[image.index('#if PQC_WOLFBOOT_STANDBY_KEYS == 0'):image.index('#else', image.index('#if PQC_WOLFBOOT_STANDBY_KEYS == 0'))]
    assert 'for (' not in single
    assert 'key_hash(0, digest)' in single


def test_multi_key_tuple_supports_one_or_two_standby_keys():
    wb = (ROOT / "scripts/framework/wolfboot_build.py").read_text()
    exp = (ROOT / "scripts/experiment.py").read_text()
    assert '_create_multi_key_persistent_tuple' in wb
    assert 'standby_private_key_sha256' in wb
    assert 'standby_signing_keys not in {0, 1, 2}' in exp
    assert 'standby_private_keys' in exp


def test_stm32l4_hal_has_bfb2_swap_and_mapping_evidence():
    text = (ROOT / "tools/wolfboot/hal/stm32l4.c").read_text()
    assert "OB_USER_BFB2" in text and "HAL_FLASH_OB_Launch" in text
    assert "hal_flash_dualbank_active_physical_bank" in text
    assert "hal_get_primary_address" in text and "hal_get_update_address" in text


def test_hwswap_requires_authenticated_candidate_bank_manifest_and_confirmation():
    text = (ROOT / "tools/wolfboot/src/update_flash_hwswap.c").read_text()
    assert "pqc_verify_candidate_bank_manifest" in text
    assert "wolfBoot_verify_authenticity(&manifest_image)" in text
    assert "PQC_OTA_FLAG_BOOTLOADER_MIGRATION" in text
    assert "Candidate-bank manifest authentication failed" in text
    assert "PQC_OTA_MARKER_STAGED" in text
    assert "PQC_OTA_MARKER_BOOTED" in text
    assert "PQC_OTA_MARKER_CONFIRMED" in text
    assert "Unconfirmed candidate bank: restoring previous physical bank" in text


def test_firmware_confirmation_occurs_only_after_deferred_reporting_path():
    text = (ROOT / "Core/Src/pqc_wolfmqtt_build_only.c").read_text()
    publish = text.index("int PQC_WolfMQTT_PublishDeferredResults")
    confirm = text.index("PQC_OTA_ConfirmActiveCandidateIfPending", publish)
    assert confirm > publish
    assert "candidate application confirmed; reset to commit" in text


def test_secure_boot_hardware_test_uses_normal_provenance_for_destructive_subprocesses():
    text = (ROOT / "tests/hardware/test_secure_boot_flash_workflow_hw.py").read_text()
    assert 'env["PQC_BUILD_PURPOSE"] = "experiment"' in text
    assert 'env.pop("PQC_TEST_RESULT_DIR", None)' in text


def test_negative_plan_and_unconfirmed_rollback_hooks_exist():
    ota=(ROOT / "scripts/framework/ota.py").read_text()
    exp=(ROOT / "scripts/experiment.py").read_text()
    fw=(ROOT / "Core/Src/pqc_wolfmqtt_build_only.c").read_text()
    assert "make_fault_plan" in ota
    assert "invalid-manifest" in ota and "corrupt-application" in ota and "interrupted" in ota
    assert "--test-no-confirm" in exp
    assert "intentionally left unconfirmed" in fw


def test_status_uses_effective_secure_boot_bundle():
    text = (ROOT / "scripts/experiment.py").read_text()
    start = text.index("def run_status_command")
    end = text.index("def run_create_run_command", start)
    block = text[start:end]
    assert "_resolved_case_secure_boot_choice(args.experiment)" in block
    assert "load_secure_boot_experiment_bundle" in block
    assert "load_experiment_bundle(args.experiment)" in block


def test_signed_application_uses_distinct_immutable_evidence_role(tmp_path):
    import sys

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from framework.manifest import _sync_legacy_evidence

    unsigned = tmp_path / "application.bin"
    signed = tmp_path / "application_signed.bin"
    unsigned.write_bytes(b"unsigned-dualbank-image")
    signed.write_bytes(b"signed-dualbank-image")

    manifest = {}
    manifest_path = tmp_path / "manifest.json"

    _sync_legacy_evidence(
        manifest_path,
        manifest,
        {"firmware": {"result_artifact_path": str(unsigned)}},
    )
    _sync_legacy_evidence(
        manifest_path,
        manifest,
        {
            "firmware": {
                "result_artifact_path": str(signed),
                "evidence_role": "signed_application",
            }
        },
    )

    artifacts = {item["role"]: item for item in manifest["artifacts"]}
    assert artifacts["application_binary"]["sha256"] != artifacts["signed_application"]["sha256"]
    assert artifacts["application_binary"]["path"] == "application.bin"
    assert artifacts["signed_application"]["path"] == "application_signed.bin"


def test_wolfboot_build_materializes_and_retains_raw_binary():
    text = (ROOT / "scripts/framework/wolfboot_build.py").read_text()
    assert '"arm-none-eabi-objcopy"' in text
    assert 'binary_artifact_path = artifact_path.with_suffix(".bin")' in text
    assert '"wolfboot.bin"' in text
    assert '"retained_binary_path"' in text
    assert 'state_artifacts.append(binary_artifact_path)' in text


def test_application_build_materializes_raw_binary_before_result_copy():
    text = (ROOT / "scripts/framework/build.py").read_text()
    assert 'construct_binary_command' in text
    assert '"arm-none-eabi-objcopy"' in text
    assert 'binary_path = elf_path.with_suffix(".bin")' in text
    assert 'copy_firmware_artifacts_to_result(elf_path, result_dir_path)' in text
    assert 'ARTIFACT_CONVERSION_RETURN_CODE' in text


def test_dev_wrapper_forwards_dualbank_ota_hardware_environment():
    text = (ROOT / "scripts/dev.sh").read_text()
    for name in (
        "PQC_OTA_HW",
        "PQC_OTA_HW_CASE",
        "PQC_OTA_HW_APP_PLAN",
        "PQC_OTA_HW_ROLLBACK_PLAN",
        "PQC_OTA_HW_MIGRATION_PLAN",
        "PQC_OTA_HW_INTERRUPTED_PLAN",
        "PQC_OTA_HW_CORRUPT_APP_PLAN",
        "PQC_OTA_HW_INVALID_MANIFEST_PLAN",
    ):
        assert name in text
    assert 'ota_env_args="$ota_env_args -e $ota_env_name"' in text
    assert '$campaign_env_args $ota_env_args' in text


def test_dualbank_run_provenance_retains_ota_record(tmp_path):
    import importlib.util

    module_path = ROOT / "scripts" / "framework" / "run_evidence.py"
    spec = importlib.util.spec_from_file_location("dualbank_run_evidence", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    manifest = {
        "source": {"commit": "deadbeef"},
        "ota": {
            "requested": True,
            "transport": "reporting_mqtt_plaintext",
            "impairment_exempt": True,
            "delivery": {"return_code": 0},
        },
    }
    snapshot = module.build_run_provenance_snapshot(manifest)
    assert snapshot["records"]["ota"] == manifest["ota"]


def test_dualbank_structured_uart_state_markers_and_explicit_hw_assertions_exist():
    firmware = (ROOT / "Core/Src/pqc_wolfmqtt_build_only.c").read_text()
    hardware = (ROOT / "tests/hardware/test_ota_dualbank_hw.py").read_text()
    experiment = (ROOT / "scripts/experiment.py").read_text()
    for phase in (
        "request_accepted",
        "transfer_complete",
        "hashes_verified",
        "activation_reset",
        "boot_state",
        "confirmed",
        "confirmation_withheld",
    ):
        assert f'phase={phase}' in firmware or f'PQC_OTA_LogApplicationState("{phase}")' in firmware
    assert "test_application_update_explicit_bank_boot_and_confirmation_state_hw" in hardware
    assert "test_unconfirmed_update_explicitly_returns_to_original_physical_bank_hw" in hardware
    assert 'record.get("active_bank") != initial_bank' in hardware
    assert 'candidate_app.get("bfb2") != initial_bfb2' in hardware
    assert 'record.get("phase") == "confirmed"' in hardware
    assert 'record.get("active_bank") == original_bank' in hardware
    assert "wolfBoot verification result: 0" in hardware
    assert "===== Dual-bank OTA UART:" in hardware
    assert 'ota_wait_mode = "rollback" if ota_plan_payload.get("test_no_confirm") else "confirmed"' in experiment
    assert 'termination_reason=ota_terminal' in experiment
    assert 'PQC_OTA_APP phase=confirmed ' in experiment
    assert 'PQC_OTA_APP phase=confirmation_withheld ' in experiment

