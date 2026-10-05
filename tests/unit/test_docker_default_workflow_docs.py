from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text(encoding="utf-8")


def test_docker_wrappers_exist_for_default_and_gateway_paths() -> None:
    repo_root = _repo_root()
    sh = (repo_root / "scripts/dev.sh").read_text(encoding="utf-8")

    assert "pytest-hardware" in sh
    assert "experiment-gateway" in sh
    assert "PQC_CONTAINER_ENABLE_GATEWAY=1" in sh
    assert "PQC_DOCKER_IMAGE" in sh
    assert "python" in sh


def test_container_ci_records_relocated_build_provenance_before_signing() -> None:
    workflow = _read(".github/workflows/ci.yml")

    relocated_build = workflow.index(
        "Build relocated firmware with framework provenance in container"
    )
    signing = workflow.index("Sign relocated application in container")

    assert relocated_build < signing
    assert "./scripts/dev.sh experiment build" in workflow
    assert "./scripts/dev.sh experiment sign-application" in workflow
    assert "--configure-preset Release" in workflow
    assert "--build-preset Release" in workflow
    assert "RelocatedDebug" not in workflow
    assert "--artifact build/Release/stm32_basic_hal1.elf" in workflow


def test_linux_is_the_sole_supported_development_wrapper() -> None:
    assert not (_repo_root() / "scripts/dev.ps1").exists()
    for path in (
        "AI_BUILD_GUIDE.md",
        "README.md",
        "docs/001_ai_feature_request_workflow.md",
        "docs/008_chatgpt_project_prompt.md",
        "docs/005_remote_flash_workflow.md",
        "experiment/mqtt-broker/README.md",
    ):
        content = _read(path)
        assert "dev.ps1" not in content, path
        assert "./scripts/dev.sh" in content or path in (
            "docs/001_ai_feature_request_workflow.md",
            "docs/008_chatgpt_project_prompt.md",
        ), path


def test_common_documented_wrapper_commands_have_dispatch_paths() -> None:
    import re

    wrapper = _read("scripts/dev.sh")
    readme = _read("README.md")
    commands = set(re.findall(r"\./scripts/dev\.sh ([a-z][a-z-]*)", readme))
    assert {"build-image", "pytest", "python", "experiment", "experiment-gateway", "campaign-gateway"} <= commands
    for command in commands:
        assert re.search(rf"(?m)^\s*{re.escape(command)}\)", wrapper), command
    assert 'run_container python "$@"' in wrapper
    assert 'run_container --gateway python "$@"' in wrapper
