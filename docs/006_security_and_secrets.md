# Security and Secrets

## Purpose

This document defines what may and may not be committed to this repository.

## Never commit

Do not commit:

- SSH private keys
- VPN private keys
- TLS private keys
- MQTT passwords
- real `.env` files
- private client certificates or key bundles
- private firmware signing keys
- private wolfBoot signing keys
- production credentials
- generated local signing keys under `secrets/wolfboot/`
- generated wolfBoot working-tree signing keys such as `tools/wolfboot/wolfboot_signing_private_key.der`

## Usually safe to commit

These may be committed if clearly non-secret:

- documentation
- example configuration files without real credentials
- public CA certificates
- public test certificates
- dummy credentials used only for examples
- project-local wolfBoot `.config` templates under `configs/wolfboot/`

## Local signing-key handling

The secure-boot signing workflows use local private keys under `secrets/wolfboot/` and a wolfBoot working-tree key path under `tools/wolfboot/` for the active build profile. These files are generated/local state and must remain ignored by Git.

Build and signing manifests may record non-secret SHA-256 key fingerprints to prove key consistency. They must not copy private key material into result directories, replacement ZIPs, documentation, or commits.

`flash-secure-boot` refuses hardware flashing when available canonical and wolfBoot working-tree private-key fingerprints differ. This prevents flashing a bootloader and application signed with inconsistent key material.

The reusable wolfBoot signing tuple contains the canonical private key, the matching wolfBoot-local private key, the generated public key, and generated `tools/wolfboot/src/keystore.c`. A completely absent tuple may be created only by the owning workflow when profile configuration permits local generation. A complete matching tuple is preserved and reused. Partial state or any fingerprint mismatch must fail safely before build or signing. Existing canonical private keys must not be silently replaced, and missing public-key or keystore members must not be silently reconstructed from partial state.

Generated-state preflight is the primary mechanism for validating build/signing compatibility, artifact hashes, and provenance. Pytest session-start cleanup is supplementary cross-platform hygiene only; it must not remove canonical keys or reusable signing-tuple members and must not be treated as signing-state validation.


## Containerised workflow secret handling

Container images and container build contexts must not contain private keys, credential files, generated signing material, real `.env` files, private certificates, or production credentials. The repository `.dockerignore` excludes generated outputs, `secrets/`, local environment files, wolfBoot generated key material, and MQTT broker runtime material from container build contexts.

The container image is the default runtime for Python validation, STM32 direct and relocated builds, wolfBoot builds, relocated application signing, pytest, gateway checks, and gateway-mediated hardware experiments. Signing material for containerised secure-boot workflows must come from the runtime-mounted workspace or locally generated files such as `secrets/wolfboot/<profile>_private_key.der`; it must remain outside the image, outside Git, and outside replacement artifacts. The image may contain client tools such as OpenSSH and OpenSSL, but it must not contain SSH keys, VPN keys, broker credentials, private certificates, private signing keys, real `.env` files, or generated signing material.

This applies to secure-boot signing material, wolfBoot working-tree signing keys, SSH access for any optional gateway-capable workflow, VPN profiles, MQTT broker credentials, TLS private keys, and certificate authority private material. Documentation may describe required mount points or local preparation steps, but must not include real secret values or ask for secret material to be committed.

Gateway-capable and hardware container workflows are still explicit, capability-gated, and supplied with SSH access at runtime only. Inside the container, gateway checks require `PQC_CONTAINER_ENABLE_GATEWAY=1` and runtime-mounted SSH configuration, known-hosts data, and credentials. The default wrapper commands for gateway and hardware workflows set that flag and mount SSH material read-only for the duration of one container run. Without that explicit enablement, gateway tests skip or fail according to the existing pytest strict flag.


### Container gateway SSH access

Gateway-capable container checks must use runtime-provided SSH material only. The default PowerShell wrapper mounts the workspace and a local SSH directory read-only:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

Do not copy SSH private keys, VPN profiles, broker credentials, TLS private keys, private certificates, private signing keys, or real `.env` files into the repository or the image. Keep known-hosts data and SSH configuration local to the runtime environment.

## CI secret handling

The GitHub Actions workflow preserves the existing runner-compatible jobs and MQTT broker Docker runtime validation as compatibility coverage, and uses the containerised non-hardware job as the default reproducible software-build validation path. The containerised job must not require repository, organization, or environment secrets. It must not mount SSH keys, VPN keys, broker credentials, TLS private keys, private certificates, private signing keys, real `.env` files, or production credentials. Signing material generated during CI is local runner workspace state only and must remain ignored by Git and excluded from container images.

The existing MQTT broker Docker runtime job uses temporary local test certificates generated for the CI run; it must not use production broker credentials, private certificates, real `.env` files, or committed secrets. Gateway, hardware, Wi-Fi-module, or other secret-dependent CI workflows must be separate opt-in workflows if they are added later, and must preserve the same no-committed-secrets rule.

## Generated outputs to keep out of Git

```text
build/
results/*
!results/.gitkeep
.last_successful_build.json
.build_number
*.elf
*.bin
*.hex
*.map
*.list
*.su
__pycache__/
.pytest_cache/
tools/wolfboot/.config
tools/wolfboot/wolfboot.elf
tools/wolfboot/wolfboot.bin
tools/wolfboot/wolfboot_signing_private_key.der
secrets/wolfboot/
```

## Gateway SSH access

Each development PC should generate its own SSH keypair for gateway access. The private key remains local. Only the public key should be installed on `pqc-gateway1`.

Use the SSH alias:

```text
pqc-gateway1
```

Do not hard-code private key paths into framework code or documentation.

## VPN and future transport secrets

If VPN, MQTT, TLS, or broker access is required in later phases, document the requirement without committing private profiles, private keys, passwords, tokens, or production certificates.

## MQTT broker TLS material

The MQTT broker compose project uses generated local TLS material under `experiment/mqtt-broker/runtime/`. That directory is ignored by Git and must remain local or be copied only to the intended gateway host during deployment.

Do not commit MQTT broker private keys, client private keys, password files, real `.env` files, production certificates, or private CA material. The committed files are limited to compose files, Mosquitto configuration templates, documentation, tests, and scripts.

## STM32 wolfSSL build-only boundary

The Phase M6 STM32 wolfSSL boundary is build-only. It may compile project-owned wolfSSL preparation code and non-secret configuration/status strings, but it must not embed private keys, MQTT passwords, real `.env` values, private certificates, private CA material, production certificates, or bearer tokens. Certificate handling in this phase is limited to future path/reference configuration; no certificate store is configured and no private key material is compiled into firmware.

Do not treat a successful Phase M6 firmware build as TLS runtime evidence. TLS handshake, certificate validation, MQTT connect, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end network success require explicit later logs, manifests, UART output, broker output, or equivalent evidence.


The classical profile uses local test X.509 certificates for TLS development. The OQS profile is experimental and uses Open Quantum Safe tooling or images for PQC TLS evaluation; it must not be treated as production TLS infrastructure.


## Phase M6 wolfSSL source-build smoke

The Phase M6 wolfSSL smoke path builds a minimal wolfCrypt SHA-256 source target from `tools/wolfboot/lib/wolfssl` and runs it over a fixed non-secret test message. This path must not embed private keys, CA private keys, client keys, broker credentials, MQTT passwords, real `.env` files, private certificates, or production TLS material. The UART marker may report source-build and SHA-256 smoke status only; it must continue to mark certificate loading, compiled-in secrets, runtime transport, TLS handshake, MQTT, Wi-Fi, and end-to-end network success as unavailable until later evidence-backed phases implement them.
