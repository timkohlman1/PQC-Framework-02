## Phase 11 Completion Review Checklist

### 1. Phase scope and sequencing

- [ ] Phase 11 is limited to secure-boot benchmark metrics and repeated-run support.
- [ ] Phase 11 remains focused on classical wolfBoot signing-algorithm benchmarking.
- [ ] PQC and hybrid signing algorithms are not implemented as part of Phase 11.
- [ ] MQTT, TLS, network degradation, analysis/reporting, and containerisation phases are not implemented early.
- [ ] The existing direct-flash baseline remains available and unchanged unless intentionally updated.
- [ ] Existing Phase 10 secure-boot workflows remain compatible.
- [ ] `configs/boot/wolfboot_ecdsa_p256.yaml` is not incorrectly promoted to a generic runnable direct-flash boot profile.
- [ ] Hardware, gateway, flashing, UART, or runtime success is not claimed without user-provided logs.

### 2. Benchmark result model

- [ ] A stable benchmark evidence schema exists in run manifests or benchmark manifests.
- [ ] The schema distinguishes build-time metrics from runtime metrics.
- [ ] The schema distinguishes signed-artifact metrics from bootloader metrics.
- [ ] The schema supports repeated-run samples.
- [ ] The schema supports aggregate statistics.
- [ ] The schema records unavailable metrics explicitly instead of omitting them silently.
- [ ] The schema records limitations or explanation notes for unavailable metrics.
- [ ] Existing secure-boot timing fields remain compatible.
- [ ] Existing Phase 10 fields such as `boot_mode`, `boot_crypto`, `signature_size`, `boot_signature`, `boot_timing`, and `secure_boot_evidence` are preserved or mapped cleanly.
- [ ] The manifest remains the source of truth for what was actually measured.

### 3. Runtime verification sample fields

- [ ] Each valid or attempted verification sample records the run index.
- [ ] Each valid or attempted verification sample records the sample timestamp.
- [ ] Each valid or attempted verification sample records verification time in milliseconds.
- [ ] Each valid or attempted verification sample records verification cycles.
- [ ] Each valid or attempted verification sample records verification CPU frequency.
- [ ] Each valid or attempted verification sample records verification result code.
- [ ] Each valid or attempted verification sample records verification time source.
- [ ] Each valid or attempted verification sample records verification cycles source.
- [ ] Each valid or attempted verification sample records UART marker detection result.
- [ ] Each valid or attempted verification sample records sample pass/fail verdict.
- [ ] Each valid or attempted verification sample records referenced build, bootloader artifact, signed application artifact, or equivalent artifact identity.
- [ ] Failed or invalid samples are represented explicitly.
- [ ] Failed samples do not silently contaminate valid timing statistics.

### 4. Repeated-run support

- [ ] A benchmark profile can be executed multiple times.
- [ ] One measurement sample is recorded per run.
- [ ] The configured run count is recorded.
- [ ] The actual attempted sample count is recorded.
- [ ] The valid sample count is recorded.
- [ ] The failed sample count is recorded.
- [ ] Outliers remain visible in the raw sample list.
- [ ] The repeated-run workflow does not hide individual failures behind a final aggregate result.
- [ ] Repeated-run behaviour references a consistent build/artifact identity where intended.
- [ ] The workflow avoids unnecessary rebuilds when the benchmark is meant to compare repeated verification runs of the same artifact.
- [ ] The workflow does not infer boot verification timing from host-side SSH duration, UART capture duration, reset delay, or marker ordering.

### 5. Aggregate statistics

- [ ] Verification-time sample count is calculated.
- [ ] Verification-time valid sample count is calculated.
- [ ] Verification-time failed sample count is calculated.
- [ ] Verification-time minimum is calculated.
- [ ] Verification-time mean is calculated.
- [ ] Verification-time median is calculated.
- [ ] Verification-time maximum is calculated.
- [ ] Verification-time standard deviation is calculated.
- [ ] The primary headline verification-time metric uses median, not a single run.
- [ ] Verification-cycle sample count is calculated.
- [ ] Verification-cycle valid sample count is calculated.
- [ ] Verification-cycle failed sample count is calculated.
- [ ] Verification-cycle minimum is calculated.
- [ ] Verification-cycle mean is calculated.
- [ ] Verification-cycle median is calculated.
- [ ] Verification-cycle maximum is calculated.
- [ ] Verification-cycle standard deviation is calculated.
- [ ] Invalid or failed samples are excluded from valid timing and cycle calculations.

### 6. Static build and resource metrics

- [ ] Each relevant profile or build record records bootloader ELF size.
- [ ] Each relevant profile or build record records `.text` size.
- [ ] Each relevant profile or build record records `.data` size.
- [ ] Each relevant profile or build record records `.bss` size.
- [ ] Each relevant profile or build record records total flash-relevant size.
- [ ] Each relevant profile or build record records static RAM usage estimate from `.data + .bss`.
- [ ] Each relevant profile or build record records retained wolfBoot artifact size.
- [ ] Each relevant profile or build record records unsigned application artifact size, where available.
- [ ] Each relevant profile or build record records signed application artifact size.
- [ ] Each relevant profile or build record records signed-image overhead in bytes.
- [ ] Each relevant profile or build record records signed-image overhead percentage.
- [ ] The source of static metrics is recorded, such as ELF, map, or tool output.
- [ ] Static metrics are associated with the wolfBoot build record, benchmark profile, run manifest, or another clearly documented evidence object.
- [ ] Static RAM metrics are not confused with runtime stack or heap usage.

### 7. Runtime stack and memory metrics

- [ ] Maximum stack high-water mark during verification is supported where firmware evidence is available.
- [ ] Stack metric source is recorded.
- [ ] Heap usage is recorded only if heap is actually used and reliably measurable.
- [ ] Heap metric source is recorded when heap metrics exist.
- [ ] Estimated total RAM pressure is calculated only when stack evidence is available.
- [ ] Runtime memory limitations are recorded when metrics are unavailable.
- [ ] Runtime stack and heap values come from explicit firmware-side measurement evidence.
- [ ] Runtime memory is not inferred from host-side timing, UART capture duration, reset delay, or build output alone.
- [ ] Unavailable runtime memory metrics are recorded as unavailable or null with limitation notes.

### 8. Derived metrics

- [ ] `cycles_per_kb` is calculated using the documented formula.
- [ ] `time_ms_per_kb` is calculated using the documented formula.
- [ ] `static_ram_bytes` is calculated as `.data + .bss`.
- [ ] `estimated_total_ram_pressure_bytes` is calculated only when stack evidence is available.
- [ ] Derived metrics handle missing or zero image-size inputs safely.
- [ ] Derived metric inputs are traceable to manifest evidence.

### 9. Classical signing-algorithm benchmark profiles

- [ ] Classical signing profiles are added only after the benchmark result model is stable.
- [ ] The implemented profile set is documented.
- [ ] Any reduction from the recommended full profile set is justified.
- [ ] Profiles use comparable image payloads.
- [ ] Profiles use controlled board, clock speed, measurement method, and run count.
- [ ] Each profile can build wolfBoot with the intended signing algorithm.
- [ ] Each profile can sign the same relocated application payload.
- [ ] Each profile can run through the same benchmark workflow.
- [ ] Signature algorithm, curve, or key size is recorded.
- [ ] Signature size is recorded where available.
- [ ] Private signing keys remain local and are not committed or copied into result artifacts.
- [ ] Generated signing artifacts remain out of Git unless explicitly safe and intended.

### 10. Benchmark aggregation output

- [ ] A machine-readable JSON benchmark summary is produced.
- [ ] A machine-readable CSV benchmark summary is produced.
- [ ] Summary output can aggregate across signing profiles.
- [ ] Summary output includes profile ID.
- [ ] Summary output includes signing algorithm.
- [ ] Summary output includes curve or key size.
- [ ] Summary output includes sample count.
- [ ] Summary output includes valid sample count.
- [ ] Summary output includes failed sample count.
- [ ] Summary output includes median verification time.
- [ ] Summary output includes mean verification time.
- [ ] Summary output includes minimum verification time.
- [ ] Summary output includes maximum verification time.
- [ ] Summary output includes verification time standard deviation.
- [ ] Summary output includes median verification cycles.
- [ ] Summary output includes mean verification cycles.
- [ ] Summary output includes minimum verification cycles.
- [ ] Summary output includes maximum verification cycles.
- [ ] Summary output includes verification cycles standard deviation.
- [ ] Summary output includes cycles per KB.
- [ ] Summary output includes bootloader flash size.
- [ ] Summary output includes static RAM size.
- [ ] Summary output includes maximum stack usage where available.
- [ ] Summary output includes signed-image size.
- [ ] Summary output includes signature size where available.
- [ ] Summary output includes size overhead bytes.
- [ ] Summary output includes size overhead percentage.
- [ ] Summary output includes final profile verdict.
- [ ] Summary output includes limitations.
- [ ] CSV output is suitable for charting.
- [ ] JSON output preserves richer structured evidence.

### 11. Manifest and result-directory evidence

- [ ] Benchmark run result directories are created under the documented `results/` structure.
- [ ] Manifests link to relevant logs and retained artifacts.
- [ ] Manifests identify the experiment or profile config used.
- [ ] Manifests identify the build profile used.
- [ ] Manifests identify the signing profile used.
- [ ] Manifests identify the bootloader artifact and SHA-256.
- [ ] Manifests identify the signed application artifact and SHA-256.
- [ ] Manifests identify the board, host, UART device, and relevant boot config.
- [ ] Manifests record final verdicts clearly.
- [ ] Manifest evidence is internally consistent across build, signing, flashing, UART, timing, and benchmark sections.
- [ ] Missing data is represented explicitly and consistently.

### 12. Tests

- [ ] Unit tests do not require STM32 hardware.
- [ ] Unit tests do not require SSH.
- [ ] Unit tests do not require UART devices.
- [ ] Unit tests do not require MQTT broker access.
- [ ] Unit tests do not require network impairment privileges.
- [ ] Unit tests validate benchmark metrics schema creation.
- [ ] Unit tests validate repeated-run sample recording.
- [ ] Unit tests validate aggregate calculations.
- [ ] Unit tests validate median headline metric selection.
- [ ] Unit tests validate failed-sample handling.
- [ ] Unit tests validate unavailable-metric handling.
- [ ] Unit tests validate manifest updates.
- [ ] Unit tests validate static metric parsing or calculation where implemented.
- [ ] Unit tests validate derived metric calculations.
- [ ] Unit tests validate benchmark summary JSON and CSV generation.
- [ ] Hardware tests remain marked separately.
- [ ] Hardware tests skip cleanly when required capabilities are unavailable.
- [ ] Hardware tests can be required explicitly with strict capability flags where appropriate.
- [ ] Existing direct-flash baseline tests still pass or skip correctly.
- [ ] Existing secure-boot workflow tests still pass or skip correctly.
- [ ] New benchmark hardware tests, if added, are opt-in and capability-gated.

### 13. Documentation

- [ ] `AI_BUILD_GUIDE.md` is updated for Phase 11 behaviour.
- [ ] README or architecture documentation explains the benchmark purpose.
- [ ] Documentation explains supported metrics.
- [ ] Documentation explains repeated-run measurement.
- [ ] Documentation distinguishes build metrics from runtime metrics.
- [ ] Documentation explains timing and cycle interpretation.
- [ ] Documentation explains flash, RAM, stack, and size-overhead interpretation.
- [ ] Documentation explains unavailable metrics and limitation notes.
- [ ] Documentation explains how benchmark profiles should be compared.
- [ ] Documentation includes exact commands to run the benchmark workflow.
- [ ] Documentation includes exact commands to aggregate benchmark results.
- [ ] Documentation states that PQC and hybrid signing are out of scope for Phase 11.
- [ ] Documentation preserves warnings about not committing private keys or generated secrets.
- [ ] Documentation preserves the rule that hardware success must come from user-provided logs.

### 14. Git and generated-file hygiene

- [ ] Generated benchmark result directories remain out of Git.
- [ ] Generated wolfBoot artifacts remain out of Git.
- [ ] Generated signed images remain out of Git unless explicitly intended and safe.
- [ ] Private signing keys remain out of Git.
- [ ] No SSH private keys, VPN keys, TLS private keys, MQTT passwords, `.env` secrets, private certificates, or production credentials are introduced.
- [ ] `.gitignore` covers any new generated benchmark outputs.
- [ ] Replacement files do not include local machine paths unless they are documented existing project conventions.
- [ ] The wolfBoot submodule is not left dirty by temporary instrumentation or build patches.