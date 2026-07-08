from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_container_dockerfile_supports_wolfboot_build_signing_and_runtime_gateway_tooling():
    dockerfile = _repo_root() / "docker" / "python" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    normalised = text.lower()

    for package in (
        "build-essential",
        "gcc-arm-none-eabi",
        "binutils-arm-none-eabi",
        "libnewlib-arm-none-eabi",
        "openssh-client",
        "openssl",
    ):
        assert package in normalised

    assert "CMD [\"python\", \"-m\", \"pytest\", \"tests/unit\"]" in text

    # Avoid depending on exact Dockerfile comment wording. The concrete policy is
    # that the image contains gateway tooling only, not gateway credentials or
    # direct hardware access tools.
    forbidden_terms = (
        "id_rsa",
        "id_ed25519",
        "vpn private key",
        "mqtt password",
        "wolfboot_signing_private_key",
        "openocd",
        "stlink-tools",
        "picocom",
        "mosquitto-clients",
    )
    for term in forbidden_terms:
        assert term not in normalised


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
