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


def test_both_mldsa_tls_levels_enable_the_same_workspace_routing():
    source = Path("Core/Src/pqc_wolfssl_memory.c").read_text()
    assert source.count("#if PQC_TLS_ENABLE_MLDSA_44 || PQC_TLS_ENABLE_MLDSA_65") == 7
    assert "#if PQC_TLS_ENABLE_MLDSA_65\n" not in source


def test_mldsa_scratch_routing_and_exclusive_arena_at_both_levels(tmp_path):
    """Execute the firmware routing/arena code at actual scratch sizes."""
    import subprocess
    source = Path("Core/Src/pqc_wolfssl_memory.c").read_text()
    policy = source[source.index("#ifndef PQC_TLS_ENABLE_MLDSA_44"):source.index("#if PQC_WOLFSSL_ALLOCATION_PROVENANCE", source.index("#ifndef PQC_TLS_ENABLE_MLDSA_44"))]
    pos = source.index("static uint8_t s_mldsa_workspace")
    start = source.rfind("#if ", 0, pos)
    globals_ = source[start:source.index("#endif", pos)+len("#endif")]
    start = source.index("static bool PQC_WolfSSL_IsRAM3WorkspacePointer")
    functions = source[start:source.index("#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS", start)]
    harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define DYNAMIC_TYPE_MLDSA 7
#define PQC_MLDSA_WORKSPACE_SIZE_BYTES (96U * 1024U)
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
""" + policy + globals_ + "\n" + functions + r"""
int main(void) {
    size_t minimum = EXPECTED_MINIMUM;
    assert(PQC_WolfSSL_IsLargeMlDsaRequest(minimum, DYNAMIC_TYPE_MLDSA));
    assert(!PQC_WolfSSL_IsLargeMlDsaRequest(minimum-1, DYNAMIC_TYPE_MLDSA));
    assert(!PQC_WolfSSL_IsLargeMlDsaRequest(76U*1024U, 99));
    /* 44 default verification/signing are 29/49 KiB; 65 are 48/76 KiB. */
    assert(PQC_WolfSSL_IsLargeMlDsaRequest(VERIFY_BYTES, DYNAMIC_TYPE_MLDSA));
    assert(PQC_WolfSSL_IsLargeMlDsaRequest(SIGN_BYTES, DYNAMIC_TYPE_MLDSA));
    void *p = PQC_WolfSSL_ClaimMlDsaWorkspace(VERIFY_BYTES);
    assert(p && PQC_WolfSSL_IsRAM3WorkspacePointer(p));
    assert(PQC_WolfSSL_ClaimMlDsaWorkspace(SIGN_BYTES) == NULL);
    PQC_WolfSSL_ReleaseMlDsaWorkspace();
    assert(PQC_WolfSSL_ClaimMlDsaWorkspace(SIGN_BYTES) == p);
    assert(s_mldsa_workspace_request_bytes == SIGN_BYTES);
    PQC_WolfSSL_ReleaseMlDsaWorkspace();
    assert(PQC_WolfSSL_ClaimMlDsaWorkspace(PQC_MLDSA_WORKSPACE_SIZE_BYTES+1) == NULL);
    assert(s_mldsa_workspace_peak_request_bytes == PQC_MLDSA_WORKSPACE_SIZE_BYTES+1);
    assert(PQC_WolfSSL_ClaimMlDsaWorkspace(minimum) == p);
    return 0;
}
"""
    c = tmp_path/'routing.c';c.write_text(harness)
    for level,verify,sign,minimum in [(44,29,49,29),(65,48,76,32)]:
        for small in (False,True):
            exe = tmp_path/f'routing-{level}-{small}'
            cmd = ['cc','-std=c11','-Wall','-Wextra','-Werror',f'-DPQC_TLS_ENABLE_MLDSA_{level}=1',
                   f'-DEXPECTED_MINIMUM={8 if small else minimum}U*1024U',
                   f'-DVERIFY_BYTES={verify}U*1024U',f'-DSIGN_BYTES={sign}U*1024U']
            if small:cmd += ['-DPQC_MLDSA_VERIFY_SMALL_MEM=1']
            subprocess.run(cmd+[str(c),'-o',str(exe)],check=True,capture_output=True,text=True)
            subprocess.run([str(exe)],check=True,capture_output=True,text=True)
