from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "python" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
README = REPO_ROOT / "README.md"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_python_container_definition_supports_stm32_builds_and_runtime_gateway_access() -> None:
    dockerfile = _read(DOCKERFILE)
    normalised = dockerfile.lower()

    assert "FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285" in dockerfile
    assert "COPY requirements-dev.txt" in dockerfile
    assert '["python", "-m", "pytest", "tests/unit"]' in dockerfile

    build_tool_packages = [
        "cmake",
        "ninja-build",
        "gcc-arm-none-eabi",
        "binutils-arm-none-eabi",
        "libnewlib-arm-none-eabi",
    ]
    for package in build_tool_packages:
        assert package in normalised

    runtime_gateway_packages = [
        "openssh-client",
        "openssl",
        "tshark",
    ]
    for package in runtime_gateway_packages:
        assert package in normalised

    # The image may document gateway-capable workflows in comments, but tests should
    # validate the concrete boundary: gateway access is SSH/TLS tooling only and
    # credentials are not baked into the image.
    forbidden_terms = [
        "stm32cube",
        "openocd",
        "stlink-tools",
        "picocom",
        "mosquitto-clients",
        "mosquitto",
        "docker",
        "id_rsa",
        "id_ed25519",
        "wolfboot_signing_private_key",
    ]
    for term in forbidden_terms:
        assert term not in normalised



def test_python_container_pins_debian_snapshot_and_toolchain_packages() -> None:
    dockerfile = _read(DOCKERFILE)

    assert "ARG DEBIAN_SNAPSHOT=20260914T040000Z" in dockerfile
    assert "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/" in dockerfile
    assert "snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/" in dockerfile
    assert dockerfile.count("Check-Valid-Until: no") == 2

    expected_packages = [
        "ca-certificates=20250419",
        "git=1:2.47.3-0+deb13u1",
        "openssh-client=1:10.0p1-7+deb13u4",
        "openssl=3.5.7-1~deb13u2",
        "tshark=4.4.18-0+deb13u1",
        "build-essential=12.12",
        "cmake=3.31.6-2",
        "ninja-build=1.12.1-1",
        "gcc-arm-none-eabi=15:14.2.rel1-1",
        "binutils-arm-none-eabi=2.44-3+23+b1",
        "libnewlib-arm-none-eabi=4.5.0.20241231-1",
    ]
    for package in expected_packages:
        assert package in dockerfile

    # The maintained build image must not silently return to live Debian mirrors.
    assert "deb.debian.org" not in dockerfile

def test_requirements_dev_keeps_python_test_dependencies_small() -> None:
    requirements = _read(REQUIREMENTS_DEV)

    assert "pytest" in requirements
    assert "stm32cube" not in requirements.lower()
    assert "wolfboot" not in requirements.lower()


def test_dockerignore_excludes_generated_outputs_and_secrets() -> None:
    dockerignore = _read(DOCKERIGNORE)

    required_patterns = [
        "build/",
        "results/*",
        "!results/.gitkeep",
        ".last_successful_build.json",
        ".build_number",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        "secrets/",
        "*.env",
        "*.elf",
        "*.bin",
        "*.hex",
        "*.map",
        "*.su",
        "tools/wolfboot/.config",
        "tools/wolfboot/*.der",
        "tools/wolfboot/*.pem",
        "experiment/mqtt-broker/runtime/",
        "experiment/mqtt-broker/data/",
        "experiment/mqtt-broker/log/",
        "experiment/mqtt-broker/.env",
    ]
    for pattern in required_patterns:
        assert pattern in dockerignore
