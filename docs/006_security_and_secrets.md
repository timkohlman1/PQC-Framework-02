# Security and Secrets

## Purpose

This document owns repository secret-handling and generated-private-state policy. Operational SSH setup is in `docs/002_host_gateway_setup.md`, flash/signing commands are in `docs/005_remote_flash_workflow.md`, and broker certificate operation is in `experiment/mqtt-broker/README.md`.

## Never commit or package

Do not commit, add to container images/build contexts, copy into result artifacts or replacement ZIPs, or include in documentation:

- SSH or VPN private keys and profiles
- TLS, client, CA, or firmware-signing private keys
- MQTT passwords, password files, tokens, or production credentials
- real `.env` files
- private certificates or key bundles
- generated local signing keys under `secrets/wolfboot/`
- wolfBoot working-tree signing keys such as `tools/wolfboot/wolfboot_signing_private_key.der`
- broker runtime material under `experiment/mqtt-broker/runtime/`

Non-secret documentation, credential-free example configs, public test certificates, public CA certificates, dummy example values, and project-owned wolfBoot config templates may be committed when their purpose is clear.

## wolfBoot signing state

Build/signing manifests may record non-secret aggregate and per-file SHA-256 fingerprints, but must never copy private key material into results. Per-file fingerprint records contain repository-relative paths and content digests only, not file contents or absolute host paths.

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

The repository-local, ignored `secrets/` hierarchy is the single source of truth for MQTT TLS and wolfBoot signing material. Experiment YAML declares profile identifiers, not certificate or private-key paths. The experiment runner resolves and prepares the declared profile before fingerprinting, build generation, broker deployment, signing, or execution.

Runtime, build, broker-compose, and result directories are not authoritative key stores. They may contain bounded deployment copies where required, but no workflow may select material by discovering whichever file happens to be present there. Partial tuples and public/provenance hash mismatches fail closed. Manifests retain profile identifiers and public hashes only; private key bytes are never retained in results.
