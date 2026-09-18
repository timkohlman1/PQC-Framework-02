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
CANONICAL_DOCUMENTS = (
    "README.md",
    "AI_BUILD_GUIDE.md",
    "docs/README.md",
    "docs/001_ai_feature_request_workflow.md",
    "docs/007_framework_architecture.md",
    "docs/008_chatgpt_project_prompt.md",
    "docs/non_hardware_mqtt_tls_development_plan.md",
    "docs/pqc_iot_experiment_framework_plan.md",
    "experiment/mqtt-broker/README.md",
)
CANONICAL_MQTT_PLAN = "docs/non_hardware_mqtt_tls_development_plan.md"
PROHIBITED_UNSAFE_COMMANDS = (
    "make wolfboot_root=. keysclean",
    "remove-item -force .\\tools\\wolfboot\\wolfboot_signing_private_key.der",
    "remove-item -force .\\tools\\wolfboot\\wolfboot_signing_public_key.der",
    "remove-item -force .\\tools\\wolfboot\\src\\keystore.c",
    "remove-item -recurse -force .\\secrets\\wolfboot",
)
PROJECT_DOCUMENT_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(AI_BUILD_GUIDE\.md|README\.md|docs/[A-Za-z0-9_./-]+\.(?:md|txt))"
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _tracked_files() -> set[str]:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={REPO_ROOT}",
            "ls-files",
            "-z",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {
        path.decode("utf-8")
        for path in completed.stdout.split(b"\0")
        if path
    }


def test_required_canonical_documents_exist_and_are_tracked() -> None:
    tracked = _tracked_files()
    for path in CANONICAL_DOCUMENTS:
        assert path in tracked, f"Required canonical document is not tracked: {path}"
        assert (REPO_ROOT / path).is_file(), f"Required canonical document is missing: {path}"


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
    command_fragment = "experiment build --experiment"
    for path in ("README.md", "docs/005_remote_flash_workflow.md"):
        content = _read(path).lower()
        build_index = content.find(command_fragment)
        signing_index = content.find("experiment sign-application", build_index + 1)
        assert build_index >= 0, f"{path} is missing the framework-recorded relocated build"
        assert signing_index > build_index, f"{path} must show relocated build before signing"
        assert "release is the default" in content
        assert "relocateddebug" not in content

    guide = _read("AI_BUILD_GUIDE.md")
    assert "framework-recorded relocated application build before signing" in guide
    assert "docs/005_remote_flash_workflow.md" in guide

    architecture = _read("docs/007_framework_architecture.md").lower()
    assert "direct wrapped cmake remains a diagnostic fallback only" in architecture

MQTT_COMMAND_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/007_framework_architecture.md",
    "experiment/mqtt-broker/README.md",
)


def test_powershell_wolfmqtt_examples_use_named_client_argument_boundary() -> None:
    broker_readme = _read("experiment/mqtt-broker/README.md")
    architecture = _read("docs/007_framework_architecture.md")
    root_readme = _read("README.md")

    assert "--client-args '-h'" in broker_readme
    assert "'-p'" in broker_readme
    assert "'-t'" in broker_readme
    assert "PowerShell `--client-args` forwarding contract" in root_readme

    combined = "\n".join((broker_readme, architecture)).lower()
    assert "after `--client-args`" in combined
    assert "active powershell guidance does not use a standalone `--`" in combined
    assert "pass the selected upstream wolfmqtt client arguments after `--`" not in combined


def test_certificate_provisioning_docs_use_config_driven_one_time_workflow() -> None:
    broker_readme = _read("experiment/mqtt-broker/README.md")

    assert "python scripts/provision_certificates.py" in broker_readme
    assert "configs/tls_auth/" in broker_readme
    assert "secrets/certificates/<profile-id>/" in broker_readme
    assert "experiment execution never generates or renews certificates" in broker_readme
    assert "provision-certs --server-name" not in broker_readme

    for path in ("README.md", "AI_BUILD_GUIDE.md"):
        assert "experiment/mqtt-broker/README.md" in _read(path)


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
    assert "legacy transport-boundary self-test" in architecture
    assert "ST67W61M1 hardware-backed network backend | Driver and interface sources build in direct and relocated profiles | Association and DHCP-supported runtime" in architecture
    assert "stm32-st67-wifi-association-dhcp" in architecture
    assert "Hardware success requires both association and DHCP pass markers from the latest boot and a non-zero IPv4 address." in architecture
    assert "Real classical STM32 MQTT-over-TLS | Implemented | ST67/lwIP/wolfSSL/wolfMQTT runtime path implemented" in architecture
    assert "STM32-local wolfMQTT build/runtime integration and real wolfSSL transport/handshake integration" not in architecture

def test_readme_is_concise_and_routes_detail_to_canonical_owners() -> None:
    readme = _read("README.md")

    assert len(readme.splitlines()) <= 200
    for heading in (
        "## Current scope",
        "## Documentation",
        "## Default workflow",
        "## Secure-boot example",
        "## MQTT and broker orientation",
        "## Safety and evidence",
    ):
        assert heading in readme

    for owner in (
        "docs/README.md",
        "docs/005_remote_flash_workflow.md",
        "docs/006_security_and_secrets.md",
        "docs/007_framework_architecture.md",
        "experiment/mqtt-broker/README.md",
    ):
        assert owner in readme

    assert "## Containerised build/test/experiment environment" not in readme
    assert "## Benchmark collection" not in readme
    assert "### Phase" not in readme


def test_architecture_is_capability_oriented_not_phase_structured() -> None:
    architecture = _read("docs/007_framework_architecture.md")

    required_headings = (
        "## System capability overview",
        "## Architectural organization",
        "## Canonical current capability matrix",
        "## Build and generated-state architecture",
        "## Test architecture",
        "## Consolidated deferred-test register",
    )
    for heading in required_headings:
        assert heading in architecture
    assert not re.search(r"(?m)^#{2,4} Phase ", architecture)
    assert "docs/non_hardware_mqtt_tls_development_plan.md" in architecture
    assert "docs/pqc_iot_experiment_framework_plan.md" in architecture


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
        "wolfMQTT runtime smoke:",
        "FreeRTOS task-context smoke complete:",
        "\ntick\n",
    )

    positions = [representative.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
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
        "configs/gateways/pqc_gateway1.yaml",
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
    assert "python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py" in broker
    assert "Diagnostic fallback: local Docker smoke test" in broker
    assert "Diagnostic fallback: raw gateway-capable container execution" in broker


def test_operational_secure_boot_profiles_match_tracked_config_inventory() -> None:
    workflow = _read("docs/005_remote_flash_workflow.md")
    expected_stems = (
        "integrity_sha256",
        "ecdsa_p256",
        "ecdsa_p384",
        "ecdsa_p521",
        "ed25519",
        "ed448",
        "rsa2048",
        "rsa3072",
        "rsa4096",
        "mldsa44",
        "mldsa65",
        "mldsa87",
    )

    for stem in expected_stems:
        assert stem in workflow
        assert (REPO_ROOT / f"configs/secure_boot/{stem}.yaml").is_file()

    assert (REPO_ROOT / "configs/targets/stm32l4r5_wolfboot.yaml").is_file()
    assert (REPO_ROOT / "configs/campaigns/secure_boot.yaml").is_file()
    assert not (REPO_ROOT / "configs/builds").exists()
    assert not (REPO_ROOT / "configs/signing").exists()


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
    assert "disposable experiment cryptographic material" in security
    assert "may, however, be copied into the result directory" in security
    assert "ssh private keys" in security
    assert "production or externally managed certificates and keys" in security
    assert "must fail closed rather than be archived" in security


MASTER_PLAN = "docs/pqc_iot_experiment_framework_plan.md"
ARCHITECTURE = "docs/007_framework_architecture.md"
DEFERRED_REGISTER_FIELDS = (
    "ID",
    "Feature",
    "Missing test layer",
    "Reason",
    "Required capability or phase",
    "Intended test file",
    "Eventual verification command",
    "Status",
)


MQTT_PHASE_STATUS_FIELDS = (
    "Status",
    "Implemented evidence boundary",
    "Verification",
    "Remaining limitations",
    "Deferred tests",
    "Last reconciled",
)


def test_active_mqtt_plan_phases_have_complete_status_metadata() -> None:
    plan = _read(CANONICAL_MQTT_PLAN)
    phase_matches = list(re.finditer(r"(?m)^## (?:Deferred )?Phase M[^\n]+$", plan))
    assert phase_matches, "Canonical MQTT plan contains no phase headings"

    for index, match in enumerate(phase_matches):
        end = phase_matches[index + 1].start() if index + 1 < len(phase_matches) else len(plan)
        section = plan[match.start():end]
        heading = match.group(0)
        assert section.count("### Phase status") == 1, (
            f"{heading} must contain exactly one Phase status block"
        )
        status = section.split("### Phase status", maxsplit=1)[1]
        for field in MQTT_PHASE_STATUS_FIELDS:
            assert re.search(rf"(?m)^- \*\*{re.escape(field)}:\*\* \S", status), (
                f"{heading} is missing non-empty status metadata field: {field}"
            )


def test_historical_master_plan_has_lifecycle_notice() -> None:
    master = _read(MASTER_PLAN)
    opening = "\n".join(master.splitlines()[:8]).lower()
    assert "lifecycle classification: historical roadmap" in opening
    assert "not the canonical current implementation-status source" in opening
    assert re.search(r"last reconciled: \d{4}-\d{2}-\d{2}", opening)


def test_master_plan_is_historical_and_does_not_track_live_mqtt_checkboxes() -> None:
    master = _read(MASTER_PLAN)
    assert "Lifecycle classification: Historical roadmap" in master
    assert ARCHITECTURE in master

    mqtt_start = master.index("## Phase M —")
    mqtt_section = master[mqtt_start:]
    assert "Historical goals and pass criteria only" in mqtt_section
    assert not re.search(r"(?m)^- \[\[ xX\]\] ", mqtt_section), (
        "Historical master-plan MQTT content must not retain live status checkboxes"
    )


def test_architecture_has_one_structured_deferred_test_register() -> None:
    architecture = _read(ARCHITECTURE)
    assert architecture.count("## Consolidated deferred-test register") == 1
    assert "AI_BUILD_GUIDE.md" in architecture

    header = "| " + " | ".join(DEFERRED_REGISTER_FIELDS) + " |"
    assert header in architecture
    assert "## Deferred test coverage —" not in architecture
    assert "### Deferred test coverage" not in architecture
    assert "#### Deferred test coverage" not in architecture

    rows = re.findall(r"(?m)^\| (DTR-\d{3}) \|.*\|$", architecture)
    assert rows == [f"DTR-{index:03d}" for index in range(1, len(rows) + 1)]


def test_deferred_register_rows_have_all_required_values() -> None:
    architecture = _read(ARCHITECTURE)
    rows = [
        line for line in architecture.splitlines()
        if re.match(r"^\| DTR-\d{3} \|", line)
    ]
    assert rows

    expected_cells = len(DEFERRED_REGISTER_FIELDS)
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        assert len(cells) == expected_cells, f"Malformed deferred-test row: {row}"
        assert all(cells), f"Deferred-test row contains an empty required field: {row}"
        assert cells[5].startswith("`tests/"), f"Intended test file is not explicit: {row}"
        assert (
            "./scripts/dev.ps1" in cells[6]
            or "./scripts/dev.sh" in cells[6]
        ), f"Verification command is not explicit: {row}"

DOCUMENTATION_INDEX = "docs/README.md"
PROJECT_DOCUMENT_PATTERNS = (
    re.compile(r"^(?:README|AI_BUILD_GUIDE)\.md$"),
    re.compile(r"^docs/.*\.(?:md|txt)$"),
    re.compile(r"^experiment/mqtt-broker/(?:README\.md|config/oqs/README\.md)$"),
)
INDEXED_DOCUMENT_PATH = re.compile(r"(?m)^\| `([^`]+\.(?:md|txt))` \|")


def _submodule_roots() -> tuple[str, ...]:
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.is_file():
        return ()
    roots = re.findall(r"(?m)^\s*path\s*=\s*(\S+)\s*$", gitmodules.read_text(encoding="utf-8"))
    return tuple(f"{root.rstrip('/')}/" for root in roots)


def _is_project_owned_document(path: str) -> bool:
    if any(path.startswith(root) for root in _submodule_roots()):
        return False
    return any(pattern.fullmatch(path) for pattern in PROJECT_DOCUMENT_PATTERNS)


def _indexed_document_paths() -> list[str]:
    return INDEXED_DOCUMENT_PATH.findall(_read(DOCUMENTATION_INDEX))


def _documentation_index_rows() -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for line in _read(DOCUMENTATION_INDEX).splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5, f"Malformed documentation ownership row: {line}"
        path = cells[0].strip("`")
        rows.append((path, cells[1], cells[2], cells[3], cells[4]))
    return rows


def _active_project_owned_documents() -> list[str]:
    active: list[str] = []
    for path, classification, lifecycle, _owner, _audience in _documentation_index_rows():
        metadata = f"{classification} {lifecycle}".lower()
        if (
            "historical" in metadata
            or "decision record" in metadata
            or "plan" in metadata
        ):
            continue
        active.append(path)
    return active


def test_documentation_index_covers_every_tracked_project_owned_document() -> None:
    tracked = _tracked_files()
    expected = sorted(path for path in tracked if _is_project_owned_document(path))
    indexed = _indexed_document_paths()

    assert indexed == sorted(indexed), "Documentation index paths must be sorted"
    assert len(indexed) == len(set(indexed)), "Documentation index contains duplicate paths"
    assert indexed == expected, (
        "Project-owned documentation index coverage mismatch. "
        f"Missing: {sorted(set(expected) - set(indexed))}; "
        f"unexpected: {sorted(set(indexed) - set(expected))}"
    )


def test_every_indexed_document_exists_and_is_tracked() -> None:
    tracked = _tracked_files()
    for path in _indexed_document_paths():
        assert (REPO_ROOT / path).is_file(), f"Indexed documentation file is missing: {path}"
        assert path in tracked, f"Indexed documentation file is not tracked: {path}"


def test_documentation_index_records_complete_ownership_metadata() -> None:
    content = _read(DOCUMENTATION_INDEX)
    header = (
        "| Path | Classification | Lifecycle | Canonical subject ownership | "
        "Intended audience |"
    )
    assert header in content

    rows = _documentation_index_rows()
    assert rows
    for row in rows:
        assert all(row), f"Documentation ownership row has an empty field: {row}"


def test_active_project_docs_reject_unsafe_wolfboot_cleanup_commands() -> None:
    for path in _active_project_owned_documents():
        content = _read(path).lower()
        for command in PROHIBITED_UNSAFE_COMMANDS:
            assert command not in content, (
                f"Unsafe signing-state cleanup command found in {path}: {command}"
            )


def test_canonical_mqtt_plan_path_is_used_consistently() -> None:
    tracked = _tracked_files()
    assert CANONICAL_MQTT_PLAN in tracked
    assert CANONICAL_MQTT_PLAN in _indexed_document_paths()

    for source in (DOCUMENTATION_INDEX, ARCHITECTURE):
        assert CANONICAL_MQTT_PLAN in _read(source), (
            f"{source} must route MQTT roadmap status to {CANONICAL_MQTT_PLAN}"
        )

    stale_paths = (
        "non_hardware_mqtt_tls_development_plan.md",
        "docs/mqtt_tls_development_plan.md",
    )
    for source in ACTIVE_AI_DOCUMENTS + (ARCHITECTURE, MASTER_PLAN):
        content = _read(source)
        for stale in stale_paths:
            if stale == "non_hardware_mqtt_tls_development_plan.md":
                content = content.replace(CANONICAL_MQTT_PLAN, "")
            assert stale not in content, f"{source} references non-canonical MQTT plan path: {stale}"


def test_vendor_and_submodule_documentation_is_excluded_from_project_ownership() -> None:
    content = _read(DOCUMENTATION_INDEX)
    indexed = _indexed_document_paths()

    assert "vendor or submodule trees is upstream-owned" in content
    for root in _submodule_roots():
        assert f"`{root}`" in content
        assert not any(path.startswith(root) for path in indexed)

    assert not any(path.startswith("Drivers/") for path in indexed)
    assert not any(path.startswith("Middlewares/Third_Party/") for path in indexed)


def test_root_entry_documents_link_to_documentation_index() -> None:
    for path in ("README.md", "AI_BUILD_GUIDE.md"):
        content = _read(path)
        assert DOCUMENTATION_INDEX in content, f"{path} must link to {DOCUMENTATION_INDEX}"


def test_ai_build_guide_is_compact_and_routes_detail_to_canonical_owners() -> None:
    guide = _read("AI_BUILD_GUIDE.md")

    required_headings = (
        "## 1. Purpose and authority",
        "## 2. Canonical documentation routing",
        "## 3. Project and capability boundaries",
        "## 4. Repository navigation and ownership",
        "## 5. Default workflow model",
        "## 6. Generated state, signing state, and provenance",
        "## 7. Evidence and result rules",
        "## 8. Testing requirements",
        "## 9. Secrets and generated artifacts",
        "## 10. AI-assisted implementation and review workflow",
        "## 11. Replacement artifact delivery",
        "## 12. Documentation maintenance rules",
    )
    for heading in required_headings:
        assert heading in guide, f"AI build guide is missing required section: {heading}"

    for canonical_path in (
        "docs/README.md",
        "docs/001_ai_feature_request_workflow.md",
        "docs/002_host_gateway_setup.md",
        "docs/003_stm32_board_setup.md",
        "docs/004_baseline_hal_app.md",
        "docs/005_remote_flash_workflow.md",
        "docs/006_security_and_secrets.md",
        "docs/007_framework_architecture.md",
        "docs/008_chatgpt_project_prompt.md",
        "docs/pqc_iot_experiment_framework_plan.md",
        "experiment/mqtt-broker/README.md",
    ):
        assert canonical_path in guide, f"AI build guide is missing canonical link: {canonical_path}"

    assert len(guide.splitlines()) <= 275
    assert "Phase M" not in guide
    assert "Gateway SSH alias:" not in guide
    assert "ST-LINK serial:" not in guide
    assert "Core/Src/pqc_" not in guide
    assert "tests/unit/test_artifacts.py" not in guide


def test_ai_build_guide_preserves_mandatory_workflow_and_safety_rules() -> None:
    guide = _read("AI_BUILD_GUIDE.md")
    required_phrases = (
        "Do not rely on prior chats, prior uploads, memory, or inferred repository state.",
        "Do not move CubeMX-generated folders unless explicitly requested.",
        "Do not implement a future or deferred capability early",
        "Do not claim hardware, gateway, flashing, UART, runtime, timing, memory, benchmark",
        "Do not implement code until the required context is available.",
        "complete matching tuple",
        "partially missing tuple",
        "mismatched tuple",
        "Never silently reconstruct tuple members",
        "supplementary cross-platform hygiene",
        "consolidated deferred-test register",
        "Provide complete replacement content",
        "Expand-Archive -LiteralPath",
    )
    for phrase in required_phrases:
        assert phrase in guide, f"AI build guide lost mandatory rule: {phrase}"

def test_st67_transport_documentation_matches_vendor_aligned_runtime_baseline() -> None:
    board = _read("docs/003_stm32_board_setup.md")
    baseline = _read("docs/004_baseline_hal_app.md")
    architecture = _read("docs/007_framework_architecture.md")
    combined = "\n".join((board, baseline, architecture))

    assert "SPI_BAUDRATEPRESCALER_4" in baseline
    assert "SPI1 uses prescaler 4" in architecture
    assert "approximately 30 Mbit/s" in combined
    assert "vendor `spi_iface.c` implementation" in combined
    assert "each segment in a chained lwIP `pbuf`" in combined
    assert "30-second" in combined

def test_wolfssl_dependency_ownership_is_explicit_and_consistent() -> None:
    guide = _read("AI_BUILD_GUIDE.md")
    architecture = _read("docs/007_framework_architecture.md")
    readme = _read("README.md")

    for document in (guide, architecture, readme):
        assert "Middlewares/Third_Party/wolfSSL" in document
        assert "tools/wolfboot/lib/wolfssl" in document

    assert "Application TLS/wolfCrypt source of truth" in architecture
    assert "wolfBoot-owned nested wolfSSL dependency" in architecture
    assert "PQC_WOLFSSL_SOURCE_DIR" in architecture
    assert "commit and push the wolfSSL source change" in architecture

    assert "Application TLS/wolfCrypt changes must target `Middlewares/Third_Party/wolfSSL`" in guide
    assert "Do not modify `tools/wolfboot/lib/wolfssl` for application TLS functionality" in guide
    assert "parent-repository commit alone does not preserve dirty wolfSSL working-tree changes" in guide

    assert "Application TLS/wolfCrypt builds use the top-level `Middlewares/Third_Party/wolfSSL` submodule" in readme



def test_hardware_test_standard_is_self_contained() -> None:
    guide = _read("AI_BUILD_GUIDE.md")
    workflow = _read("docs/001_ai_feature_request_workflow.md")
    architecture = _read("docs/007_framework_architecture.md")
    flash = _read("docs/005_remote_flash_workflow.md")

    assert "Hardware tests must be self-contained by default" in guide
    assert "Hardware-test design standard" in workflow
    assert "Hardware tests are self-contained by default" in architecture
    assert "pre-generated campaigns" in workflow
    assert "test-specific environment variables" in workflow
    assert "Automated hardware tests" in flash
    assert "test_application_timebase_hw.py" in flash
    assert "PQC_TIMEBASE_UART_LOG" not in architecture.split("| DTR-015 |", 1)[1].splitlines()[0]
