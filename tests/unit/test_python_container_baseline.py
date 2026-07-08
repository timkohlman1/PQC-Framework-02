from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "python" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
README = REPO_ROOT / "README.md"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_python_container_definition_supports_stm32_local_builds_and_opt_in_gateway_checks() -> None:
    dockerfile = _read(DOCKERFILE)

    assert "FROM python:3.13-slim" in dockerfile
    assert "COPY requirements-dev.txt" in dockerfile
    assert '["python", "-m", "pytest", "tests/unit"]' in dockerfile

    required_terms = [
        "cmake",
        "ninja-build",
        "gcc-arm-none-eabi",
        "binutils-arm-none-eabi",
        "libnewlib-arm-none-eabi",
        "openssh-client",
        "openssl",
        "gateway-capable integration checks",
        "provided at container runtime",
    ]
    normalised = dockerfile.lower()
    for term in required_terms:
        assert term in normalised

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


def test_readme_documents_container_boundaries_and_stm32_local_builds() -> None:
    readme = _read(README)

    assert "docker build -f docker/python/Dockerfile -t pqc-framework-stm32-build ." in readme
    assert "pqc-framework-stm32-build python -m pytest tests/unit" in readme
    assert "pqc-framework-stm32-build python scripts/experiment.py status" in readme
    assert "pqc-framework-stm32-build cmake --preset Debug" in readme
    assert "pqc-framework-stm32-build cmake --build --preset Debug" in readme
    assert "pqc-framework-stm32-build cmake --preset RelocatedDebug" in readme
    assert "pqc-framework-stm32-build cmake --build --preset RelocatedDebug" in readme
    assert "--pqc-require-local-build" in readme

    boundary_terms = [
        "wolfBoot build/signing tools",
        "gateway SSH",
        "UART devices",
        "ST-LINK/USB access",
        "Wi-Fi-module access",
        "hardware workflows",
    ]
    for term in boundary_terms:
        assert term in readme
