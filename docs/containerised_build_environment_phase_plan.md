# Containerised Non-Hardware Build Environment Phase Plan

## Purpose

This plan defines a staged containerisation path for the PQC IoT Experiment Framework. The goal is to make non-hardware development workflows portable across suitable hosts, reducing dependence on a specific Windows build server before the MQTT/lwIP/wolfSSL/wolfMQTT work expands the dependency surface.

Each sub-phase is intentionally scoped as a small AI-driven change request.

## Scope Principles

- Containerise non-hardware workflows first.
- Preserve the existing host/gateway/hardware model.
- Keep hardware flashing and UART capture optional.
- Do not require direct USB/ST-LINK passthrough for the initial container work.
- Do not bake secrets, SSH keys, VPN keys, TLS private keys, MQTT passwords, `.env` files, private certificates, or signing keys into images.
- Use runtime mounts only for local secrets and generated signing material where needed.
- Keep generated outputs out of Git.
- Keep the current Windows workflow valid until the container workflow is proven.
- Do not alter secure-boot semantics, flash layout, UART marker semantics, benchmark schema, or existing experiment behavior unless explicitly required by a scoped sub-phase.

---

## Phase C1 — Containerisation Plan and Documentation

### Goal

Add a clear, repository-aligned containerisation plan before introducing Docker or container runtime files.

### Outcomes

- The project documentation identifies containerisation as a non-hardware portability phase.
- Supported and unsupported workflows are explicit.
- Secret-handling rules are documented.
- Generated-output rules are documented.
- Hardware, gateway, UART, and Wi-Fi-module workflows remain optional and separate.
- The container plan is positioned before MQTT/lwIP/wolfSSL/wolfMQTT implementation work.
- The phase does not implement Docker files.

### Expected Evidence

- Updated planning documentation.
- Updated architecture or security documentation only where needed.
- No runtime, hardware, gateway, or MQTT/TLS success claims.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Add a containerised non-hardware build/test environment phase to the project documentation before MQTT/lwIP/wolfSSL/wolfMQTT implementation work. The phase must focus on goals and outcomes, not prescribe implementation details. It must cover Python tests, framework scripts, STM32 direct and relocated builds, wolfBoot builds, application signing with runtime-mounted local secrets only, and optional later gateway integration. Do not implement Docker files yet.

```

### Pass Criteria

- Documentation clearly defines the containerisation phase.
- Existing hardware workflows are not made mandatory in the container.
- Secret-handling constraints are preserved.
- No Docker implementation is included in this phase.

---

## Phase C2 — Python-Only Container Baseline

### Goal

Create the smallest useful container workflow for Python framework development.

### Outcomes

- A project-owned container definition exists for Python-only framework validation.
- Unit tests can run inside the container.
- Framework commands that do not require hardware, SSH, UART, STM32 toolchains, or broker access can run inside the container.
- The workflow is documented for a fresh checkout.
- Generated test/cache output remains outside Git.

### Expected Evidence

- Container image builds.
- Unit tests pass inside the container.
- At least one non-hardware framework command runs inside the container.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement the first containerisation sub-phase: a Python-only non-hardware container baseline. It should support Python dependencies, unit tests, and framework commands that do not require STM32 toolchains, gateway access, SSH, UART, broker access, or hardware. Focus on outcomes and repository alignment. Do not add STM32 build toolchain support yet.

```

### Pass Criteria

- Python unit tests pass in the container.
- Non-hardware framework commands run in the container.
- No STM32 build, wolfBoot build, signing, gateway, UART, broker, or hardware capability is required.

---

## Phase C3 — STM32 Build Container

### Goal

Extend the container to support non-hardware STM32 firmware builds.

### Outcomes

- The container can configure and build the direct-flash firmware profile.
- The container can configure and build the relocated firmware profile.
- Local-build integration tests can run inside the container when explicitly requested.
- Build outputs remain generated artifacts and are not committed.
- The workflow remains independent of STM32 board access, ST-LINK, UART, gateway, and Wi-Fi hardware.

### Expected Evidence

- Direct firmware build succeeds inside the container.
- Relocated firmware build succeeds inside the container.
- Local build integration tests pass inside the container when strict local-build capability is requested.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Extend the containerised non-hardware environment to support STM32 local builds. It should support the existing direct-flash and relocated CMake build workflows and the relevant local-build integration tests. Do not add wolfBoot build/signing support, gateway access, UART capture, direct USB/ST-LINK access, Wi-Fi module access, or hardware tests in this sub-phase.

```

### Verification Commands

The implementation should provide exact container commands, but the expected in-container validation should cover:

```powershell
cmake --preset Debug
cmake --build --preset Debug
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python -m pytest tests/integration -m integration --pqc-require-local-build
```

### Pass Criteria

- Direct-flash firmware build works in the container.
- Relocated firmware build works in the container.
- No flashing, UART capture, gateway access, or Wi-Fi module is required.

---

## Phase C4 — wolfBoot Build and Application Signing Container Support

### Goal

Extend the container to support secure-boot build and signing workflows without committing or baking secret material into the image.

### Outcomes

- wolfBoot build workflows can run inside the container.
- Relocated application signing workflows can run inside the container.
- Any required signing material is generated locally or mounted at runtime.
- Private keys and generated signing material remain uncommitted and outside the image.
- Secure-boot hardware flashing remains outside this sub-phase.

### Expected Evidence

- wolfBoot build command succeeds inside the container.
- Relocated application signing command succeeds inside the container.
- Generated signing material is not committed or baked into the image.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Extend the containerised non-hardware environment to support wolfBoot build and application signing workflows. The solution must preserve the repository's secrets policy: private signing keys and generated signing material must not be committed or baked into the image. Use runtime-mounted or locally generated material only. Do not add hardware flashing, UART capture, gateway access, or Wi-Fi module support in this sub-phase.

```

### Verification Commands

The implementation should provide exact container commands, but the expected in-container validation should cover at least one known-good profile:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

### Pass Criteria

- wolfBoot builds inside the container.
- Relocated application signing works inside the container.
- Secret-handling documentation remains accurate.
- No secure-boot flashing or UART success is claimed.

---

## Phase C5 — Optional Gateway-Capable Container Integration

### Goal

Allow opt-in gateway-dependent integration workflows from the container without making them part of the default container pass criteria.

### Outcomes

- Gateway-capable workflows can run from the container when explicitly enabled.
- SSH access, known-hosts data, and credentials are provided at runtime only.
- The image does not contain private SSH keys, VPN keys, broker credentials, certificates, or private signing keys.
- Hardware and gateway tests remain capability-gated.
- Default container workflow remains non-hardware.

### Expected Evidence

- Gateway integration tests can run when the gateway capability is explicitly supplied.
- The same tests skip or remain unavailable when the capability is not supplied.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Add optional gateway-capable integration support to the container workflow. Gateway access must be explicitly enabled and must use runtime-provided SSH access only. The container image must not contain SSH keys, VPN keys, broker credentials, private certificates, private signing keys, or other secrets. Hardware, gateway, UART, and broker tests must remain capability-gated and must not run by default.

```

### Verification Commands

The implementation should provide exact container commands, but expected capability-gated validations include:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```

### Pass Criteria

- Gateway workflows are opt-in.
- No credentials are committed or baked into the image.
- Tests skip cleanly without gateway capability.
- No hardware, flashing, UART, broker, or MQTT/TLS success is claimed without explicit logs.

---

## Phase C6 — Optional CI Integration

### Goal

Use the container as a reproducible non-hardware CI baseline after local container workflows are stable.

### Outcomes

- CI can build or reuse the project container image.
- CI can run Python unit tests.
- CI can run non-hardware build checks where toolchain availability permits.
- Hardware, gateway, UART, and Wi-Fi-module tests remain excluded from the default CI path.
- CI does not contain committed or baked secrets.

### Expected Evidence

- CI job completes for non-hardware checks.
- CI logs distinguish skipped hardware/gateway workflows from failed non-hardware workflows.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Add optional CI support for the containerised non-hardware workflow. CI should run the reproducible Python and non-hardware build checks already supported by the local container workflow. It must not run hardware, gateway, UART, broker, Wi-Fi-module, or secret-dependent workflows by default. Do not add or require secrets in CI.

```

### Pass Criteria

- CI validates the containerised non-hardware baseline.
- Hardware/gateway tests are not run by default.
- No secrets are committed, printed, or baked into images.

---

## Overall Completion Criteria

The containerised non-hardware build environment is complete when:

- A developer can run documented non-hardware workflows from a fresh checkout on a supported host.
- Python unit tests run inside the container.
- STM32 direct and relocated builds run inside the container.
- wolfBoot build and signing workflows run inside the container without committed or baked secrets.
- Hardware, gateway, UART, Wi-Fi-module, and broker workflows remain optional and capability-gated.
- Documentation clearly distinguishes portable build/test evidence from hardware/runtime evidence.
