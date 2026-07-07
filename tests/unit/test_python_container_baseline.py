from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "python" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
README = REPO_ROOT / "README.md"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_python_container_definition_is_python_only() -> None:
    dockerfile = _read(DOCKERFILE)

    assert "FROM python:3.13-slim" in dockerfile
    assert "COPY requirements-dev.txt" in dockerfile
    assert '["python", "-m", "pytest", "tests/unit"]' in dockerfile

    forbidden_terms = [
        "arm-none-eabi",
        "stm32cube",
        "cmake",
        "ninja",
        "openssh-client",
        "ssh ",
        "mosquitto",
        "docker",
        "wolfboot",
    ]
    normalised = dockerfile.lower()
    for term in forbidden_terms:
        assert term not in normalised


def test_python_container_dependencies_are_minimal() -> None:
    requirements = _read(REQUIREMENTS_DEV)

    assert "pytest" in requirements
    assert "cmake" not in requirements.lower()
    assert "ninja" not in requirements.lower()


def test_python_container_build_context_excludes_generated_outputs_and_secrets() -> None:
    dockerignore = _read(DOCKERIGNORE)

    required_patterns = [
        "build/",
        "results/*",
        "secrets/",
        "*.env",
        "tools/wolfboot/*.der",
        "tools/wolfboot/*.pem",
        "tools/wolfboot/*private*",
        "experiment/mqtt-broker/runtime/",
        "experiment/mqtt-broker/.env",
    ]
    for pattern in required_patterns:
        assert pattern in dockerignore


def test_readme_documents_python_only_container_boundaries() -> None:
    readme = _read(README)

    assert "docker build -f docker/python/Dockerfile -t pqc-framework-python ." in readme
    assert "python -m pytest tests/unit" in readme
    assert "python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml" in readme
    assert "does not include STM32 toolchains" in readme
    assert "does not provide gateway SSH, UART, broker, Wi-Fi-module, ST-LINK, or hardware access" in readme
