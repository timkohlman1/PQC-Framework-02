from pathlib import Path


def test_ram2_mailbox_reserved_in_both_linker_scripts():
    for name in ("STM32L4R5XX_FLASH.ld", "STM32L4R5XX_FLASH_RELOCATED.ld"):
        text = Path(name).read_text(encoding="utf-8")
        assert "RAM2_BOOT_MAILBOX (xrw) : ORIGIN = 0x10000000, LENGTH = 0x400" in text
        assert "RAM2 (xrw)      : ORIGIN = 0x10000400, LENGTH = 0xFC00" in text


def test_boot_evidence_appended_only_after_workload_and_before_hash():
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    task = main[main.index("void StartNetworkTask(void *argument)\n{"):]
    assert task.index("PQC_MQTT_ApplicationRun(&fixture);") < task.index(
        "PQC_BootEvidenceAppendToResultBuffer(0U);") < task.index(
        "PQC_ResultBufferSha256Hex(result_sha256);")
    assert "mailbox->integrity_cycles" in main
    assert "mailbox->authenticity_cycles" in main
    assert 'PQC_ResultBufferAppendText(iteration, "secure_boot", line)' in main


def test_repeat_publishes_boot_evidence_once_in_first_epoch():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    repeat = source[source.index("int PQC_WolfMQTT_RunTLSHandshakeRepeatApplication("):]
    assert repeat.index("PQC_ResultBufferReset();") < repeat.index("if (iteration == 0U)")
    assert repeat.index("PQC_BootEvidenceAppendToResultBuffer(iteration);") < repeat.index(
        "PQC_ResultBufferSha256Hex(result_sha256);")
    assert "PQC_WolfMQTT_PublishDeferredResults(" in repeat


def test_invalid_mailbox_not_silently_measured():
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "mailbox_status=unavailable reason=invalid_magic_or_version" in main
    assert "mailbox->integrity_cycles != 0U" in main
    assert "mailbox->authenticity_cycles != 0U" in main


def test_production_boot_record_serializer_preserves_cycles_without_uart(tmp_path):
    """Compile the production serialization function against the real bounded buffer."""
    import json
    import shutil
    import subprocess

    import pytest

    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("host C compiler not available")
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    structure = source[
        source.index("typedef struct\n{", source.index("#define PQC_BOOT_TIMING_MAILBOX_VERSION")):
        source.index("static void APP_ConfigureResetOriginHandoff")
    ]
    function = source[
        source.index("void PQC_BootEvidenceAppendToResultBuffer(uint32_t iteration)"):
        source.index("/* USER CODE END 0 */", source.index("void PQC_BootEvidenceAppendToResultBuffer(uint32_t iteration)"))
    ]
    harness = (
        '#include <stdint.h>\n#include <stdio.h>\n#include "pqc_result_buffer.h"\n'
        '#define SECURE_BOOT_APPLICATION 1\n'
        '#define PQC_BOOT_TIMING_MAILBOX_MAGIC 0x50514354UL\n'
        '#define PQC_BOOT_TIMING_MAILBOX_VERSION 7UL\n'
        + structure
        + 'static PQC_BootTimingMailbox test_mailbox;\n'
        + '#define PQC_BOOT_TIMING_MAILBOX_ADDR ((uintptr_t)&test_mailbox)\n'
        + source[source.index("static const char *PQC_BootSignatureAlgorithmName("):source.index("#endif /* SECURE_BOOT_APPLICATION */", source.index("static const char *PQC_BootSignatureAlgorithmName("))]
        + function
        + '''int main(void) {
            test_mailbox.magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
            test_mailbox.version = PQC_BOOT_TIMING_MAILBOX_VERSION;
            test_mailbox.signature_algorithm_id = 12U;
            test_mailbox.integrity_valid = 1U;
            test_mailbox.integrity_cycles = 23752531U;
            test_mailbox.integrity_result = 0;
            test_mailbox.verified_image_digest_valid = 1U;
            test_mailbox.verified_image_part = 0U;
            test_mailbox.verified_image_fw_size = 204800U;
            test_mailbox.selected_image_valid = 1U;
            test_mailbox.selected_image_part = 0U;
            test_mailbox.selected_image_fw_size = 204800U;
            test_mailbox.image_verification_valid = 1U;
            test_mailbox.image_verification_cycles = 35000000U;
            for (unsigned int i = 0U; i < 32U; ++i)
                test_mailbox.verified_image_sha256[i] = (uint8_t)i;
            test_mailbox.sysclk_hz = 80000000U;
            test_mailbox.hclk_hz = 80000000U;
            PQC_ResultBufferReset();
            PQC_BootEvidenceAppendToResultBuffer(0U);
            fwrite(PQC_ResultBufferData(), 1, PQC_ResultBufferSize(), stdout);
            PQC_ResultBufferReset();
            test_mailbox.selected_image_valid = 0U;
            PQC_BootEvidenceAppendToResultBuffer(0U);
            fwrite(PQC_ResultBufferData(), 1, PQC_ResultBufferSize(), stdout);
            PQC_ResultBufferReset();
            test_mailbox.magic = 0U;
            PQC_BootEvidenceAppendToResultBuffer(0U);
            fwrite(PQC_ResultBufferData(), 1, PQC_ResultBufferSize(), stdout);
            return 0;
        }
'''
    )
    harness_path = tmp_path / "serializer.c"
    harness_path.write_text(harness, encoding="utf-8")
    executable = tmp_path / "serializer"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-ICore/Inc", str(harness_path), "Core/Src/pqc_result_buffer.c",
         "-o", str(executable)],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, check=True)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 15
    assert all(record["context"] == "secure_boot" for record in records)
    assert "PQC_SECURE_BOOT_PROFILE" in records[0]["text"]
    assert "signature_algorithm=mldsa87" in records[0]["text"]
    assert "public_key_size_bytes=unavailable" in records[0]["text"]
    assert "verification_type=integrity_sha256 measurement_valid=1 cycles=23752531 result=0" in records[3]["text"]
    assert "hclk_hz=80000000" in records[3]["text"]
    assert "signature_algorithm=mldsa87" in records[3]["text"]
    assert "verification_type=signature_authenticity measurement_valid=0" in records[4]["text"]
    assert "signature_algorithm=mldsa87" in records[3]["text"]
    assert "PQC_SECURE_BOOT_IMAGE" in records[1]["text"]
    assert "image_sha256=000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f" in records[1]["text"]
    assert "packaged_image_sha256=unavailable" in records[1]["text"]
    assert "PQC_SECURE_BOOT_VERIFICATION" in records[2]["text"]
    assert "measurement_valid=1 cycles=35000000" in records[2]["text"]
    assert "PQC_SECURE_BOOT_HANDOFF" in records[5]["text"]
    assert "PQC_SECURE_BOOT_TOTAL" in records[6]["text"]
    assert "image_sha256=unavailable reason=selected_image_not_verified" in records[8]["text"]
    assert "measurement_valid=0" in records[9]["text"]
    assert "verification_type=integrity_sha256 measurement_valid=0" in records[10]["text"]
    assert "mailbox_status=unavailable" in records[14]["text"]


def test_verified_image_identity_captured_after_dwt_end():
    """No new hash computation or flash access is added to the DWT interval."""
    build = Path('scripts/framework/wolfboot_build.py').read_text(encoding='utf-8')
    wrapper = build[build.index('/* PQC_BOOT_INTEGRITY_WRAPPER_V4:'):build.index("\n'''", build.index('/* PQC_BOOT_INTEGRITY_WRAPPER_V4:'))]
    assert wrapper.index('end_cycles =') < wrapper.index('    pqc_boot_timing_integrity_finish(end_cycles')
    assert 'pqc_boot_timing_integrity_finish(end_cycles - start_cycles, ret, img)' in wrapper
    assert 'mailbox->verified_image_sha256[i] = img->sha_hash[i];' in build
    assert 'if ((result == 0) && (img != NULL) && (img->sha_hash != NULL)' in build
    assert 'WOLFBOOT_SHA_DIGEST_SIZE == 32U' in build


def test_v7_selected_image_checkpoint_and_independent_interval():
    build = Path("scripts/framework/wolfboot_build.py").read_text(encoding="utf-8")
    app = Path("Core/Src/main.c").read_text(encoding="utf-8")
    standard = Path("tools/wolfboot/src/update_flash.c").read_text(encoding="utf-8")
    swap = Path("tools/wolfboot/src/update_flash_hwswap.c").read_text(encoding="utf-8")
    assert "PQC_BOOT_TIMING_MAILBOX_VERSION 7UL" in build
    assert "PQC_BOOT_TIMING_MAILBOX_VERSION   7UL" in app
    assert "pqc_boot_timing_image_start(start_cycles, img);" in build
    assert "pqc_boot_timing_image_finish(end_cycles, ret, img);" in build
    assert "cycles = end_cycles - pqc_boot_image_start_cycles;" in build
    assert "mailbox->image_verification_valid = 1U;" in build
    assert "mailbox->selected_image_valid = 1U;" in build
    assert "pqc_boot_timing_select_image(&boot);" in standard
    assert "pqc_boot_timing_select_image(&fw_image);" in swap
    assert "if (active == PART_BOOT && fw_image.part == PART_BOOT)" in swap
    assert "pqc_boot_timing_select_image(NULL);" in swap
    assert standard.index("pqc_boot_timing_select_image(&boot);") < standard.index("    hal_prepare_boot();")
    assert swap.index("pqc_boot_timing_select_image(&fw_image);") < swap.index("    hal_prepare_boot();")
    assert "PQC_SECURE_BOOT_VERIFICATION" in app
    assert "PQC_SECURE_BOOT_TOTAL" in app
    assert "(mailbox->selected_image_valid == 1U)" in app
