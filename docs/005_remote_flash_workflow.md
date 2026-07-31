# Remote Flash Workflow

## Purpose

This document owns the current Docker-wrapper direct-flash, secure-boot, and UART workflows. Run commands from the repository root. Host-native Python, CMake, Make, SCP, SSH, and toolchain commands are diagnostic fallback only; they are not the normal reproducible validation path.

Gateway identity is owned by `configs/hosts/gateway.yaml` and explained in `docs/002_host_gateway_setup.md`. Board/ST-LINK/UART hardware identity is owned by `docs/003_stm32_board_setup.md`.

## Direct-flash workflow

Build through the Docker wrapper:

```powershell
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
```

Flash an explicitly recorded build:

```powershell
.\scripts\dev.ps1 experiment-gateway flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run <run_id>
```

The untracked-artifact escape hatch is limited to manual recovery or investigation:

```powershell
.\scripts\dev.ps1 experiment-gateway flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
```

Build and flash, with optional UART capture:

```powershell
.\scripts\dev.ps1 experiment-gateway build-flash --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment-gateway build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
```

Run the normal build/flash/UART baseline workflow:

```powershell
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
```

The `flash` path refuses SCP/SSH unless the artifact matches recorded build provenance or the explicit recovery escape hatch is supplied.

## Secure-boot workflow

Secure boot consumes the configured wolfBoot artifact and signed relocated application. The secure-boot workflow selects one canonical target and algorithm. The normal command pattern is:

```powershell
.\scripts\dev.ps1 experiment build-wolfboot --boot-algorithm <algorithm>
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml --configure-preset RelocatedDebug --build-preset RelocatedDebug --artifact build/RelocatedDebug/stm32_basic_hal1.elf
.\scripts\dev.ps1 experiment sign-application --boot-algorithm <algorithm>
.\scripts\dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml --boot-algorithm <algorithm> --repeat-count 5
```

Supported algorithm IDs are:

```text
Classical: ecdsa_p256, ecc384, ecc521, ed25519, ed448, rsa2048, rsa3072, rsa4096
ML-DSA:   mldsa44, mldsa65
```

ML-DSA-87 is not a supported profile under the current 8192-byte image-header reserve. `configs/targets/stm32l4r5_wolfboot.yaml` owns shared target configuration, `configs/algorithms/*.yaml` owns algorithm differences, `configs/experiments/secure_boot_uart.yaml` is the single secure-boot experiment entry point, and `configs/wolfboot/*.config` contains native wolfBoot build templates.

The relocated application build must run through the framework so generated-state provenance and the artifact hash are recorded before signing. `build-wolfboot`, `sign-application`, and `flash-secure-boot` use generated-state preflight as the primary compatibility, stale-output, and provenance mechanism.

The reusable signing tuple consists of the canonical private key, matching wolfBoot-local private key, generated public key, and generated `tools/wolfboot/src/keystore.c`:

- Completely absent tuple: the owning workflow may create it when the profile permits generation.
- Complete matching tuple: preserve and reuse it.
- Partially missing tuple: fail before build/signing; do not reconstruct members.
- Mismatched tuple: fail before build/signing; do not replace the canonical key or overwrite members.

Do not run wolfBoot `keysclean` or manually delete tuple members. Pytest startup cleanup is supplementary cross-platform hygiene only; it is not provenance validation and must not remove reusable signing state.

Negative corrupted-application test:

```powershell
.\scripts\dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml --boot-algorithm ecdsa_p256 --negative-corrupt-application
```

The workflow corrupts a result-local copy. It must not modify the canonical signed image or private key.

## UART capture

Direct-flash `flash` and `build-flash` capture UART only with `--capture-uart`; `run` captures UART after a successful flash. Secure-boot flashing captures UART unless `--skip-uart` is supplied. Repeated secure-boot samples are written as `uart_sample_001.log`, `uart_sample_002.log`, and so on.

Ad hoc bounded capture:

```powershell
.\scripts\dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
.\scripts\dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10 --restart
```

Monitor output is useful for diagnosis but has no result manifest and does not establish image provenance by itself.

## Broker boundary

Broker deployment and host-side MQTT/TLS checks are separate from firmware flashing. Use `experiment/mqtt-broker/README.md`. Broker/client success is `host_side` or broker-side evidence only and cannot be promoted to STM32, UART, Wi-Fi, ST67W61M1, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless evidence.

## Diagnostic fallback

Host-native commands may be used only to isolate a development-machine, CubeMX, IDE, toolchain, SSH, or gateway problem. They must not replace wrapper verification, bypass generated-state preflight, or use destructive signing-state cleanup. Manual SCP/SSH flash and direct `picocom` capture are recovery diagnostics documented by the host/gateway and board setup guides.

## Evidence rules

- Container build output proves compilation/linkage only.
- Flash success requires workflow SCP/SSH/helper evidence.
- Direct-flash runtime success requires expected UART markers from a provenance-backed run.
- Positive secure-boot success requires explicit secure-boot/application markers and result status.
- Timing, cycle, stack, heap, and benchmark values must come from explicit UART fields or manifests.
- Gateway reachability, broker status, host-client validation, and hardware/UART evidence are separate boundaries.


## ST67 T02 and secure-boot runtime validation

Use a UART capture of at least 30 seconds when validating ST67 networking.
A successful normal or secure-boot application run must show module
initialization, the normal scan-skipped marker, Wi-Fi association, DHCP
success, a live `lwIP runtime network:` marker with a non-zero IPv4 address,
and continued heartbeat output.

For secure-boot profiles, these application markers are required in addition
to the profile-specific wolfBoot verification and handoff evidence. Run the
existing secure-boot flash workflow and algorithm benchmark tests for the
maintained profile matrix; do not treat build or signing success alone as
runtime networking evidence.

## Signing-state initialization and clean builds

Before the first secure-boot build for an algorithm, ensure the configured
persistent tuple directory is either completely absent or complete. The
matching `build-wolfboot` profile atomically creates a new tuple when absent.

Deleting `build/` or generated files inside `tools/wolfboot/` does not rotate
the signing identity. The next build rematerializes the required wolfBoot files
from `secrets/wolfboot/tuples/<tuple-id>/`. Do not manually delete individual
files inside a persistent tuple.

## Locating failed pytest hardware and gateway evidence

Hardware, gateway, and integration pytest failures retain their partial evidence
under `results/automated-tests/<test-run-id>/`. Inspect `manifest.json` for the
failure stage and `pytest.log` for the ordered collection, setup, call, and
teardown records. Test-triggered build evidence is below the same run's
`builds/` directory. These test-only builds are diagnostic evidence and are not
normal reusable firmware builds.


## End-to-end MQTT experiments through wolfBoot

For MQTT experiments, use the normal `run` command and select the secure-boot
domain separately:

```powershell
.\scripts\dev.ps1 experiment-gateway run `
    --experiment configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml `
    --boot-mode wolfboot `
    --boot-algorithm ecdsa_p256
```

This path owns all prerequisites. It provisions experiment dependencies and
signing state, builds wolfBoot, builds the MQTT application with the relocated
preset, signs that exact application, prepares the broker, flashes both images,
captures UART, validates MQTT command/response behaviour, collects broker logs,
and stops the broker. Standalone secure-boot commands remain diagnostic and
benchmark entry points; they are not prerequisites for `run`.

The `--boot-algorithm` option applies only to wolfBoot signing and verification.
TLS key exchange and certificate/signature selections remain in the MQTT
experiment profile.
