# Security and Secrets

## Purpose

This document owns repository secret-handling and generated-private-state policy. Operational SSH setup is in `docs/002_host_gateway_setup.md`, flash/signing commands are in `docs/005_remote_flash_workflow.md`, and broker certificate operation is in `experiment/mqtt-broker/README.md`.

## Commit, image, and result boundaries

Disposable experiment cryptographic material must remain ignored by Git and must not be baked into container images or static build contexts. It may, however, be copied into the result directory of the build or experiment that used it so the recorded result is self-contained and can be reproduced manually.

The following result retention is required when the material exists and is selected by the owning workflow:

- unsigned and signed application images;
- application and bootloader ELF, BIN, and HEX outputs;
- firmware-signing and wolfBoot private/public keys, generated keystores, tuple manifests, and verification material;
- MQTT root/intermediate CA certificates, chains, broker certificates and private keys, and mutual-TLS client certificates and private keys;
- ESP32 or other experiment-infrastructure firmware and configuration artifacts explicitly used by the workflow.

Every retained file must be copied explicitly by its owning workflow and recorded in `material-inventory.json` with its result-relative path, SHA-256 digest, size, role, private/public classification, and intended use. Workflows must not recursively sweep broad host directories or discover credentials from result folders. Canonical source state remains authoritative.

The following remain prohibited from result artifacts, replacement ZIPs, images, and build contexts because they are host/control-plane or production credentials rather than disposable experiment inputs:

- SSH private keys, SSH agent state, known-hosts databases, and VPN private keys or profiles;
- API tokens, GitHub credentials, bearer tokens, and unrelated machine credentials;
- production or externally managed certificates and keys;
- real `.env` files and unrelated password stores.

Production, externally managed, or non-exportable material must fail closed rather than be archived. Result folders containing disposable private keys are sensitive experiment records and must stay ignored by Git. Retention of these disposable private keys is intentional for reproducible research evidence; the result directory or any ZIP made from it must be classified and handled as sensitive key material. Do not publish, attach to public issues, or share externally without an explicit review of `material-inventory.json` and removal of material that is not authorised for that destination.

## wolfBoot signing state

Build/signing manifests retain aggregate and per-file SHA-256 fingerprints and must also reference the copied experiment material inventory. Private tuple members are copied byte-for-byte into the owning result directory after tuple validation; they are never reconstructed from public metadata.

The reusable signing tuple consists of the canonical private key, matching wolfBoot-local private key, generated public key, and generated `tools/wolfboot/src/keystore.c`:

- A completely absent tuple may be created by its owning workflow when profile configuration permits generation.
- A complete matching tuple is preserved and reused.
- A partially missing tuple fails safely; missing members are not silently reconstructed.
- A mismatched tuple fails safely; the canonical private key is not silently replaced and tuple members are not overwritten.

`flash-secure-boot` must reject inconsistent canonical and wolfBoot-local private-key fingerprints. Do not use wolfBoot `keysclean` or manual tuple-member deletion as routine cleanup.

Generated-state preflight is the primary mechanism for build/signing compatibility, artifact hashes, stale-output handling, and provenance. Pytest session-start cleanup is supplementary cross-platform hygiene only; it must not remove canonical keys or reusable tuple members and is not signing-state validation.

## Container and gateway access

Docker-hosted execution is the normal path. Container images and build contexts must remain secret-free. Signing material is supplied through the runtime-mounted workspace or generated as ignored local workspace state.

Gateway wrappers explicitly enable gateway access, mount the configured host SSH directory read-only, and use it only for the temporary container run. Keep known-hosts data, SSH configuration, and private keys local. Do not bake them into the image.

Representative capability-gated command:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

The command’s success proves only the evidence asserted by that test. Gateway SSH reachability is not board runtime, UART, broker, MQTT/TLS, timing, memory, benchmark, or end-to-end evidence.

## Broker TLS material

The classical and experimental OQS broker profiles use generated development TLS material under ignored runtime directories. Gateway deployment may copy that material only to the intended temporary or configured remote broker directory.

Do not commit broker private keys, client private keys, CA private keys, password files, private certificates, real `.env` files, or production credentials. The OQS profile is protocol-evaluation infrastructure, not production TLS.

Broker/client validation is host-side or broker-side evidence. It cannot prove STM32 firmware, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, ST67W61M1, UART, or end-to-end wireless success.

## Firmware secret boundary

Current STM32 lwIP, wolfSSL, and wolfMQTT preparation must not compile private keys, broker credentials, real environment values, private certificates, CA private material, or bearer tokens into firmware.

The implemented STM32 evidence includes build-only linkage, local helper/context lifecycle smokes, an unavailable wolfSSL transport boundary with no socket I/O, local UDP loopback, and fake/no-network wolfMQTT initialization. These are not certificate-backed TLS-handshake or real MQTT evidence. Real credentials must not be introduced merely to exercise an unavailable boundary.

## CI secret handling

The default containerised non-hardware CI path must not require repository, organisation, or environment secrets. Temporary local test certificates used by broker runtime checks are per-run development material and must not be committed. Any future gateway, hardware, Wi-Fi-module, or secret-dependent CI must be separate and explicitly opt-in.

## Generated outputs to keep out of Git

```text
build/
results/*
!results/.gitkeep
.pqc-generated-state/
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
tools/wolfboot/wolfboot_signing_public_key.der
tools/wolfboot/src/keystore.c
secrets/wolfboot/
experiment/mqtt-broker/runtime/
experiment/mqtt-broker/data/
experiment/mqtt-broker/log/
experiment/mqtt-broker/.env
```

Generated files can be locally required while still remaining untracked. Their lifecycle must be handled by the owning workflow and generated-state preflight, not by committing them.

## Persistent wolfBoot signing identity

The authoritative wolfBoot signing state is the complete local tuple under
`secrets/wolfboot/tuples/<tuple-id>/`: private key, public key, generated
`keystore.c`, and `tuple.json`. Generic cleanup must never modify `secrets/`.

The matching files under `tools/wolfboot/` are materialized build copies. They
may be deleted by clean builds, submodule resets, or test cleanup and are
restored automatically from the validated persistent tuple.

Configuration chooses the tuple ID. Algorithm changes must select a compatible
tuple ID. The framework never overwrites a complete persistent tuple and fails
on partial state or hash mismatch.


### Standalone public-key export

The maintained ECDSA-P256 tuple also stores `public_key.der` in wolfBoot's raw
ECC public-key format: 32-byte X followed by 32-byte Y. The corresponding
wolfBoot private-key file is raw X, Y, and private scalar data, so the public
file can be derived without changing the private key. Before writing or
migrating the public file, the framework verifies that those 64 bytes exactly
match the key embedded in `keystore.c`.

The public-key hash and format metadata are recorded in `tuple.json`. Existing
tuples are migrated in place without rotating or rewriting `private_key.der`.

## Automated-test result retention

Automated-test manifests and logs may retain commands, outcomes, public hashes,
fingerprints, paths, and bounded failure details. They must not retain
passwords, PSKs, tokens, credentials, private-key contents, private certificate
material, secret environment values, or generated authentication files. Secret-
bearing fields are redacted before JSON manifests are written. A test may
reference a canonical non-secret result record by identity, path, and hash, but
must not copy secret material or mutate the referenced record.

## Cryptographic prerequisite ownership

The repository-local ignored generated-state hierarchy remains authoritative for cryptographic inputs, but MQTT X.509 and wolfBoot signing material have distinct owners. `secrets/certificates/` is authoritative for generated MQTT X.509 profiles, while `secrets/wolfboot/` remains authoritative for wolfBoot signing tuples. Experiment YAML declares profile identifiers, not certificate or private-key paths. The experiment runner resolves and prepares the declared profile before build generation, broker deployment, signing, or execution.

`secrets/certificates/<certificate-profile>/` is both the authoritative generated X.509 profile and the broker/STM32 input. There is no secondary MQTT certificate staging tree. Runtime, build, broker-compose, and result directories are not authoritative key stores. Result directories contain bounded reproduction copies, but no workflow may select future inputs by discovering whichever file happens to be present there. Public/provenance hash mismatches fail closed. Manifests identify the selected family and the result-relative material inventory.

## Certificate provisioning and wolfBoot key separation

`scripts/provision_certificates.py` owns offline X.509 generation. Profile definitions live under `configs/certificate_profile/`; the provisioner reads those YAML files and writes each generated profile directly under ignored `secrets/certificates/<profile-id>/`. Experiments never generate, renew, or stage certificates. If the selected profile is absent or incomplete, prerequisite preparation fails and instructs the user to run the one-time provisioning command. No online CA, Vault, KMS, ACME, OCSP, or continuously running certificate service is required.

wolfBoot signing keys are not X.509 identities and must not be issued by the X.509 provisioner. The wolfBoot tooling remains responsible for algorithm-compatible generation and public-key export. The historical `framework/certs` Step CA/Vault/KMS/ML-DSA provisioning subsystem has been removed. wolfBoot signing state remains independent of X.509 certificate profiles.


TLS key logs retained as `mqtt-broker-tls-keylog.log` are experiment-only secret material because they permit decryption of the associated packet capture. They belong only in ignored result directories, must be inventoried by SHA-256 in the result manifest, and must not be committed or copied into AI context or replacement archives.
