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


## Phase 10l — Consolidated Secure-Boot Evidence

Phase 10l adds consolidated manifest evidence only. It does not add new private-key material, public certificates, credentials, or production secrets.

Secure-boot run manifests may record local artifact paths, SHA-256 hashes, signature algorithm, `signature_size`, UART evidence, and boot-timing values. These are experiment evidence, not secrets. Private signing keys remain under `secrets/wolfboot/`, are not copied into `results/`, and must not be uploaded in AI context archives or committed.

The following generated or local-only paths must remain ignored:

```text
results/*
.last_successful_build.json
secrets/
secrets/wolfboot/
build/**/*_signed.bin
build/**/*_v*_signed.bin
tools/wolfboot/.config
tools/wolfboot/**/*.elf
tools/wolfboot/**/*.bin
tools/wolfboot/*.der
tools/wolfboot/*.pem
```

A consolidated manifest is not sufficient by itself to claim hardware success. Secure-boot success, negative-test success, and timing values must still be supported by user-provided `secure_boot_flash.log`, `uart.log`, and `manifest.json` evidence from the actual run.

## Phase 11.1 Benchmark Evidence and Secret Handling

The Phase 11.1 benchmark result model records artifact paths, hashes, sizes when available, runtime verification evidence, unavailable-metric reasons, and future repeated-run or aggregate placeholders. It must not copy private signing keys, private certificates, passwords, SSH private keys, or other local credentials into result manifests or replacement artifacts.

Private wolfBoot signing keys remain local under ignored paths such as `secrets/wolfboot/`. Benchmark manifests may identify the signing algorithm and signature size, but they must not embed private key material.

## Phase 11.3 Static Metrics and Secret Handling

Phase 11.3 records static build/resource metrics from local wolfBoot and application artifacts only. It must not copy private signing keys, private certificates, credentials, or other secret material into result directories. The unsigned and signed application size metrics are file-size evidence only; they do not require exposing or retaining signing keys.

Runtime stack and heap metrics remain unavailable unless a later phase adds explicit firmware-side measurement evidence. Host-side timing, UART capture duration, reset delay, build logs, and ELF section sizes must not be used to claim runtime stack or heap usage.

## Secure-Boot Signing-Key Consistency

The ECDSA-P256 secure-boot profile uses one canonical local private key path: `secrets/wolfboot/ecdsa_p256_private_key.der`. The wolfBoot build workflow coordinates that key with wolfBoot's local key file at `tools/wolfboot/wolfboot_signing_private_key.der` so the bootloader keystore and the signed application are generated from matching key material.

The framework may record SHA-256 fingerprints of local signing-key files in generated manifests and logs as non-secret consistency evidence. It must not copy private key material into `results/`, replacement artifacts, documentation, or Git. Generated key files remain local developer state and must stay ignored by Git.

Before hardware flashing, `flash-secure-boot` checks configured local key fingerprints when both key files are available. If the wolfBoot private key and application-signing private key differ, the command fails before SCP, SSH, or flash-helper execution.



## Phase 11.5a Profile Model and Keys

The Phase 11.5a classical profile model is metadata only. It records the ECC256 reference profile and reserves ED25519 and RSA2048 for later sub-phases, but it does not add new private keys, new signing commands, or new runnable non-ECC256 profiles.

Private signing keys remain local generated state and must not be committed or copied into result artifacts. ED25519 and RSA2048 key material must not be introduced until the corresponding implementation sub-phase defines the local-only key-generation and signing workflow.

## Phase 11.5b ED25519 signing-key handling

The ED25519 benchmark profile uses a canonical local private key at `secrets/wolfboot/ed25519_private_key.der`. The wolfBoot build workflow uses the working-tree private-key path `tools/wolfboot/wolfboot_signing_private_key.der` while generating the local keystore. Both paths are local developer state and must remain ignored by Git.

The framework records non-secret SHA-256 key fingerprints as consistency evidence in build, signing, and secure-boot flash manifests. It does not copy private key material into result directories. `flash-secure-boot` refuses to run SCP, SSH, or hardware flashing when both configured key files exist and their SHA-256 fingerprints differ.

The ECC256 key path remains `secrets/wolfboot/ecdsa_p256_private_key.der`. RSA2048 key handling is not implemented in Phase 11.5b.


## Phase 11 shared secure-boot image-header reserve

Phase 11 secure-boot benchmark profiles use one shared 8192-byte wolfBoot image-header reserve for ECC256, ED25519, and RSA2048. The matching wolfBoot logical sector size is 0x4000 / 16 KB because wolfBoot requires `WOLFBOOT_SECTOR_SIZE` to be larger than `IMAGE_HEADER_SIZE`. The signed image slot still starts at `0x08020000`, but the relocated HAL application is linked at `0x08022000` with `STM32_APP_VECTOR_OFFSET=0x00022000`. The signing profiles set `IMAGE_HEADER_SIZE=8192` for wolfBoot keytools so the signed image header and application vector address remain aligned. The wolfBoot config templates set `WOLFBOOT_SECTOR_SIZE=0x4000`; this is a wolfBoot logical sector choice for the benchmark layout, while the STM32L4R5 flash page assumption remains documented separately as 4 KB. This intentionally wastes a small amount of flash for smaller classical signatures to keep the benchmark layout stable before later PQC/hybrid profiles are added. If a future profile requires a larger header, apply the larger value globally before collecting final experiment runs.

## Phase 11.5d expanded classical signing keys

The expanded classical benchmark profiles may generate local private keys under `secrets/wolfboot/` for ECC384, ECC521, ED448, RSA3072, and RSA4096. These keys are local experiment inputs only. They must not be committed, copied into replacement artifacts, or copied into result directories. The framework records non-secret key fingerprints as consistency evidence when available, but private key material remains local.

