from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text(encoding="utf-8")


def test_readme_documents_docker_as_default_workflow() -> None:
    readme = _read("README.md")

    assert "The default development path is Docker-hosted Linux execution" in readme
    assert "./scripts/dev.sh pytest" in readme
    assert "./scripts/dev.sh experiment-gateway run" in readme
    assert "Host-native commands remain available as an explicit fallback" in readme


def test_ai_build_guide_documents_gateway_hardware_container_default() -> None:
    guide = _read("AI_BUILD_GUIDE.md")

    assert "The project default is Docker-hosted Linux execution" in guide
    assert "gateway-mediated hardware experiments" in guide
    assert "Host-native development-machine builds remain available only as an explicit manual fallback" in guide
    assert "Do not claim hardware" in guide


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


def test_operational_docs_use_wrappers_and_label_native_commands_diagnostic() -> None:
    workflow = _read("docs/005_remote_flash_workflow.md")
    local_commands = _read("docs/local build commands.txt")

    assert "./scripts/dev.sh experiment build-wolfboot" in workflow
    assert "./scripts/dev.sh experiment build --experiment" in workflow
    assert "--configure-preset Release" in workflow
    assert "--build-preset Release" in workflow
    assert "generated-state provenance" in workflow
    assert "## Diagnostic fallback" in workflow
    assert "Host-native commands may be used only" in workflow

    assert "Local Build Diagnostic Fallback" in local_commands
    assert "normal project workflow is Docker-hosted" in local_commands
    assert "generated-state preflight" in local_commands
    assert "not the reproducible validation gate" in local_commands


def test_signing_docs_do_not_describe_partial_key_generation_as_normal() -> None:
    readme = _read("README.md").lower()
    workflow = _read("docs/005_remote_flash_workflow.md").lower()

    assert "may locally generate missing profile keys" not in readme
    assert "silently reconstruct partial signing state" in readme
    assert "completely absent tuple" in workflow
    assert "partially missing tuple: fail before build/signing" in workflow
    assert "mismatched tuple: fail before build/signing" in workflow


def test_pytest_cleanup_is_documented_as_supplementary_hygiene() -> None:
    for path in (
        "AI_BUILD_GUIDE.md",
        "README.md",
        "docs/005_remote_flash_workflow.md",
        "docs/006_security_and_secrets.md",
        "docs/007_framework_architecture.md",
    ):
        content = _read(path).lower()
        assert "supplementary cross-platform hygiene" in content


def test_python_passthrough_is_supported_and_documented() -> None:
    sh = _read("scripts/dev.sh")
    readme = _read("README.md")
    guide = _read("AI_BUILD_GUIDE.md")

    assert 'python)' in sh
    assert 'run_container python "$@"' in sh
    assert 'python-gateway)' in sh
    assert 'run_container --gateway python "$@"' in sh
    assert './scripts/dev.sh python' in readme
    assert './scripts/dev.sh python-gateway' in readme
    assert './scripts/dev.sh python' in guide
    assert './scripts/dev.sh python-gateway' in guide


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
