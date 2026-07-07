from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_container_dockerfile_supports_wolfboot_build_and_signing_tooling():
    dockerfile = _repo_root() / "docker" / "python" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "build-essential" in text
    assert "gcc-arm-none-eabi" in text
    assert "binutils-arm-none-eabi" in text
    assert "libnewlib-arm-none-eabi" in text
    assert "wolfBoot builds" in text
    assert "contains no secret material" in text
    assert "CMD [\"python\", \"-m\", \"pytest\", \"tests/unit\"]" in text


def test_dockerignore_excludes_wolfboot_generated_keytools_and_signing_material():
    dockerignore = _repo_root() / ".dockerignore"
    text = dockerignore.read_text(encoding="utf-8")

    required_patterns = {
        "secrets/",
        "tools/wolfboot/.config",
        "tools/wolfboot/*.der",
        "tools/wolfboot/*.pem",
        "tools/wolfboot/*private*",
        "tools/wolfboot/*signing_key*",
        "tools/wolfboot/tools/keytools/keygen",
        "tools/wolfboot/tools/keytools/sign",
        "tools/wolfboot/src/keystore.c",
        "experiment/mqtt-broker/runtime/",
    }

    missing = sorted(pattern for pattern in required_patterns if pattern not in text)
    assert missing == []
