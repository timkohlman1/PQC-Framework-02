"""Host-level regression for the actual pre-scheduler arena implementation.

Extracts the self-contained benchmark allocator from the firmware source and
executes it in a small C harness; no STM32 toolchain or hardware is required.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Core/Src/pqc_wolfssl_memory.c"


def test_benchmark_allocator_reuses_and_coalesces_freed_blocks(tmp_path):
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("host C compiler unavailable")
    source = SOURCE.read_text(encoding="utf-8")
    begin = source.index("/* Benchmark-only arena.")
    end = source.index("\n#else\nvoid PQC_WolfSSL_BenchmarkMemoryEnable(bool enabled)", begin)
    arena = source[begin:end] + "\n#endif\n"
    harness = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#define PQC_BAREMETAL_BENCHMARK_ENABLED 1
''' + arena + r'''
int main(void)
{
    unsigned char *key, *scratch, *tail, *again, *large;
    size_t i;
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
    key = PQC_WolfSSL_BenchmarkMalloc(1024U);
    scratch = PQC_WolfSSL_BenchmarkMalloc(98U * 1024U);
    tail = PQC_WolfSSL_BenchmarkMalloc(20U * 1024U);
    if (!key || !scratch || !tail || !PQC_WolfSSL_IsBenchmarkArenaPointer(key)) return 1;
    memset(key, 0x5a, 1024U);
    memset(scratch, 0xa5, 98U * 1024U);
    PQC_WolfSSL_BenchmarkFree(scratch);
    again = PQC_WolfSSL_BenchmarkMalloc(92U * 1024U);
    if (again != scratch || key[0] != 0x5a || key[1023] != 0x5a) return 2;
    for (i = 0; i < 92U * 1024U; i++)
        if (again[i] != 0U) return 3; /* Freed secret was scrubbed. */
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
    if (key[0] != 0x5a || again[0] != 0U) return 4; /* Live block retained. */
    PQC_WolfSSL_BenchmarkFree(again);
    PQC_WolfSSL_BenchmarkFree(tail);
    large = PQC_WolfSSL_BenchmarkMalloc(115U * 1024U);
    if (large != scratch || key[0] != 0x5a) return 5; /* Coalescing. */
    PQC_WolfSSL_BenchmarkFree(large);
    PQC_WolfSSL_BenchmarkFree(key);
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
    if (s_benchmark_arena_used != 0U) return 6;
    if (PQC_WolfSSL_BenchmarkMalloc(161U * 1024U) != NULL) return 7;
    puts("benchmark arena: reuse, zeroization, coalescing, live-key retention, bounds PASS");
    return 0;
}
'''
    c_file = tmp_path / "arena_test.c"
    exe = tmp_path / "arena_test"
    c_file.write_text(harness, encoding="utf-8")
    compile_result = subprocess.run(
        [cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O0", str(c_file), "-o", str(exe)],
        text=True, capture_output=True, check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([str(exe)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_benchmark_free_and_realloc_do_not_use_freertos_heap():
    source = SOURCE.read_text(encoding="utf-8")
    free_branch = source.split("void PQC_WolfSSL_TrackedFree(", 1)[1]
    realloc_branch = source.split("void *PQC_WolfSSL_TrackedRealloc(", 1)[1]
    assert "PQC_WolfSSL_BenchmarkFree(pointer);" in free_branch
    assert "if (PQC_WolfSSL_IsBenchmarkArenaPointer(pointer))" in realloc_branch
    assert "PQC_WolfSSL_BenchmarkMalloc(size);" in realloc_branch
    assert "PQC_WolfSSL_BenchmarkFree(pointer);" in realloc_branch
