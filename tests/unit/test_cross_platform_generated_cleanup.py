from __future__ import annotations

from pathlib import Path

import conftest


def test_clean_generated_build_artifacts_removes_only_generated_outputs(tmp_path: Path) -> None:
    repo_root = tmp_path

    generated_files = [
        repo_root / "build" / "Debug" / "CMakeCache.txt",
        repo_root / "build" / "RelocatedDebug" / "CMakeCache.txt",
        repo_root / "tools" / "wolfboot" / ".config",
        repo_root / "tools" / "wolfboot" / "wolfboot.elf",
        repo_root / "tools" / "wolfboot" / "wolfboot.bin",
        repo_root / "tools" / "wolfboot" / "wolfboot.hex",
        repo_root / "tools" / "wolfboot" / "wolfboot.map",
        repo_root / "tools" / "wolfboot" / "src" / "image.o",
        repo_root / "tools" / "wolfboot" / "src" / "image.d",
        repo_root / "tools" / "wolfboot" / "hal" / "stm32l4.o",
        repo_root / "tools" / "wolfboot" / "hal" / "stm32l4.d",
        repo_root / "tools" / "wolfboot" / "tools" / "keytools" / "asn.o",
        repo_root / "tools" / "wolfboot" / "tools" / "keytools" / "asn.d",
        repo_root / "tools" / "wolfboot" / "tools" / "keytools" / "keygen.exe",
        repo_root / "tools" / "wolfboot" / "tools" / "keytools" / "sign.exe",
    ]
    preserved_tuple_files = [
        repo_root / "tools" / "wolfboot" / "wolfboot_signing_private_key.der",
        repo_root / "tools" / "wolfboot" / "wolfboot_signing_public_key.der",
        repo_root / "tools" / "wolfboot" / "src" / "keystore.c",
    ]
    source_file = repo_root / "tools" / "wolfboot" / "src" / "image.c"
    canonical_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"

    for path in [*generated_files, *preserved_tuple_files, source_file, canonical_key]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")

    removed = conftest._clean_generated_build_artifacts(repo_root)

    assert removed
    for path in generated_files:
        assert not path.exists()
    for path in preserved_tuple_files:
        assert path.is_file()
    assert source_file.is_file()
    assert canonical_key.is_file()


def test_foreign_generated_build_state_detects_container_paths(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    cache_path = repo_root / "build" / "Debug" / "CMakeCache.txt"
    dep_path = repo_root / "tools" / "wolfboot" / "tools" / "keytools" / "asn.d"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("CMAKE_HOME_DIRECTORY:INTERNAL=/workspace", encoding="utf-8")
    dep_path.write_text("asn.o: /workspace/tools/wolfboot/lib/wolfssl/wolfcrypt/src/asn.c", encoding="utf-8")

    monkeypatch.setattr(conftest, "_running_in_container", lambda: False)

    assert conftest._has_foreign_generated_build_state(repo_root) is True
