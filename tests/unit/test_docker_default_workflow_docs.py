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


def test_container_ci_records_relocated_build_provenance_before_signing() -> None:
    workflow = _read(".github/workflows/ci.yml")

    relocated_build = workflow.index(
        "Build relocated firmware with framework provenance in container"
    )
    signing = workflow.index("Sign relocated application in container")

    assert relocated_build < signing
    assert "python scripts/experiment.py build" in workflow
    assert "--configure-preset RelocatedDebug" in workflow
    assert "--build-preset RelocatedDebug" in workflow
    assert "--artifact build/RelocatedDebug/stm32_basic_hal1.elf" in workflow


def test_active_documentation_rejects_unsafe_wolfboot_cleanup_guidance() -> None:
    repo_root = _repo_root()
    active_docs = [
        repo_root / "AI_BUILD_GUIDE.md",
        repo_root / "README.md",
        repo_root / "docs" / "005_remote_flash_workflow.md",
        repo_root / "docs" / "006_security_and_secrets.md",
        repo_root / "docs" / "007_framework_architecture.md",
        repo_root / "docs" / "local build commands.txt",
    ]

    prohibited_commands = (
        "make wolfboot_root=. keysclean",
        "remove-item -force .\\tools\\wolfboot\\wolfboot_signing_private_key.der",
        "remove-item -force .\\tools\\wolfboot\\wolfboot_signing_public_key.der",
        "remove-item -force .\\tools\\wolfboot\\src\\keystore.c",
        "remove-item -recurse -force .\\secrets\\wolfboot",
    )

    for path in active_docs:
        assert path.is_file(), f"Missing active documentation file: {path.relative_to(repo_root)}"
        content = path.read_text(encoding="utf-8").lower()
        for command in prohibited_commands:
            assert command not in content, (
                f"Unsafe signing-state cleanup command found in "
                f"{path.relative_to(repo_root)}: {command}"
            )


def test_operational_docs_use_wrappers_and_label_native_commands_diagnostic() -> None:
    workflow = _read("docs/005_remote_flash_workflow.md")
    local_commands = _read("docs/local build commands.txt")

    assert ".\\scripts\\dev.ps1 experiment build-wolfboot" in workflow
    assert ".\\scripts\\dev.ps1 experiment build --experiment" in workflow
    assert "--configure-preset RelocatedDebug" in workflow
    assert "--build-preset RelocatedDebug" in workflow
    assert "generated-state provenance" in workflow
    assert "## Diagnostic fallback" in workflow
    assert "Host-native commands may be used only" in workflow

    assert "Local Build Diagnostic Fallback" in local_commands
    assert "normal project workflow is Docker-hosted" in local_commands
    assert "generated-state preflight" in local_commands
    assert "not the reproducible validation gate" in local_commands


def test_signing_docs_do_not_describe_partial_key_generation_as_normal() -> None:
    readme = _read("README.md").lower()
    assert "may locally generate missing profile keys" not in readme
    assert "completely absent profile signing tuple" in readme
    assert "partial or mismatched tuple state fails safely" in readme


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
