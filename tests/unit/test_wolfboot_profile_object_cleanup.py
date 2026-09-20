from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.wolfboot_build import (
    WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS,
    _remove_wolfboot_host_tool_outputs,
)


def test_profile_dependent_cleanup_covers_recursive_wolfssl_objects(tmp_path):
    source_dir = tmp_path / "wolfboot"
    outputs = [
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.o",
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.d",
        source_dir
        / "lib/wolfssl/wolfcrypt/src/port/arm/thumb2-sha3-asm.o",
        source_dir / "lib/wolfssl/wolfcrypt/src/wc_mldsa.o",
        source_dir / "src/libwolfboot.o",
        source_dir / "src/libwolfboot.d",
        source_dir / "src/update_flash_hwswap.o",
        source_dir / "hal/stm32l4.o",
        source_dir / "hal/spi/spi.o",
    ]
    sources = [
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.c",
        source_dir / "src/libwolfboot.c",
        source_dir / "src/keystore.c",
        source_dir / "hal/stm32l4.c",
    ]
    signing_key = source_dir / "wolfboot_signing_private_key.der"
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated")
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("/* source */\n", encoding="utf-8")
    signing_key.write_bytes(b"untouched test fixture")

    removed = _remove_wolfboot_host_tool_outputs(source_dir)

    assert set(removed) == set(outputs)
    assert all(not path.exists() for path in outputs)
    assert all(source.is_file() for source in sources)
    assert signing_key.read_bytes() == b"untouched test fixture"
    assert "src/**/*.o" in WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS
    assert "hal/**/*.o" in WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS
    assert "lib/wolfssl/**/*.o" in WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS
    assert "lib/wolfssl/**/*.d" in WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS
