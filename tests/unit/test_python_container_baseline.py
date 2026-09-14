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

    assert "FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e" in dockerfile
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


def test_readme_documents_container_default_boundaries_and_fallbacks() -> None:
    readme = _read(README)
    readme_lower = readme.lower()

    default_policy_terms = [
        "docker-hosted linux",
        "default development path",
        "project wrapper scripts",
        "scripts\\dev.ps1",
        "scripts/dev.sh",
        "host-native commands remain available as an explicit fallback",
    ]
    for term in default_policy_terms:
        assert term in readme_lower

    workflow_terms = [
        "build-image",
        "pytest tests/unit",
        "experiment status",
        "cmake --preset Debug",
        "cmake --build --preset Debug",
        "cmake --preset Release",
        "cmake --build --preset Release",
        "--pqc-require-local-build",
    ]
    for term in workflow_terms:
        assert term in readme

    boundary_terms = [
        "SSH/SCP",
        "runtime-mounted SSH access",
        "direct UART devices",
        "ST-LINK/USB passthrough",
        "Wi-Fi-module passthrough",
        "hardware workflows",
    ]
    for term in boundary_terms:
        assert term in readme

    secret_boundary_terms = [
        "must not be committed",
        "baked into the image",
        "Private signing keys",
    ]
    for term in secret_boundary_terms:
        assert term in readme
