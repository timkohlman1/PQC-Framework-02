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


## Containerised workflow secret handling

Container images and container build contexts must not contain private keys, credential files, generated signing material, real `.env` files, private certificates, or production credentials. The repository `.dockerignore` excludes generated outputs, `secrets/`, local environment files, wolfBoot generated key material, and MQTT broker runtime material from container build contexts.

The Phase C2 Python-only image does not require local secret material and must not be used for signing, SSH/gateway access, UART capture, broker validation, or hardware workflows. Containerised workflows in later phases that need local secret material must receive it through explicit runtime mounts or locally generated files that remain outside the image, outside Git, and outside replacement artifacts.

This applies to secure-boot signing material, wolfBoot working-tree signing keys, SSH access for any optional gateway-capable workflow, VPN profiles, MQTT broker credentials, TLS private keys, and certificate authority private material. Documentation may describe required mount points or local preparation steps, but must not include real secret values or ask for secret material to be committed.

The default containerisation path remains non-hardware. Any later gateway-capable container workflow must remain opt-in, capability-gated, and supplied with SSH access at runtime only.

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

The classical profile uses local test X.509 certificates for TLS development. The OQS profile is experimental and uses Open Quantum Safe tooling or images for PQC TLS evaluation; it must not be treated as production TLS infrastructure.
