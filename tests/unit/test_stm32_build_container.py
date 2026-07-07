from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dockerfile_text() -> str:
    return (_repo_root() / "docker" / "python" / "Dockerfile").read_text(encoding="utf-8")


def test_container_image_installs_stm32_local_build_toolchain() -> None:
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


def test_container_image_does_not_install_gateway_or_hardware_access_tools() -> None:
    dockerfile = _dockerfile_text()

    for package in (
        "openssh-client",
        "openocd",
        "stlink-tools",
        "picocom",
        "mosquitto-clients",
    ):
        assert package not in dockerfile
