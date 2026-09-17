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


def test_request5_firmware_modes_are_resolved_and_build_affecting():
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
