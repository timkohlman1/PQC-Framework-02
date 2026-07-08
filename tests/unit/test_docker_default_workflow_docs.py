from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text(encoding="utf-8")


def test_readme_documents_docker_as_default_workflow() -> None:
    readme = _read("README.md")

    assert "The default development path is Docker-hosted Linux execution" in readme
    assert ".\\scripts\\dev.ps1 pytest" in readme
    assert ".\\scripts\\dev.ps1 experiment-gateway run" in readme
    assert "Host-native commands remain available as an explicit fallback" in readme


def test_ai_build_guide_documents_gateway_hardware_container_default() -> None:
    guide = _read("AI_BUILD_GUIDE.md")

    assert "The project default is Docker-hosted Linux execution" in guide
    assert "gateway-mediated hardware experiments" in guide
    assert "Host-native Windows or development-machine builds remain available only as an explicit manual fallback" in guide
    assert "Do not claim hardware" in guide


def test_docker_wrappers_exist_for_default_and_gateway_paths() -> None:
    repo_root = _repo_root()
    ps1 = (repo_root / "scripts/dev.ps1").read_text(encoding="utf-8")
    sh = (repo_root / "scripts/dev.sh").read_text(encoding="utf-8")

    for wrapper in (ps1, sh):
        assert "pytest-hardware" in wrapper
        assert "experiment-gateway" in wrapper
        assert "PQC_CONTAINER_ENABLE_GATEWAY=1" in wrapper
        assert "PQC_DOCKER_IMAGE" in wrapper
