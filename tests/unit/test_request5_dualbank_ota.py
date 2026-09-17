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


def test_wolfboot_generated_config_uses_hardware_dualbank_layout():
    text = (ROOT / "scripts/experiment.py").read_text()
    for value in ('DUALBANK_SWAP?": "1"', "0x08120000", "0x08020000", "0x000E0000"):
        assert value in text
    target = (ROOT / "configs/targets/stm32l4r5_st67.yaml").read_text()
    assert "DUALBANK_SWAP?: 1" in target
    assert "WOLFBOOT_PARTITION_UPDATE_ADDRESS: '0x08120000'" in target
    assert "WOLFBOOT_PARTITION_SWAP_ADDRESS: '0x0'" in target


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
