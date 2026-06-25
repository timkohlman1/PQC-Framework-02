# PQC IoT Experiment Framework — Step-by-Step Plan

This checklist tracks the staged development of the STM32-based PQC IoT experiment framework. The project is broader than wolfBoot: it will eventually cover secure boot, MQTT, TLS, classical crypto, PQC/hybrid crypto, network degradation, benchmarking, result capture, documentation, and tests.

## Phase 0 — Freeze the Known-Good STM32 Baseline

## Phase 1 — Establish Documentation and AI Workflow

## Phase 2 — Add Minimal Framework Skeleton

## Phase 3 — Add Result Manifest Support

## Phase 4 — Automate Build, But Do Not Flash Yet

## Phase 5 — Automate Remote Flash

- [ ] Add flash command:

  ```powershell
  python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml
  ```

- [ ] Initially wrap the known-good manual workflow:

  ```powershell
  scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
  ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
  ```

- [ ] Capture:
  - [ ] scp log
  - [ ] flash log
  - [ ] return code
  - [ ] flashed artifact path
  - [ ] ST-LINK serial

- [ ] Save flash log:

  ```text
  results/<run_id>/flash.log
  ```

- [ ] Add unit tests for generated `scp` and `ssh` commands.

- [ ] Add opt-in integration test:

  ```text
  tests/integration/test_gateway_flash_helper.py
  ```

- [ ] Confirm normal unit tests do not require hardware.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 6 — Automate UART Capture

- [ ] Add UART capture command:

  ```powershell
  python scripts/experiment.py capture-uart --experiment configs/experiments/baseline_direct_uart.yaml
  ```

- [ ] Use ST-LINK VCP path:

  ```text
  /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
  ```

- [ ] Capture for a bounded duration, for example 10 seconds.

- [ ] Save UART output:

  ```text
  results/<run_id>/uart.log
  ```

- [ ] Add pass/fail detection:
  - [ ] expected boot marker present
  - [ ] `tick` present

- [ ] Update manifest result to `pass` or `fail`.

- [ ] Add hardware test:

  ```text
  tests/hardware/test_baseline_uart.py
  ```

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 7 — Add Full Baseline Run Command

- [ ] Add combined command:

  ```powershell
  python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
  ```

- [ ] Combined command should:
  - [ ] create result directory
  - [ ] build
  - [ ] copy artifact
  - [ ] flash
  - [ ] capture UART
  - [ ] evaluate pass/fail
  - [ ] write manifest

- [ ] Treat this as the known-good automated baseline.

- [ ] Add tests for orchestration logic using mocked command runners.

- [ ] Run manually and confirm output.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 8 — Add Build Numbers and Artifact Tracking

- [ ] Add build number tracking.

- [ ] Start with simple file-based tracking if adequate:

  ```text
  .build_number
  ```

- [ ] Consider later upgrade to:

  ```text
  results/build_index.json
  ```

- [ ] Record in manifest:
  - [ ] `build_number`
  - [ ] `firmware_elf`
  - [ ] `firmware_sha256`
  - [ ] `git_commit`

- [ ] Copy important artifacts into the result folder:
  - [ ] `firmware.elf`
  - [ ] `firmware.hex`
  - [ ] `firmware.bin`
  - [ ] `build.log`
  - [ ] `flash.log`
  - [ ] `uart.log`
  - [ ] `manifest.json`

- [ ] Add unit tests for:
  - [ ] build number incrementing
  - [ ] artifact hashing

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 9 — Add Source-Hash Rebuild Skipping

- [ ] Add source hash over relevant inputs:
  - [ ] `Core/`
  - [ ] `Drivers/`
  - [ ] `CMakeLists.txt`
  - [ ] `CMakePresets.json`
  - [ ] `cmake/`
  - [ ] `STM32L4R5XX_FLASH.ld`
  - [ ] `startup_stm32l4r5xx.s`
  - [ ] `stm32_basic_hal1.ioc`

- [ ] Store last build hash.

- [ ] Skip rebuild when:
  - [ ] source hash unchanged
  - [ ] ELF exists
  - [ ] `--force` not supplied

- [ ] Always allow forced build:

  ```powershell
  python scripts/experiment.py build --force
  ```

- [ ] Add unit tests for:
  - [ ] hash calculation
  - [ ] rebuild decision

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 10 — Start Boot-Security Experiments

- [ ] Add boot mode config:

  ```text
  configs/boot/direct_flash.yaml
  ```

- [ ] Refactor baseline experiment to reference that boot config.

- [ ] Add planned config:

  ```text
  configs/boot/wolfboot_ecdsa_p256.yaml
  ```

- [ ] Do not implement wolfBoot until ready.

- [ ] Inspect wolfBoot STM32 target support.

- [ ] Choose or adapt the closest STM32L4 target.

- [ ] Define flash layout.

- [ ] Use initial working assumption only if appropriate:

  ```text
  0x08000000  wolfBoot
  0x08020000  signed application
  ```

- [ ] Relocate the HAL app linker script.

- [ ] Set vector table offset.

- [ ] Build relocated app.

- [ ] Build wolfBoot with ECDSA-P256.

- [ ] Generate signing keypair.

- [ ] Keep private signing key out of Git.

- [ ] Sign application image.

- [ ] Flash wolfBoot plus signed app.

- [ ] Confirm UART boot marker.

- [ ] Add negative test: corrupted app should not boot.

- [ ] Add boot timing instrumentation.

- [ ] Record in manifest:
  - [ ] `boot_mode`
  - [ ] `boot_crypto`
  - [ ] `signature_size`
  - [ ] `verification_time_ms`

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit at each working sub-step.

---

## Phase 11 — Add MQTT Plain Baseline

- [ ] Add simple MQTT firmware variant.

- [ ] Add broker configuration on `pqc-gateway1`.

- [ ] Add transport config:

  ```text
  configs/transport/mqtt_plain.yaml
  ```

- [ ] Add experiment config:

  ```text
  configs/experiments/mqtt_plain_baseline.yaml
  ```

- [ ] Capture:
  - [ ] connect success
  - [ ] publish success
  - [ ] publish latency
  - [ ] reconnect behaviour
  - [ ] UART logs
  - [ ] broker logs where useful

- [ ] Save metrics:

  ```text
  results/<run_id>/metrics.json
  ```

- [ ] Add tests for:
  - [ ] MQTT config parsing
  - [ ] result schema

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 12 — Add Classical MQTT over TLS

- [ ] Add wolfSSL classical TLS firmware profile.

- [ ] Add certificate handling.

- [ ] Commit only:
  - [ ] public CA certificates where appropriate
  - [ ] example configs
  - [ ] documentation

- [ ] Keep private keys in local secrets only.

- [ ] Add transport config:

  ```text
  configs/transport/mqtt_tls_classic.yaml
  ```

- [ ] Capture:
  - [ ] TLS handshake time
  - [ ] MQTT connect time
  - [ ] first publish time
  - [ ] repeat publish latency
  - [ ] RAM usage if available
  - [ ] firmware size
  - [ ] network bytes if available

- [ ] Add result metrics schema.

- [ ] Add repeat-run support.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 13 — Add Network Degradation

- [ ] Add network profile configs:

  ```text
  configs/network/normal.yaml
  configs/network/latency_50ms.yaml
  configs/network/loss_1pct.yaml
  configs/network/jitter_20ms.yaml
  ```

- [ ] Add Linux `tc netem` wrapper on `pqc-gateway1`.

- [ ] Add setup and cleanup behaviour:
  - [ ] apply impairment before run
  - [ ] verify impairment active
  - [ ] run experiment
  - [ ] clear impairment after run
  - [ ] verify impairment cleared

- [ ] Make cleanup robust even if the experiment fails.

- [ ] Add unit tests for generated `tc` commands.

- [ ] Add opt-in integration tests for applying and clearing network impairment.

- [ ] Record network profile in manifest.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 14 — Add PQC/Hybrid Transport Experiments

- [ ] Verify selected wolfSSL version.

- [ ] Confirm supported PQC/hybrid options.

- [ ] Add build profiles for PQC/hybrid TLS only after support is confirmed.

- [ ] Add transport configs:

  ```text
  configs/transport/mqtt_tls_pqc.yaml
  configs/transport/mqtt_tls_hybrid.yaml
  ```

- [ ] Capture the same metrics as classical TLS:
  - [ ] firmware size
  - [ ] RAM use
  - [ ] handshake time
  - [ ] MQTT connect time
  - [ ] publish latency
  - [ ] success/failure under degraded networks
  - [ ] reconnect behaviour

- [ ] Add comparison scripts later.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 15 — Add Analysis and Reporting Tooling

- [ ] Add script to aggregate result manifests and metrics:

  ```text
  scripts/analyse_results.py
  ```

- [ ] Produce CSV summaries:

  ```text
  results_summary.csv
  ```

- [ ] Produce charts later:
  - [ ] boot verification time
  - [ ] TLS handshake time
  - [ ] publish latency
  - [ ] success rate under packet loss
  - [ ] firmware size by crypto profile
  - [ ] RAM use by crypto profile

- [ ] Keep raw results immutable.

- [ ] Put derived summaries in a separate folder:

  ```text
  analysis/
  ```

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Immediate Next Actions

- [ ] Finish `.gitignore`.
- [ ] Commit the STM32 HAL baseline.
- [ ] Create `AI_BUILD_GUIDE.md`.
- [ ] Create the docs skeleton.
- [ ] Create the ChatGPT Project instruction prompt.
- [ ] Commit documentation.
- [ ] Add `configs/`, `scripts/`, and `tests/`.
- [ ] Implement `experiment.py status`.
- [ ] Add unit tests for config loading.
- [ ] Add manifest creation.
- [ ] Add unit tests for manifest creation.
- [ ] Only then automate build, flash, and UART capture.

## Current Rule

Do not start wolfBoot, MQTT, TLS, PQC, or network impairment until the baseline framework exists and has tests.
