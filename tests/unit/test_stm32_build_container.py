from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dockerfile_text() -> str:
    return (_repo_root() / "docker" / "python" / "Dockerfile").read_text(encoding="utf-8")


def test_container_image_installs_stm32_build_toolchain() -> None:
    dockerfile = _dockerfile_text()

    for package in (
        "cmake",
        "ninja-build",
        "gcc-arm-none-eabi",
        "binutils-arm-none-eabi",
        "libnewlib-arm-none-eabi",
    ):
        assert package in dockerfile

    assert "apt-get install --no-install-recommends -y" in dockerfile


def test_container_default_command_remains_non_hardware_unit_tests() -> None:
    dockerfile = _dockerfile_text()

    assert 'CMD ["python", "-m", "pytest", "tests/unit"]' in dockerfile


def test_container_image_installs_only_runtime_gateway_tooling_not_hardware_access_tools() -> None:
    dockerfile = _dockerfile_text()
    normalised = dockerfile.lower()

    # SSH is sufficient because hardware operations remain gateway-mediated.
    assert "openssh-client" in normalised
    assert "openssl" in normalised

    for package in (
        "openocd",
        "stlink-tools",
        "picocom",
        "mosquitto-clients",
    ):
        assert package not in normalised

    for secret_marker in (
        "id_rsa",
        "id_ed25519",
        "mqtt password",
        "wolfboot_signing_private_key",
    ):
        assert secret_marker not in normalised
