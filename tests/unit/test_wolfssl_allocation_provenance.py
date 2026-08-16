from pathlib import Path


def test_wolfssl_diagnostics_are_compile_time_optional_and_off_by_default():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(
        encoding="utf-8"
    )
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "#define XMALLOC_OVERRIDE" in settings
    assert "#ifndef PQC_WOLFSSL_MEMORY_DIAGNOSTICS" in settings
    assert "#define PQC_WOLFSSL_MEMORY_DIAGNOSTICS 0" in settings
    assert "#ifndef PQC_WOLFSSL_ALLOCATION_PROVENANCE" in settings
    assert "#define PQC_WOLFSSL_ALLOCATION_PROVENANCE 0" in settings
    assert "option(PQC_WOLFSSL_MEMORY_DIAGNOSTICS" in cmake
    assert "option(PQC_WOLFSSL_ALLOCATION_PROVENANCE" in cmake
    assert '"Enable wolfSSL heap/failure UART diagnostics (changes timing)" OFF' in cmake
    assert '"Enable wolfSSL allocation source/type UART tracing (changes timing)" OFF' in cmake


def test_wolfssl_provenance_preserves_type_and_callsite_when_enabled():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(
        encoding="utf-8"
    )
    assert "#if PQC_WOLFSSL_ALLOCATION_PROVENANCE" in settings
    assert "__func__" in settings
    assert "__FILE__" in settings
    assert "__LINE__" in settings
    assert "NULL, NULL, 0U" in settings


def test_large_mldsa_requests_use_single_ram3_workspace_not_heap4():
    source = Path("Core/Src/pqc_wolfssl_memory.c").read_text(encoding="utf-8")
    linker = Path("STM32L4R5XX_FLASH_RELOCATED.ld").read_text(encoding="utf-8")

    assert 'section(".pqc_mldsa_workspace")' in source
    assert "PQC_WolfSSL_IsLargeMlDsaRequest" in source
    assert "type == DYNAMIC_TYPE_MLDSA" in source
    assert "PQC_WolfSSL_ClaimMlDsaWorkspace" in source
    assert "PQC_WolfSSL_ReleaseMlDsaWorkspace" in source
    assert "taskENTER_CRITICAL();" in source
    assert "taskEXIT_CRITICAL();" in source
    assert ".pqc_mldsa_workspace (NOLOAD)" in linker
    assert "} >RAM3" in linker


def test_normal_wolfssl_allocations_remain_heap4_and_alignment_preserving():
    source = Path("Core/Src/pqc_wolfssl_memory.c").read_text(encoding="utf-8")
    assert "max_align_t alignment;" in source
    assert "pvPortMalloc(total_bytes)" in source
    assert "vPortFree(header)" in source
    assert "return (void *)(header + 1);" in source
