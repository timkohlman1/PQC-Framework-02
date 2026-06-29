# Security and Secrets

## Purpose

This document defines what may and may not be committed to this repository.

## Never Commit

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

## Usually Safe to Commit

These may be committed if they are non-secret and clearly identified:

- public CA certificates
- example configuration files
- documentation
- public test certificates
- dummy credentials used only for examples

## SSH Access

Each development PC should generate its own SSH keypair.

The private key remains local.

Only the public key is copied to the experiment gateway.

## TLS Certificates

Public CA certificates may be stored in the repository if required for TLS validation.

Client private keys must not be stored in the repository.

## Signing Keys

Future firmware signing private keys must be treated as secrets and kept outside the repository.

## VPN Access

VPN configuration and VPN private keys must not be committed.

Document VPN requirements, but keep credentials local.


## wolfBoot Target Assessment and Keys

Phase 10c documents target-support suitability only. It does not generate signing keys, does not add test keys, and does not add a signing workflow.

When later wolfBoot signing phases are implemented, private wolfBoot signing keys must remain outside the repository. Only public verification material, dummy/example keys clearly marked as non-secret, or documentation may be committed.

## Phase 10d Flash Layout and Secrets

Phase 10d defines a planned secure-boot flash layout only.

It does not generate signing keys, does not add test keys, does not add private certificates, does not sign firmware images, and does not add a signing workflow.

The planned layout metadata and documentation are safe to commit because they contain only addresses, sizes, status fields, and decision references. Private wolfBoot signing keys must still remain outside the repository in later signing phases.

## Phase 10f.1 wolfBoot Build Adaptation

The repository may track the project-local wolfBoot build configuration template at `configs/wolfboot/stm32l4r5_ecdsa_p256.config` because it contains target addresses, build flags, and include paths only. It must not contain private signing keys, private certificates, passwords, or production credentials.

The generated copy at `tools/wolfboot/.config`, wolfBoot build outputs, and any local signing-key by-products under `tools/wolfboot` remain local generated state and must not be committed. Phase 10f.1 does not introduce an application image-signing workflow and does not create durable project signing keys.


## Phase 10g Application Signing Keys

Phase 10g introduces a local signing workflow for the relocated application image through:

```powershell
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

The default signing profile expects the ECDSA-P256 private key at:

```text
secrets/wolfboot/ecdsa_p256_private_key.der
```

That private key is local developer state. It must not be committed, uploaded in AI context archives, copied into replacement artifacts, or copied into `results/`. The framework records the private-key path and whether the key existed or was generated, but it does not record a private-key hash and does not copy private key material into signing evidence directories.

The default workflow may convert the relocated ELF into the configured BIN input before signing and may generate the local key when it is absent by invoking the configured wolfBoot key-generation command from `tools/wolfboot`. That working directory is required because wolfBoot keygen writes `src/keystore.c` relative to the wolfBoot source tree. The generated private key remains under `secrets/wolfboot/`, which is ignored by Git. Signed images and signing evidence are generated outputs and must not be treated as source files.

Phase 10g still does not flash wolfBoot or a signed application and does not provide UART boot evidence. Hardware success must not be claimed from signing evidence alone.


## Phase 10h — Flash wolfBoot and Signed Application

The Phase 10h workflow flashes two generated artifacts: the locally built `tools/wolfboot/wolfboot.elf` bootloader and the locally signed `build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin` application image. The workflow records artifact hashes, flash offsets, gateway return codes, and UART evidence in `results/`.

Private wolfBoot signing keys remain under `secrets/wolfboot/` and must not be committed or copied into result artifacts. The flash workflow reads only generated public artifacts and does not copy private key material.

A successful flash command is not, by itself, proof of wolfBoot-mediated boot. Boot confirmation must come from the recorded UART log. Phase 10i records the distinct secure-boot application marker `stm32-basic_hal1 secure-boot app v0.1.0` and requires it for positive boot evidence.

## Phase 10j — Corrupted-Application Negative Test

The negative-test workflow uses a result-local corrupted copy of the signed application image. It does not modify the original signed image under `build/`, does not modify or copy the private key under `secrets/wolfboot/`, and does not generate new signing material.

The command is:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
```

The manifest records the original signed-image SHA-256, corrupted-image SHA-256, corruption method, corrupted result-local path, and `source_image_modified: false`. Do not commit corrupted images, result directories, private keys, or generated signing outputs.
