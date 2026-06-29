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
