from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_AI_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/001_ai_feature_request_workflow.md",
    "docs/008_chatgpt_project_prompt.md",
)
OBSOLETE_REFERENCES = (
    "docs/009_chatgpt_project_prompt_release_readiness_review.md",
    "docs/phase11_plan.md",
    "docs/plase11_checklist.md",
)
PROJECT_DOCUMENT_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(AI_BUILD_GUIDE\.md|README\.md|docs/[A-Za-z0-9_./-]+\.(?:md|txt))"
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _tracked_files() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {
        path.decode("utf-8")
        for path in completed.stdout.split(b"\0")
        if path
    }


def test_explicit_ai_documentation_references_exist_and_are_tracked() -> None:
    tracked = _tracked_files()

    for source in ACTIVE_AI_DOCUMENTS:
        assert source in tracked, f"Active AI document is not tracked: {source}"
        content = _read(source)
        references = set(PROJECT_DOCUMENT_REFERENCE.findall(content))

        for reference in sorted(references):
            assert (REPO_ROOT / reference).is_file(), (
                f"{source} references missing project documentation: {reference}"
            )
            assert reference in tracked, (
                f"{source} references untracked project documentation: {reference}"
            )


def test_obsolete_ai_workflow_references_are_absent() -> None:
    for source in ACTIVE_AI_DOCUMENTS:
        content = _read(source)
        for obsolete_reference in OBSOLETE_REFERENCES:
            assert obsolete_reference not in content, (
                f"{source} still references obsolete documentation: "
                f"{obsolete_reference}"
            )


def test_supported_ai_entry_points_are_consistent() -> None:
    documents = {
        "AI_BUILD_GUIDE.md": _read("AI_BUILD_GUIDE.md"),
        "README.md": _read("README.md"),
        "docs/001_ai_feature_request_workflow.md": _read(
            "docs/001_ai_feature_request_workflow.md"
        ),
        "docs/008_chatgpt_project_prompt.md": _read(
            "docs/008_chatgpt_project_prompt.md"
        ),
    }

    for content in documents.values():
        assert "AI_BUILD_GUIDE.md" in content
        assert "docs/001_ai_feature_request_workflow.md" in content
        assert "there is no separate release-readiness prompt document" in content.lower()

    for path, content in documents.items():
        if path != "docs/008_chatgpt_project_prompt.md":
            assert "docs/008_chatgpt_project_prompt.md" in content


SIGNING_STATE_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/005_remote_flash_workflow.md",
    "docs/006_security_and_secrets.md",
    "docs/007_framework_architecture.md",
)


def test_active_docs_define_safe_signing_tuple_lifecycle() -> None:
    combined = "\n".join(_read(path).lower() for path in SIGNING_STATE_DOCUMENTS)

    required = (
        "completely absent tuple",
        "complete matching tuple",
        "partially missing tuple",
        "mismatched tuple",
        "canonical private key",
    )
    for phrase in required:
        assert phrase in combined, f"Missing signing-state lifecycle wording: {phrase}"

    assert "silently replace" in combined
    assert "silently reconstruct" in combined or "silently regenerated" in combined


def test_generated_state_preflight_is_primary_and_pytest_cleanup_is_supplementary() -> None:
    for path in SIGNING_STATE_DOCUMENTS:
        content = _read(path).lower()
        assert "generated-state preflight" in content, (
            f"{path} must identify generated-state preflight"
        )

    combined = "\n".join(_read(path).lower() for path in SIGNING_STATE_DOCUMENTS)
    assert "primary mechanism" in combined
    assert "supplementary cross-platform hygiene" in combined
    assert "must not remove" in combined


def test_canonical_relocated_build_precedes_signing_in_active_docs() -> None:
    command_fragment = (
        "experiment build --experiment configs/experiments/baseline_direct_uart.yaml "
        "--configure-preset relocateddebug --build-preset relocateddebug "
        "--artifact build/relocateddebug/stm32_basic_hal1.elf"
    )
    for path in ("AI_BUILD_GUIDE.md", "README.md", "docs/005_remote_flash_workflow.md"):
        content = _read(path).lower()
        build_index = content.find(command_fragment)
        signing_index = content.find("experiment sign-application", build_index + 1)
        assert build_index >= 0, f"{path} is missing the framework-recorded relocated build"
        assert signing_index > build_index, f"{path} must show relocated build before signing"

    architecture = _read("docs/007_framework_architecture.md").lower()
    assert "direct wrapped cmake remains a diagnostic fallback only" in architecture

MQTT_COMMAND_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/007_framework_architecture.md",
    "experiment/mqtt-broker/README.md",
)


def test_powershell_wolfmqtt_examples_use_named_client_argument_boundary() -> None:
    root_readme = _read("README.md")
    architecture = _read("docs/007_framework_architecture.md")
    guide = _read("AI_BUILD_GUIDE.md")

    assert "--client-args '-h'" in root_readme
    assert "'-p'" in root_readme
    assert "'-t'" in root_readme

    combined = "\n".join((root_readme, architecture, guide)).lower()
    assert "after `--client-args`" in combined
    assert "active powershell guidance does not use a standalone `--`" in combined
    assert "pass the selected upstream wolfmqtt client arguments after `--`" not in combined


def test_gateway_and_localhost_certificate_examples_are_distinct() -> None:
    gateway_command = (
        "provision-certs --server-name pqc-gateway1 "
        "--host-config configs/hosts/gateway.yaml"
    )
    localhost_command = "provision-certs --server-name localhost"

    for path in ("README.md", "AI_BUILD_GUIDE.md", "experiment/mqtt-broker/README.md"):
        content = _read(path)
        assert gateway_command in content, f"{path} is missing gateway IP-SAN provisioning"

    for path in ("README.md", "experiment/mqtt-broker/README.md"):
        content = _read(path)
        assert localhost_command in content, f"{path} is missing the localhost-only example"
        assert "localhost-only" in content.lower()


def test_mqtt_command_docs_preserve_compose_path_and_evidence_boundary() -> None:
    combined = "\n".join(_read(path) for path in MQTT_COMMAND_DOCUMENTS)

    assert "experiment/mqtt-broker/compose.yaml" in combined
    assert "host_side" in combined or "host-side" in combined
    assert "wolfMQTT-on-STM32" in combined
    assert "end-to-end wireless" in combined


def test_host_wolfmqtt_wrapper_help_uses_client_args_contract() -> None:
    source = _read("experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py")

    assert "after --client-args" in source
    assert "error=run requires explicit wolfMQTT client arguments after --client-args" in source
    assert "PowerShell forwarding path" in source


def test_architecture_contains_canonical_current_capability_matrix() -> None:
    architecture = _read("docs/007_framework_architecture.md")

    assert "## Canonical current capability matrix" in architecture
    required_rows = (
        "Direct-flash HAL/FreeRTOS application",
        "wolfBoot secure-boot build, signing, and flashing",
        "MQTT/TLS config and result schema",
        "Deterministic fake/no-network MQTT transport",
        "Native host wolfMQTT/wolfSSL broker validation",
        "STM32 lwIP UDP loopback",
        "STM32 wolfSSL transport boundary",
        "STM32 wolfMQTT integration",
        "ST67W61M1 hardware-backed network backend",
        "Real classical STM32 MQTT-over-TLS",
        "PQC or hybrid STM32 MQTT-over-TLS",
    )
    for row in required_rows:
        assert f"| {row} |" in architecture, f"Missing capability matrix row: {row}"

    for heading in (
        "Build-only",
        "STM32-local runtime",
        "Host-side",
        "Broker-side",
        "Gateway/hardware",
        "Evidence class or boundary",
        "Current limitation",
    ):
        assert heading in architecture


def test_architecture_preserves_mqtt_hardware_boundaries() -> None:
    architecture = _read("docs/007_framework_architecture.md")

    assert "STM32 wolfMQTT integration | Supported" in architecture
    assert "stm32-fake-no-network-initialization-only" in architecture
    assert "unavailable-transport-only" in architecture
    assert "ST67W61M1 hardware-backed network backend | Compile-time driver/interface preparation only | Unimplemented" in architecture
    assert "Real classical STM32 MQTT-over-TLS | Dependencies and boundaries are prepared, but no complete runtime path exists | Unimplemented" in architecture
    assert "STM32-local wolfMQTT build/runtime integration and real wolfSSL transport/handshake integration" not in architecture

ENTRY_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/000_project_overview.md",
    "docs/004_baseline_hal_app.md",
)


def test_entry_documents_match_canonical_mqtt_evidence_boundaries() -> None:
    combined = "\n".join(_read(path).lower() for path in ENTRY_DOCUMENTS)

    for phrase in (
        "build-only",
        "local-only",
        "fake/no-network",
        "host-side",
        "unavailable transport",
        "st67w61m1",
    ):
        assert phrase in combined, f"Missing D2.2 capability-boundary wording: {phrase}"

    assert "real st67w61m1-backed networking" in combined
    assert "no socket i/o" in combined
    assert "end-to-end" in combined


def test_overview_does_not_describe_all_mqtt_or_wolfssl_work_as_unimplemented() -> None:
    overview = _read("docs/000_project_overview.md").lower()

    assert "mqtt transport experiments" not in overview
    assert "tls/wolfssl transport experiments" not in overview
    assert "framework and fake/no-network" in overview
    assert "broker-side and host-side" in overview
    assert "stm32 build-only" in overview
    assert "stm32 local-only" in overview
    assert "stm32 unavailable transport" in overview
    assert "future hardware-backed" in overview


def test_baseline_document_matches_scheduler_and_task_smoke_sequence() -> None:
    baseline = _read("docs/004_baseline_hal_app.md")
    representative = baseline.split("A representative sequence is:", maxsplit=1)[1]

    ordered_markers = (
        "stm32-basic_hal1 boot v0.1.0",
        "lwIP runtime smoke: context=pre_scheduler scheduler=not_started",
        "lwIP network interface: evidence=lwip-netif-state-only",
        "wolfSSL TLS context smoke: context=pre_scheduler scheduler=not_started",
        "wolfSSL transport boundary: evidence=unavailable-transport-only",
        "FreeRTOS defaultTask created:",
        "FreeRTOS scheduler starting:",
        "FreeRTOS defaultTask started: periodic tick task active",
        "FreeRTOS task-context smoke starting:",
        "lwIP local loopback smoke:",
        "wolfMQTT runtime smoke:",
        "FreeRTOS task-context smoke complete:",
        "\ntick\n",
    )

    positions = [representative.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
    assert "evidence=stm32-local-lwip-loopback-only" in baseline
    assert "evidence=stm32-fake-no-network-initialization-only" in baseline
    assert "socket_io=not-performed" in baseline
    assert "does not provide evidence of ST67W61M1 detection" in baseline

OPERATIONAL_WORKFLOW_DOCUMENTS = (
    "docs/002_host_gateway_setup.md",
    "docs/003_stm32_board_setup.md",
    "docs/005_remote_flash_workflow.md",
    "docs/006_security_and_secrets.md",
    "experiment/mqtt-broker/README.md",
)


def test_operational_workflow_docs_use_canonical_owners_and_evidence_boundaries() -> None:
    combined = "\n".join(_read(path) for path in OPERATIONAL_WORKFLOW_DOCUMENTS)

    for canonical_path in (
        "configs/hosts/gateway.yaml",
        "docs/002_host_gateway_setup.md",
        "docs/003_stm32_board_setup.md",
        "docs/005_remote_flash_workflow.md",
        "docs/006_security_and_secrets.md",
        "docs/007_framework_architecture.md",
        "experiment/mqtt-broker/README.md",
    ):
        assert canonical_path in combined

    for boundary in (
        "host-side",
        "broker-side",
        "UART",
        "ST67W61M1",
        "end-to-end wireless",
    ):
        assert boundary in combined


def test_operational_commands_use_docker_wrappers_by_default() -> None:
    gateway = _read("docs/002_host_gateway_setup.md")
    workflow = _read("docs/005_remote_flash_workflow.md")
    broker = _read("experiment/mqtt-broker/README.md")

    assert "Docker-wrapper" in workflow
    assert "diagnostic fallback only" in workflow
    assert ".\\scripts\\dev.ps1 experiment-gateway" in gateway
    assert ".\\scripts\\dev.ps1 experiment build-wolfboot" in workflow
    assert ".\\scripts\\dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py" in broker
    assert "Diagnostic fallback: local Docker smoke test" in broker
    assert "Diagnostic fallback: raw gateway-capable container execution" in broker


def test_operational_secure_boot_profiles_match_tracked_config_inventory() -> None:
    workflow = _read("docs/005_remote_flash_workflow.md")
    expected_stems = (
        "ecdsa_p256",
        "ecc384",
        "ecc521",
        "ed25519",
        "ed448",
        "rsa2048",
        "rsa3072",
        "rsa4096",
        "mldsa44",
        "mldsa65",
    )

    for stem in expected_stems:
        assert stem in workflow
        assert (REPO_ROOT / f"configs/builds/wolfboot_stm32l4_{stem}.yaml").is_file()
        assert (REPO_ROOT / f"configs/signing/wolfboot_{stem}_app.yaml").is_file()
        assert (REPO_ROOT / f"configs/experiments/wolfboot_{stem}_uart.yaml").is_file()
        assert (REPO_ROOT / f"configs/wolfboot/stm32l4r5_{stem}.config").is_file()

    assert "ML-DSA-87 is not a supported profile" in workflow


def test_operational_docs_preserve_generated_state_and_secret_safety() -> None:
    workflow = _read("docs/005_remote_flash_workflow.md").lower()
    security = _read("docs/006_security_and_secrets.md").lower()

    for content in (workflow, security):
        assert "generated-state preflight" in content
        assert "primary" in content
        assert "supplementary cross-platform hygiene" in content
        assert "keysclean" in content
        assert "do not" in content

    assert "partially missing tuple" in workflow
    assert "mismatched tuple" in workflow
    assert "must never copy private key material" in security
