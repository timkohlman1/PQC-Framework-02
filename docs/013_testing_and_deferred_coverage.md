# Testing and deferred coverage

This is the canonical test architecture and consolidated deferred-test register.
[AI_BUILD_GUIDE.md](../AI_BUILD_GUIDE.md) owns mandatory testing policy; this
reference maps that policy to runnable layers and outstanding validation.

## Test layers

| Layer | Boundary | Default command |
|---|---|---|
| Unit | Software contracts without hardware, SSH, brokers or credentials | `./scripts/dev.sh pytest tests/unit` |
| Integration | Real local process/toolchain/Docker boundaries; explicit capability gates | `./scripts/dev.sh pytest tests/integration -m integration` |
| Hardware | Gateway-mediated STM32 execution and retained raw evidence | `./scripts/dev.sh pytest-hardware` |

Integration module names end in `_in.py`, hardware names in `_hw.py`; module
basenames must be unique. A plain `./scripts/dev.sh pytest` can skip unavailable
capabilities. Strict `--pqc-require-*` controls turn missing capabilities into
failures when the selected gate is intentionally required. A skip is not success.

Hardware tests prepare their own canonical case, build/sign/flash through owning
framework paths, capture and validate evidence, and clean up test-owned state.
They do not require pre-generated campaigns or user-supplied prior logs as their
default entry point. Gateway credentials, physical boards, installed tools and
provisioned brokers/instruments remain laboratory prerequisites. The wrapper
isolates `build/` and `.pqc-generated-state/` in Docker volumes. Retained-log tests
are parser coverage, not substitutes for a self-contained physical test.

## Evidence and CI

`results/automated-tests/<test_run_id>/` retains incremental session/stage
outcomes, failure reasons, artifact hashes and test-triggered builds. Test builds
do not reserve normal `.build_number` values or populate `results/builds/`.
`test_run_id`, canonical `run_id`, normal `build_number` and test `build_identity`
are separate identities. References to canonical experiment evidence remain
immutable. All experiment material follows the [open-data policy](006_security_and_secrets.md);
redaction/mode tests describe existing code, not a confidentiality requirement.
Generated-state preflight owns compatibility; pytest cleanup is only supplementary hygiene and must preserve source and canonical signing state.

`.github/workflows/ci.yml` defines runner compatibility, local broker/Docker and
container software validation. These jobs provide only their observed software
and host/broker evidence. The laboratory hardware/gateway layers are separate.
The checkout notebook `notebooks/00_checkout.ipynb` runs local status and unit
checks; it is not a hardware gate. Analysis notebook integration uses synthetic
inputs in temporary copies and clean kernels, not saved interactive outputs.
Copies retain the actual configuration cells. `tests/integration/test_analysis_workspace_in.py`
checks repository/notebook working directories, CLI/notebook equivalence, pinned
selection, vector figure output and separate output/source verification.
`tests/unit/test_analysis_workspace.py` checks figure/table statistical agreement,
missingness, outcome denominators and presentation validation.
`tests/integration/test_analysis_domains_in.py` exercises import, inspection,
selection, preview, publication and strict CSV/LaTeX rebuild for all eight domains,
including repeated TLS, retained packet flow attribution, energy boundaries,
primitive cycles and unconfirmed OTA transitions. Every domain executes the shared
notebook in a clean kernel and compares its scientific CSV/LaTeX with CLI output;
figure checks use the same published values. Queue export handoff, collection chapter
rendering, Jupyter authentication and PDF export retain separate integration tests. Failed runs and
recorded absent inputs remain reportable; later file appearance fails strict
source verification. All fixtures are
synthetic. `tests/integration/test_analysis_paths_in.py` covers relocated Docker
result paths in host-style checkouts, source tampering and the shared notebook;
`tests/unit/test_analysis_paths.py` covers mapping and symlink boundaries.
`tests/unit/test_analysis_comparison.py` checks complete-run selection,
standalone/current-attempt handling, explicit grouping, units and unavailable
matched effects. Existing A3–A8
retained/hardware evidence gaps below remain open; presentation tests do not close
them or establish new measurement evidence.

The maintained secure-boot flash test has focused positive/negative/restoration
coverage; the plaintext MQTT test owns a focused exchange. Neither represents the
retired full algorithm/MQTT matrix. See the register before claiming broad coverage.

## Network startup phase markers

`tests/unit/test_network_phases.py` checks historical absence, failed-call
intervals and malformed trace rejection. The real native integration in
`tests/integration/test_network_phases_in.py` compiles the marker module with the
maintained result buffer and checks deferred serialization, 64-bit timestamps,
reset isolation, partial intervals and invalid call sequences. The existing
energy firmware build cases compile the hooks in normal and repeated workloads.

Physical phase attribution requires a newly instrumented capture from the
normal gateway-mediated campaign workflow. Old captures cannot gain missing
network markers. Inspect the retained MQTT records, GPIO alignment, pre-trigger
coverage and each attempted phase before attributing a plotted feature. Native
compilation alone does not establish ST67 runtime behavior.

Bounded hardware evidence (2026-10-16): queue job `b53546c9d3b6` repeated the
four original power configurations with ten fixed attempts each. All 40 attempts
completed and retained all seven completed network spans in deferred MQTT data;
sealed UART logs contain none of the new markers. The exported batch is
`results/queue/exports/20261016-170220-a8d6cb`. One capture retains only 315 ms of
pre-trigger samples and is excluded from full boot/phase-display eligibility;
the other 39 support that display. No replacement attempt was added. This checks
normal startup and transport in those four configurations, not hardware fault
paths or exclusive CPU/radio-state attribution.


The scan-default change (2026-10-17) is not covered by that earlier hardware
batch, which had the scan enabled. The local energy-build gate also compiles
`main.c` with both scan settings and checks the ARM object: the default has no
reference to `W6X_WiFi_Scan`, the diagnostic option retains it, and both retain
`W6X_WiFi_Connect`. The native buffered-marker test checks an unattempted scan
followed by a completed connection. Runtime confirmation is deferred: the user
has requested no new experiments before rebooting the PC and reconnecting the
ESP32 recorder. Retained captures and published energy values are unchanged.

## Documentation checks

For documentation changes run:

```bash
./scripts/dev.sh pytest tests/unit/test_documentation_integrity.py
./scripts/dev.sh pytest tests/unit/test_docker_default_workflow_docs.py
./scripts/dev.sh pytest tests/unit
```

Checks enforce inventory/ownership, local link and anchor validity, runnable
command targets and selected executable/safety contracts. They do not assert
whole paragraphs or arbitrary document-length limits, force duplicate explanations
into every entry document, or prove semantic accuracy of prose. Read source when changing capability claims.
Parser-helper fixtures exercise broken links, anchors and table structure so the
checker itself must detect failures. Historical plans/decisions are indexed as
context; current references must not route readers to obsolete implementation
instructions as current authority.

## Consolidated deferred-test register

Related changes must implement, update or explicitly retire applicable rows.
Keep each ID stable, all eight fields, a concrete target and a verification path.
Rows marked planned can name future test files; they are not current runnable
commands. Closed/retired rows remain for traceability without requesting obsolete
work. Existing dated observations below are carried forward from the previous
register; documentation maintenance does not rerun or independently revalidate
those laboratory results. Updated status distinguishes missing implementation
from missing profile qualification.

Open rows below describe remaining work, not authorization to run hardware.
Historical observations are bounded to their recorded date/scenario.

### Outstanding or partial coverage

| ID | Feature | Missing test layer | Reason | Required capability or phase | Intended test file | Eventual verification command | Status |
|---|---|---|---|---|---|---|---|
| DTR-MLDSA-STANDBY | Correct ML-DSA parameter level in multi-key boot tuples | Full standby-key update/recovery transition matrix | Local real keygen/sign checks do not establish standby-key activation or authenticated rollback. | Gateway, STM32/ST67 and selected OTA profiles | `tests/integration/test_mldsa_standby_in.py`; `tests/hardware/test_ota_dualbank_hw.py` | `./scripts/dev.sh pytest tests/integration/test_mldsa_standby_in.py -m integration --pqc-require-local-build`; `./scripts/dev.sh pytest-hardware tests/hardware/test_ota_dualbank_hw.py --pqc-require-hardware` | partial: real ML-DSA-44/65/87 multi-key generation and signing pass; six ML-DSA-65 zero/one/two-standby-key build/boot cases completed with verified cleanup (queue job `56dc761d3d67`); complete standby-key transitions remain unqualified |
| DTR-HOST-USER | Host-user runtime identity and output ownership | Remaining local firmware/wolfBoot build regression | Recorded host ownership and certificate gates do not qualify local firmware/wolfBoot builds. | Non-root Linux user, local non-remapped Docker daemon, development image and complete checkout | `tests/integration/test_container_host_user_in.py`, `tests/integration/test_certificate_ownership_in.py`, `tests/integration/test_local_build_in.py`, `tests/integration/test_wolfboot_build_integration_in.py` | `./scripts/dev.sh check-host-user`; `python3 scripts/check_certificate_ownership.py`; `./scripts/dev.sh pytest tests/unit`; `./scripts/dev.sh pytest tests/integration/test_local_build_in.py tests/integration/test_wolfboot_build_integration_in.py -m integration --pqc-require-local-build` | partial: host ownership and disposable RSA-3072/ML-DSA-65 provisioning passed 2026-09-29; firmware build gates pending |
| DTR-HOST-USER-GATEWAY | Non-root gateway wrapper and isolated hardware outputs | Live SSH/gateway and representative hardware regression after identity change | Synthetic SSH/volume tests do not exercise real authentication, remote helper permissions or board operation. | Rebuilt development image, runtime SSH credentials, gateway and STM32 where required | Existing `tests/integration/test_gateway_flash_helper_in.py` and `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-gateway tests/integration/test_gateway_flash_helper_in.py -m integration --pqc-require-gateway`; `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred; these commands can build/flash hardware and require retained evidence |
| DTR-WIFI-SCAN-DEFAULT | Disable diagnostic AP scan in normal experiments | Wider profile qualification and controlled energy comparison | The bounded follow-up establishes operation with the scan omitted; three runs per condition do not qualify all workloads or isolate the effect on energy. | ESP32/INA228, gateway and STM32/ST67; any further collection needs separate authorization | Existing `tests/hardware/test_energy_capture_hw.py` and normal campaign workflow; retained phase and power analysis | `python3 scripts/run_queue.py list`; inspect retained job `f23b02e41430` and export `20261018-113526-1d9372`; verify `wifi_scan` not attempted and other six network spans completed | partial: 12/12 fixed attempts completed on 2026-10-18 (four server-authenticated TLS configurations, three each); all 12 have accepted captures, complete pre-trigger evidence, scan not attempted, and successful connection/address readiness; gateway cleanup passed; original scan-enabled energy estimates retained separately |
| DTR-ST67-ACTIVITY | Buffered ST67 command/event markers and SPI-call bins in energy workloads | Instrumentation perturbation and internal radio-state attribution | Host timestamps locate calls and waits; no task-state or radio-internal trace, and no paired trace-on/off perturbation study | STM32/ST67, gateway and ESP32/INA228; any further comparison is a separate experiment | `tests/integration/test_activity_trace_in.py`, `tests/integration/test_energy_stm32_in.py`; normal campaign captures and retained analysis | `./scripts/dev.sh pytest tests/unit/test_activity_trace.py tests/integration/test_activity_trace_in.py`; `python3 scripts/run_queue.py list`; inspect job `67d61da92ecb` | partial: four fixed verification captures completed with schema 2, 61 events each, no drops, saturation or clipping, and normal gateway cleanup; six schema 1 pilot captures retained with saturated SPI bins as lower bounds; 16-bit counters and bounded transport validated locally; all earlier cohorts retained separately |
| DTR-MLDSA-SAMPLING | Per-signature outer rejection-loop counts | Live mutual-TLS transport and count-conditioned spread | Native signatures and bounded recorder checks cannot establish target reporting or variability by count | STM32/ST67, gateway and energy recorder; fixed exploratory matrix | `tests/integration/test_mldsa_sampling_in.py`; normal queue collection | `./scripts/dev.sh pytest tests/unit/test_mldsa_sampling.py tests/integration/test_mldsa_sampling_in.py`; inspect retained exploratory capture plan | partial: decoder and normal/small-memory sign-byte equivalence pass locally; 30 fixed normal-path ML-DSA-65 mutual-TLS captures and two classical power captures completed with accepted evidence and verified cleanup (jobs `b2481905145d`, `3ade43ef28a2`); all 30 signing counts join to their TLS events; small-memory target counts, instrumentation overhead and internal rejection predicates remain unmeasured |
| DTR-RUN-QUEUE | Persistent terminal queue, cooperative pause/failure decisions and selected CSV/archive export | Live different-configuration interleaving, abrupt worker interruption, control-plane timeout and physical fault recovery | Two recorded live tests preserved a capture across pause/resume and continued after injected host rejection. Different-firmware interleaving and physical faults remain unqualified. | Gateway, STM32/ST67, brokers and energy recorder for selected profiles | `tests/hardware/test_run_queue_hw.py`; existing `tests/hardware/test_campaign_executor_hw.py` for different-firmware restoration extension | `./scripts/dev.sh pytest-hardware tests/hardware/test_run_queue_hw.py --pqc-require-hardware`, then controlled queue/fault scenarios with retained manifests | partial: 2 live tests recorded 2026-10-04; different-configuration/physical fault qualification pending |
| DTR-ST67-ACK | ST67 READY/CS transaction boundary and transfer diagnostics | Physical delayed-edge/stuck-READY fault qualification and long repeated workloads | Native C tests exercise stale event delivery, missing edge, stuck high, tick wrap, recovery gating and polling/DMA outcomes; these cannot establish the original intermittent stall mechanism. | STM32/ST67, gateway and retained UART/MQTT/packet captures; controlled GPIO fault injection for edge qualification | `tests/integration/test_st67_spi_boundary_in.py`; `tests/hardware/test_tls_handshake_repeat_hw.py` | `./scripts/dev.sh pytest tests/integration/test_st67_spi_boundary_in.py`; `./scripts/dev.sh pytest-hardware tests/hardware/test_tls_handshake_repeat_hw.py --pqc-require-hardware` | partial: native regression coverage; physical fault injection and broad qualification pending |
| DTR-CAPTURE-DEADLINE | Bounded MQTT/capture/control operations and campaign watchdog | Live SSH loss, Docker-daemon stalls and OQS container cleanup under forced termination | Recorded gateway stalled-child and plaintext/classical total-loss recovery passed. Local process termination tests do not prove remote SSH/Docker/OQS cleanup. | Gateway, STM32/ST67, OQS broker and controlled control-plane fault injection | `tests/hardware/test_capture_deadline_hw.py`; `tests/hardware/test_negative_trial_hw.py`; `tests/integration/test_operation_timeout_in.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_capture_deadline_hw.py tests/hardware/test_negative_trial_hw.py --pqc-require-hardware` | partial: 3 live tests recorded 2026-10-06, stalled-child return 1.22 s; disruptive SSH/Docker/OQS faults pending |
| DTR-CAMPAIGN-RESUME-FLASH | Restore expected firmware on campaign resume | Live resume after an intervening different firmware flash | Subprocess tests cannot prove expected firmware was restored after an intervening different image. | Gateway, STM32/ST67, build/sign prerequisites and brokers | `tests/hardware/test_campaign_executor_hw.py` (extend with intervening flash and resume) | `./scripts/dev.sh pytest-hardware tests/hardware/test_campaign_executor_hw.py -m hardware --pqc-require-hardware` after extending the live resume scenario | pending live intervening-flash/resume validation |
| DTR-OQS-MTLS-CHAIN | Container-local CA chain and dedicated health-topic ACL | Gateway deployment and blocked campaign retry | Local Docker startup, chain access and authentication checks do not establish gateway deployment or STM32 mutual TLS. | Gateway and STM32/ST67 laboratory | `tests/integration/test_oqs_mtls_permissions_in.py`; `scripts/check_oqs_mtls_broker.py` local gate; retained campaign manifests | `python3 scripts/check_oqs_mtls_broker.py`; `./scripts/dev.sh campaign-gateway --resume results/campaigns/tls_matrix_energy_20260928_222043/campaign-manifest.json` | local Docker passed 2026-09-29 for RSA-3072 and ML-DSA-65: healthy startup, staged-file access, authenticated publish and rejection without client certificate; live campaign retry pending |
| DTR-CAMPAIGN-CONTINUE | Continue after runtime failures and blocked preparation/broker setup | Live post-handshake transfer timeout and hybrid/PQC fault coverage | Recorded plaintext/classical total-loss trials retained reporting and recovered to a reference run; later transfer timeouts and hybrid/PQC failures remain unqualified. | Gateway, STM32/ST67 and brokers | `tests/hardware/test_negative_trial_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_negative_trial_hw.py --pqc-require-hardware` | partial: 2 live tests recorded 2026-10-04; post-handshake/hybrid fault qualification pending |
| DTR-TLS-MATRIX-ENERGY | Ready Metrics 2 TLS matrix with energy on every condition | Live 12-condition TLS/energy campaign acceptance | Resolver, broker dry-runs and synthetic notebooks cannot qualify the complete 12-condition instrumented matrix. | STM32/ST67, gateway, experiment/reporting brokers, configured Wi-Fi and persistent ESP32/INA228 | `tests/integration/test_tls_matrix_energy_campaign_in.py` (offline); existing `tests/hardware/test_energy_capture_hw.py` (instrument boundary); retained campaign manifests for the complete matrix | `./scripts/dev.sh campaign-gateway tls_matrix_energy`; export the exact resulting campaign with `scripts/export_timing_dataset.py` and verify consumed inputs | pending first live matrix run; energy enabled in all 12 conditions, 120 planned runtime attempts |
| DTR-A5-TRIAL | Network impairment pilot campaign and comparison presets | Gateway/STM32 execution of 15 planned attempts | Offline resolution/analysis does not qualify the five-condition, three-attempt network pilot. | Available gateway, STM32/ST67, experiment/reporting brokers and configured credentials | `tests/integration/test_network_trial_in.py` (offline); retained campaign runtime evidence | `./scripts/dev.sh campaign-gateway network_trial` then the import/select/publish commands in `docs/015_campaign_collection.md` | pending operator trial; offline resolver and report pipeline tested separately |
| DTR-NO-TLS-APPS | Matched plaintext Ready Metrics 1/2 and thesis baselines | Live application, packet and E5V energy acceptance | Recorded plaintext application/burst/energy acceptance does not establish all impaired-network or matched transport comparisons. | Provisioned gateway/STM32/ST67, brokers; INA228 for energy campaigns | `tests/hardware/test_plaintext_application_baselines_hw.py`, collection campaign manifests | `./scripts/dev.sh pytest-hardware tests/hardware/test_plaintext_application_baselines_hw.py --pqc-require-hardware`, then matched collection profiles | partial: both applications, five burst repetitions and a fresh two-run energy campaign accepted 2026-09-30; full matched matrix pending |
| DTR-THESIS-COLLECT | Resumable thesis collection coordinator | Live multi-campaign interruption/resume, compact terminal feedback on the collection PC, INA228 attribution and OTA end-to-end acceptance | The recorded original collection predates the revised focused plan and does not qualify live interruption/resume. | Provisioned gateway/STM32/ST67, brokers and persistent energy recorder | `tests/integration/test_run_console_in.py`; `tests/integration/test_thesis_collection_in.py`; existing campaign/energy/OTA hardware tests; collection manifests | `python3 scripts/collect_thesis_evidence.py run --output results/thesis/collection-01` after the documented plan command | partial: original 2026-09-30 collection recorded 930 attempts (921 completed, 9 failed) and 8 passing OTA tests; revised plan/interruption qualification pending |
| DTR-CHAPTER-TABLES | Chapter 5 views of the shared analysis workspace | Complete real-run coverage of every proposed thesis measurement | Table publication cannot supply unimplemented measurement boundaries; physical follow-up outcomes require their own retained campaign manifests. | Explicit comparable captures, validated new acquisition boundaries and an agreed inferential design for pending measures | `tests/unit/test_chapter_tables.py`, `tests/integration/test_chapter_tables_in.py`; retained report verification/rebuild | `./scripts/dev.sh pytest tests/unit/test_chapter_tables.py`; `./scripts/dev.sh pytest tests/integration/test_chapter_tables_in.py -m integration`; `./scripts/dev.sh python scripts/analyse_results.py verify results/analysis/reports/thesis-chapter5/20261010-final-2 --verify-sources` | offline CLI publication and byte-identical replay verified 2026-10-10 with synthetic captures; retained-data publication also produced all 20 fragments. D1–D9 scopes agreed; whole-device RAM, usable OTA capacity and boot-origin energy boundaries remain incomplete. Timeline clocks, phase nesting, transpose/landscape projections and energy spread have offline tests; real collection outcomes remain separate |
| DTR-A8-THESIS | Frozen reports and thesis pilot profiles | Live qualification of the new campaign combinations; full matched RQ coverage; bare-metal and OTA retained importer acceptance | Offline report/importer fixtures do not establish new campaign outcomes or all thesis comparison controls/boundaries. | STM32/ST67, gateway, appropriate broker profiles, instrument where selected, sealed comparable captures | `tests/integration/test_research_report_in.py`; existing `tests/hardware/test_baremetal_benchmark_hw.py`, `tests/hardware/test_ota_dualbank_hw.py`, `tests/hardware/test_energy_capture_hw.py`; campaign manifests | `./scripts/dev.sh campaign-gateway thesis_kex`; other profile commands in `docs/015_campaign_collection.md`; `./scripts/dev.sh pytest-hardware tests/hardware/test_ota_dualbank_hw.py` | offline report/profile validation only; new hardware campaign qualification and unsupported draft metrics remain outstanding |
| DTR-A7-EVIDENCE | A7 normal secure-boot reports | Retained matched profile differences, boot RAM and boot energy acceptance | Recorded boot/layout import lacks supported matched deltas, bootloader resource observations and boot-aligned energy. | Comparable retained records with known provenance and matching boot intervals; no new flashing or acquisition in A7 | `tests/integration/test_analysis_domains_in.py` (extend retained acceptance) | `./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/SELECTED_ANALYSIS.json --name retained-acceptance` | partially verified 2026-09-29: 120 retained boot reports and signed-image layouts imported; matched differences, bootloader static/RAM and boot energy remain unavailable |
| DTR-A6-EVIDENCE | A6 energy totals and bounded-phase reports | Real whole-window and matched-configuration acceptance; physical acquisition qualification | The earlier trace supported internal phases but not full-window brackets or matched electrical attribution. Later acquisition coverage is tracked separately by DTR-013. | Retained bracketed intervals, lab electrical-boundary references, comparable controls and independently qualified acquisition; no new experiment authorized by A6 | `tests/integration/test_analysis_domains_in.py` (extend retained acceptance); existing `tests/hardware/test_energy_capture_hw.py` for separately authorized instrument work | `./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/SELECTED_ANALYSIS.json --name retained-acceptance` | partially verified 2026-09-29: real 6,677-sample phase trace imported; whole-window/matched/physical qualification deferred |
| DTR-A5-EVIDENCE | A5 retained packet and impairment reports | Real baseline/impaired matched acceptance | The earlier baseline import did not establish attributable impaired-flow comparisons; later runtime passes alone do not close offline matched-analysis acceptance. | Explicit retained baseline/impaired captures, device-flow association and comparable controls; offline only | `tests/integration/test_analysis_domains_in.py` (extend with retained evidence) | `./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/SELECTED_ANALYSIS.json --name retained-acceptance` | partially verified 2026-09-29: real baseline import and synthetic checks passed; real impaired/matched evidence unavailable |
| DTR-A4-EVIDENCE | A4 TLS attribution and equal-run repeated-handshake inference | Real retained repeated-handshake and matched-profile acceptance | Retained attribution imported, but missing source/QoS controls blocked matching; unequal-repeat inference was synthetic. | Explicitly selected retained repeated-workload captures and comparable profile controls; offline analysis only | `tests/integration/test_analysis_domains_in.py` (extend with suitable retained evidence) | `./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/SELECTED_ANALYSIS.json --name retained-acceptance` | partially verified 2026-09-29: retained attribution import passed; real repeated/matched acceptance deferred |
| DTR-A3-MATCHED | A3 application resource comparisons | Real-evidence matched profile delta acceptance | Absolute ELF/resource import succeeded; missing source/QoS controls and differing evidence classes blocked supported matched deltas. | Retained runs with known comparable controls and explicit analysis specification; no new instrumentation | `tests/integration/test_analysis_domains_in.py` (extend retained-evidence coverage when suitable records exist) | `./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/SELECTED_ANALYSIS.json --name retained-acceptance` | partially verified 2026-09-29: 12 unique retained ELF builds imported; synthetic matched deltas and CLI/notebook equivalence pass; real matched deltas deferred for provenance gaps |
| DTR-R4-STACK | Request 4 wolfBoot stack watermark, mode isolation and mailbox v8 | Containerized wolfBoot/application build, bounded gateway/STM32 verification and OTA handoff regression | Source/fixture tests cannot measure real stack depth, RAM corruption, normal-mode interference or OTA handoff across the profile matrix. | STM32 target, Docker cross-toolchain, gateway, broker and maintained secure-boot profiles | `tests/hardware/test_secure_boot_flash_workflow_hw.py` and `tests/hardware/test_ota_dualbank_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py -m hardware --pqc-require-hardware`; profile-enabled campaign `./scripts/dev.sh experiment-gateway run --experiment <resolved secure_boot_stack case>`; then targeted OTA smoke test | deferred: full profile/normal-mode/OTA regression not established by the recorded register |
| DTR-GWLOCK | Cross-development-host gateway resource exclusion and recovery | Live multi-host contention, force-release and hardware/campaign lifecycle | Protocol tests do not establish multi-host contention, interruption, lease-loss termination and authorized abandoned-owner recovery on the live gateway. | Two Linux development machines, shared gateway SSH account, gateway Python 3 and STM32 hardware | Planned `tests/integration/test_gateway_lock_in.py` and `tests/hardware/test_gateway_lock_hw.py` | `./scripts/dev.sh gateway-lock status` from both machines; run a gated representative `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` while competing for the lock; verify forced recovery only after the old operation is stopped | deferred: unit-only protocol verification; no live gateway/multi-host evidence |
| DTR-002 | M6.2 lwIP network-interface boundary marker | Dedicated gateway-mediated known-image UART/hardware assertion | Known-image UART coverage still needs the complete local network-interface marker contract. | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-003 | M6.2.1 generated-state provenance refusal before gateway access | Hardware-workflow fixture coverage | A live refusal scenario must retain valid setup provenance and demonstrate rejection before any gateway side effect. | Updated build/signing record fixtures in the secure-boot hardware workflow | `tests/hardware/test_secure_boot_flash_workflow_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-005 | M9 live host wolfMQTT/wolfSSL validation against the gateway broker | Gateway integration and live broker compatibility | Native host build coverage does not demonstrate compatibility against the live configured gateway broker. | Gateway connectivity, broker deployment, temporary certificate provisioning, and host client execution | `tests/integration/test_mqtt_broker_gateway_e2e_in.py` | `./scripts/dev.sh pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e_in.py -m integration --pqc-require-gateway`, then the documented `host_wolfmqtt_validate.py run` command | deferred |
| DTR-007 | Classical STM32 MQTT-over-TLS profile matrix | End-to-end firmware-runtime, network, broker, gateway, UART, and hardware coverage | The socket/TLS/MQTT runtime exists; bounded workload tests are not a complete classical profile matrix. | Gateway, STM32/ST67, provisioned selected certificates, brokers and retained device/broker evidence | Planned `tests/hardware/test_stm32_mqtt_tls_hw.py`; existing `tests/hardware/test_tls_handshake_repeat_hw.py` covers only its bounded workload | After implementing the planned matrix: `./scripts/dev.sh pytest-hardware tests/hardware/test_stm32_mqtt_tls_hw.py -m hardware --pqc-require-hardware` | pending complete profile-matrix qualification; implementation support is not universal runtime acceptance |
| DTR-008 | M12 controlled network degradation / Request 8 | Live gateway/network integration, per-direction packet-path and hardware ESP32 reporting qualification | Source isolation/rollback and qdisc/MTU checks exist. Prior observations and the revised STM32 assertion rerun are tracked by DTR-014; quantitative impairment/ESP32 qualification remains distinct. | Reachable privileged gateway, independent broker veth peers, `tc`/`iproute2`/IFB/`nsenter`, exclusive gateway lease, STM32/ST67 hardware and plaintext reporting infrastructure; persistent provisioned/calibrated ESP32/INA228 and enabled energy-result acquisition for the ESP32 extension | `tests/hardware/test_reporting_plane_isolation_hw.py`, including its opt-in energy cases | `./scripts/dev.sh pytest-hardware tests/hardware/test_reporting_plane_isolation_hw.py -m hardware --pqc-require-hardware` then run an energy-enabled hardware matrix with ESP32 source/result integrity checks | partial; coordinate current STM32 assertion rerun with DTR-014; quantitative impairment and selected ESP32 matrix remain pending |
| DTR-009 | PQC/hybrid STM32 MQTT/TLS profile matrix | End-to-end firmware-runtime, broker, network, gateway, UART, and hardware coverage | PQC/hybrid runtime exists, but no maintained dedicated full-profile MQTT matrix supplies complete acceptance. | Gateway, STM32/ST67, selected provisioned PKI, compatible broker and retained negotiated-group evidence | Planned `tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py` | After implementing the planned matrix: `./scripts/dev.sh pytest-hardware tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py -m hardware --pqc-require-hardware` | pending matrix coverage/qualification; no longer blocked on absence of the runtime implementation |
| DTR-010 | ML-DSA-65 certificate authentication with hybrid ML-KEM MQTT/TLS | End-to-end STM32/server-auth and mTLS hardware verification | ML-DSA provisioning/runtime exists; complete selected server/mutual-auth qualification needs retained device and broker results. | Gateway, STM32/ST67, provisioned mldsa65 hierarchy and compatible broker | Planned `tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py` | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/tls_key_exchange/cases/<case>.yaml` followed by the mutual-auth profile | deferred: profile-specific hardware qualification |
| DTR-011 | Extended application MSP high-water and derived RAM requirement | Gateway-mediated firmware-runtime verification | Only real firmware observations can establish extended MSP watermark behavior, saturation and heap/headroom reconciliation. | Gateway, STM32/ST67 hardware, ready-metrics application, UART capture, and a completed representative MQTT/TLS workload | Planned extension of `tests/hardware/test_tls_handshake_repeat_hw.py` and representative Ready Metrics workload coverage | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/tls_key_exchange/cases/<case>.yaml` | deferred: rerun required after extended MSP watermark implementation |
| DTR-012 | Ready Metrics 2 paper-aligned MQTT application TTFB/TTLB with deferred reporting | Gateway-mediated end-to-end timing/evidence validation | The 2026-09-18 missing-buffer-record issue was fixed in source; later bounded RM2 captures do not close full selected-profile timing/packet reconciliation. | Gateway, STM32/ST67 hardware, experiment and reporting brokers, gateway transfer responder, packet capture, and the Ready Metrics 2 campaign case | `tests/hardware/test_reporting_plane_isolation_hw.py` | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/ready_metrics_2/cases/<case>.yaml` then inspect `mqtt-reporting-raw.ndjson` and capture integrity | partial; preserve historical buffer-fix context without treating later bounded captures as complete timing/profile qualification |
| DTR-013 | Passive STM32/ESP32 energy acquisition acceptance | Gateway/hardware robustness | Recorded normal passive application, repeated-TLS and bare-metal acquisitions passed with endpoint integration. Stale capture and publication-timeout recovery still need live fault injection. | Gateway, STM32/ST67 and provisioned ESP32/INA228 | `tests/hardware/test_energy_capture_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_energy_capture_hw.py --pqc-require-hardware` | partial: 2026-09-30 recorded two passing runs each for application/repeated TLS/bare-metal with 20 ms tail; fault recovery pending |
| DTR-014 | Request-15 impairment-exempt reporting plane under rate, RTT, loss and MTU | Live gateway/network/hardware validation | Prior runs retained all four applied impairments, cleanup and STM32 streams, but transient-manifest assertions failed. Revised persistent-evidence checks still need a live rerun. | Reachable gateway with non-interactive `tc`/`ip`/`modprobe`/`nsenter`, running experiment/reporting brokers, STM32/ST67 and four resolver-generated impairment cases | `tests/hardware/test_reporting_plane_isolation_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_reporting_plane_isolation_hw.py -m hardware --pqc-require-hardware` | partial: 2026-10-11 small-MTU cases (400/576/768 bytes) passed all 3 gateway-mediated hardware checks, including persistent STM32 reporting evidence, applied state and restoration; full rate/RTT/loss and ESP32 matrix remains pending |
| DTR-015 | Request-13 1 MHz application timing timebase and reset-origin handoff | Representative gateway/hardware timing validation across plaintext, classical/hybrid TLS, server/mutual auth, Ready Metrics and Ready Metrics 2 | The dedicated delay test established the derived 1 MHz timer, 10985 us for a requested 10 ms and 11 ms HAL advance with successful wolfBoot verification and application startup. Full workload/profile timing and handoff qualification remains. | Reachable gateway, STM32/ST67 hardware, reporting/experiment brokers as required by the selected cases, and the maintained representative workload/profile matrix | `tests/hardware/test_application_timebase_hw.py` plus the maintained workload hardware tests | `./scripts/dev.sh pytest-hardware tests/hardware/test_application_timebase_hw.py -m hardware --pqc-require-hardware`, then run the maintained self-contained hardware/profile tests for plaintext, classical/hybrid TLS, server/mutual auth, Ready Metrics and Ready Metrics 2 | partially complete: 1 MHz hardware self-test passed; representative profile-matrix evidence still required |
| DTR-016 | Independent Ready Metrics 2 reliability runner | Real destructive Docker reset/rebuild, certificate provisioning and sequential gateway/STM32 trials | Command-double tests do not establish actual local Docker purge/rebuild, provisioning and sequential hardware trials. | Dedicated idle Linux lab checkout/daemon, sudo, network access for image builds, configured gateway/SSH/Wi-Fi and STM32/ST67 | `tests/integration/test_ready_metrics_2_reliability_in.py` for process coverage; disposable-host acceptance via the runner | `./scripts/dev.sh pytest tests/integration/test_ready_metrics_2_reliability_in.py -m integration`, then on the dedicated host `python3 scripts/ready_metrics_2_reliability_v2.py --runs 3 --execute` and inspect each manifest/UART plus summary | deferred: real Docker and hardware acceptance pending; simulated process coverage only |
| DTR-BOOT-MAILBOX | Selected-image mailbox v8 and deferred secure-boot reporting | Full profile, corrupt-image and reset/OTA retention qualification | Focused tests do not establish every selected-image, corrupt-candidate, freshness and reset/OTA retention path. | Matching bootloader/application builds, gateway, STM32/ST67 and brokers | `tests/hardware/test_secure_boot_flash_workflow_hw.py`, `tests/hardware/test_ota_dualbank_hw.py`; planned `tests/hardware/test_secure_boot_mqtt_evidence_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py tests/hardware/test_ota_dualbank_hw.py --pqc-require-hardware`; extend reporting coverage | deferred: focused tests do not close complete profile/retention coverage |
| DTR-BAREMETAL | Pre-scheduler ML-DSA-65 measurements and TLS isolation | Strict primitive hardware acceptance and separate regular-TLS regression | Software tests do not qualify every selected primitive, cycle interval and transition back to ordinary TLS/reporting. | Gateway, STM32/ST67, benchmark workload and retained result stream | `tests/hardware/test_baremetal_benchmark_hw.py`, `tests/hardware/test_tls_handshake_repeat_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baremetal_benchmark_hw.py tests/hardware/test_tls_handshake_repeat_hw.py --pqc-require-hardware` | deferred: migrated from the former architecture benchmark note; no new hardware acceptance asserted |

### Closed or retired contracts

Retained for traceability; these rows do not request reimplementation.

| ID | Feature | Missing test layer | Reason | Required capability or phase | Intended test file | Eventual verification command | Status |
|---|---|---|---|---|---|---|---|
| DTR-A1-CONTAINER | A1 offline timing export and typed loader | Post-correction Docker-hosted documentation and full unit regression | The old upload-session documentation failure was superseded by the recorded Docker regression. | Complete Linux development checkout and rebuilt Docker Python image; no gateway, credentials or hardware | `tests/unit/test_timing_dataset_documentation.py`, `tests/unit/test_documentation_integrity.py`, `tests/unit/test_docker_default_workflow_docs.py` and `tests/integration/test_timing_dataset_in.py` | `./scripts/dev.sh pytest tests/unit`; `./scripts/dev.sh pytest tests/integration/test_timing_dataset_in.py -m integration` | closed during A2: 2026-09-28 Docker full unit regression passed, including A1 and documentation tests; A1 local integration rechecked |
| DTR-001 | M6.1 wolfSSL TLS-context lifecycle marker | Retired local-context UART assertion | The old local wolfSSL context callback/marker was removed. Current TLS workload acceptance is separately tracked. | Current TLS workload capture for any new runtime claim | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | retired: obsolete marker contract; TLS profile acceptance remains under DTR-007/DTR-009/DTR-010 |
| DTR-004 | M6.3 wolfSSL legacy transport-boundary self-test marker | Retired startup transport-marker assertion | Current startup does not invoke the legacy unavailable-transport self-test; its marker cannot describe live TLS. | Current TLS workload capture for any new runtime claim | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | retired: obsolete startup-marker contract; runtime transport acceptance remains separately tracked |
| DTR-006 | M10 ST67W61M1 association and DHCP | Hardware coverage | The baseline hardware test now requires association/DHCP pass markers and a nonzero IPv4 address. | Installed ST67W61M1 hardware, configured access point, gateway/UART access, and experiment-supplied credentials | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | retired: coverage implemented; external TCP/TLS/MQTT remains separately deferred |

### Passive AP diagnostics (14 October 2026)

DTR-AP-RF: unit and process-boundary checks cover safe read-only command selection,
missing counters, channel changes and counter reset handling. Physical UniFi
AC-Mesh SSH and legacy driver capability checks passed on 14 October 2026.
The target station was identified on the selected 2.4 GHz interface. The driver
reports disabled channel-utilisation/PER fields and native RSSI, so complete
metric semantics and RF-validity qualification remain open. The `unifi` backend
retains the supported radio/station evidence without changing radio settings. Run `python3 scripts/wireless_environment.py --ssh-host pqc-ap --samples 12
--interval 5 --context capability-check --output results/wireless/capability-check`
from the framework root. Required follow-up: verify radio identity, station MAC,
counter semantics and temporal overlap with retained experiment runs before any
RF-validity claim. A successful SSH command is not successful metric acquisition.
DTR-MLDSA-MEMORY: all six default/small-memory server/mutual configurations passed
gateway-mediated hardware qualification on 14 October 2026 after adapting scratch
routing for the experimental modes. Fixed-count pilot analysis and reduced-pool
validation remain pending. See [the experiment plan](mldsa_memory_experiment.md).

The regional RAM-demand estimate and separate configured reservations are derived offline; reduced-memory runtime,
startup/boot coverage and production overhead removal remain unvalidated.


### Interactive migration CLI

DTR-MIGRATION-AB: unit tests cover profile choices, signed/scaled deltas, missing
values, control matching, session recovery and isolated queue export. The process
integration test drives the actual interactive CLI, SQLite queue, helper and
worker processes with synthetic captures, then verifies export, report and resume.
`tests/hardware/test_migration_hw.py` prepares fresh plaintext and PQC mutual-TLS
profiles, runs one attempt each through the gateway and verifies the retained
comparison. Run `./scripts/dev.sh pytest tests/unit/test_migration.py
 tests/integration/test_migration_in.py` and `./scripts/dev.sh pytest-hardware
 tests/hardware/test_migration_hw.py --pqc-require-hardware`. The bounded hardware
gate passed on 2026-10-14: one fresh plaintext capture and one ML-KEM-768 /
ML-DSA-65 mutual-authentication capture, with verified RAM, Flash and application
timing deltas. Evidence is retained in
`results/migrations/migration_20261014_045939_58b5caa4/`. Process tests also cover
resume without duplicate jobs, retained failures and output tampering; the LaTeX
integration test compiles both generated table inputs. This qualifies the A/B
workflow, not every selectable algorithm/impairment combination or its statistical
precision. Existing component gates and missing-value policies still apply.

Optional ML-DSA memory choices are covered by campaign-editor save/validation tests,
wizard applicability and unchanged-choice tests, resolved compiler-option checks,
legacy-session handling and treatment matching. The CLI process test also compares
default mutual ML-DSA against `both_small` and checks the frozen profiles and report.
Run the focused hardware gate with `./scripts/dev.sh pytest-hardware
tests/hardware/test_migration_hw.py -k mldsa_memory --pqc-require-hardware`.
This gate passed on 14 October 2026: one default and one `both_small` mutual-TLS
attempt completed, with verified export, LaTeX output and RAM/Flash/timing deltas.
Evidence is retained in `results/migrations/migration_20261014_103840_bf00ae72/`.
The existing 30-attempt-per-state session
`results/migrations/migration_20261014_161018_e25c174a/` also passed read-only
verification with the updated tool. These checks qualify selection/report plumbing;
they do not replace the fixed-count memory-option pilot or reduced-pool validation.

### Preconnected workload responder and TLS implementation factors

The `preconnected_broker_namespace_mosquitto_v2` responder uses the same native
gateway MQTT clients inside the selected broker network namespace for every
target protocol. A loopback ACL probe and three acknowledged connections precede
target reset. `tests/integration/test_mqtt_responder_in.py` checks persistent
publishing and absent-message outcomes against an isolated gateway broker;
`tests/unit/test_responder_eligibility.py` checks the comparison rules. Earlier
process-startup delivery measurements and impaired v1 host-loopback captures
remain excluded, while qualified unimpaired v1 and pre-request observations
retain their stated boundaries.

On 14 October, the updated hardware gate completed plaintext and ML-KEM-768 /
ML-DSA-65 mutual-TLS captures in
`results/migrations/migration_20261014_112619_73cf74c7/`. Earlier bounded gates
completed default versus compact/small signing-and-verification ML-DSA mutual
authentication (`migration_20261014_111255_133c5637`) and ML-KEM compact/memory
options (`migration_20261014_111704_616ae020`). These are functionality checks,
not performance estimates or qualification of every grid combination.

The enlarged 48 KiB task stack could not start with the original 96 KiB shared
heap (`migration_20261014_113001_58d7b19f`). Large-stack selections therefore
require an explicit 128 KiB heap; both allocations must be held constant to
isolate the small-stack implementation flag. Defaults remain 8 KiB and 96 KiB.
Link-time fit and runtime watermarks are still required for each new configuration.
Run `./scripts/dev.sh pytest-hardware tests/hardware/test_migration_hw.py
-k stack_options --pqc-require-hardware` for that bounded comparison. It passed
with the 128 KiB pool on 14 October: one attempt per setting, including preparation,
export and RAM/Flash/timing deltas, retained in
`results/migrations/migration_20261014_113820_2c114abd/`.

Replacement collection is recorded in
`results/analysis/plans/responder-remediation-20261014/plan.json`. It preserves
raw captures, links selected batches to fixed-count replacements and retains
unaffected boot, primitive and pre-request evidence. Publication must use a new
report revision and must not subtract an estimated Docker startup constant.


The v1 host-loopback responder did not isolate local clients from the experiment
veth during impairment. The v2 correction passed three isolated gateway cases
(success, no request and missing workload-ready message) with 100% loss and MTU
400 on the broker's external interface. Payload delivery over namespace loopback
remained intact. Run this gate with `./scripts/dev.sh pytest-gateway
tests/integration/test_mqtt_responder_in.py --pqc-require-gateway`.

On 15 October, both plaintext and TLS total-loss/reference recovery hardware
cases passed in `tests/hardware/test_negative_trial_hw.py`, retaining valid
negative trials and successful reference attempts in
`results/automated-tests/pytest-2026-10-14T232846Z-1/`. A fresh plaintext-to-PQ
mutual-authentication A/B gate also passed, including export and comparison
verification, in `results/migrations/migration_20261014_234003_f1ca120e/`.
These checks distinguish cleanup safety, feeder completion and firmware-reported
failure; they do not qualify every impairment or algorithm combination. An earlier
A/B test stopped before flashing when a concurrent pytest session cleaned signing
objects; its preparation evidence remains retained. Run pytest sessions serially
when one owns firmware preparation, because session-start cleanup affects shared
generated build objects.

### ML-DSA-44 TLS authentication qualification

The authentication grids include ML-DSA-44 server and mutual roles with P-256
key establishment. `test_mldsa44_tls.py` checks all supported key-establishment
selectors, parameter-set isolation, role-specific signing and expected timing
labels. Native ML-DSA tests exercise levels 2 and 3 with the regular and
small-memory signing paths; recorder tests check exact count/event linkage.
The host broker check includes the new certificate hierarchy.

Target qualification uses a bounded, separately frozen queue selection at the
working-source fingerprint: three baseline Ready Metrics 2 runs per ML-DSA-44
role, then one ML-DSA-65 run per role because the level-aware hooks are shared.
Preparation captures are separate. The checks require successful payload delivery,
correct certificate/signature scheme, complete timing events, firmware/source
identity, packet corroboration and normal gateway cleanup. These captures do not
establish performance distributions or qualify every key-exchange, memory option,
impairment or repeated-handshake combination. The qualification plan and observed
status are retained under `results/analysis/plans/mldsa44-qualification-20261019`.
The full campaign remains paused pending verification and a new source freeze;
completed unaffected runs are retained without replacement.

The initial ML-DSA-44 mutual preparation and a separate full-UART diagnostic
failed before measurement runs; the diagnostic reported a FreeRTOS allocation
failure. The 29 KiB default verification buffer now routes to the reserved RAM3
workspace. Native allocator tests cover both parameter sets, capacity bounds and
exclusive ownership. Fresh ML-DSA-44 qualification must validate this route; the
initial failed preparations remain retained and are not counted as successes.

### Authentication 300-slot source freeze

The five-family authentication campaign now declares 30 attempts in each of ten
conditions. `test_mldsa44_tls.py` checks the budget, common P-256/network/workload
controls and hierarchy shape; `test_thesis_tables.py` and `test_analysis_workspace.py`
check skewed timing distributions, missingness, median/IQR figure agreement and
separate ten-run boot / three-run stack summaries. The compact exporter retains
supplementary means/CV without making them the principal latency statistic.

| Feature | Missing layer | Reason | Required capability | Intended check / command | Status |
|---|---|---|---|---|---|
| Five-family 300-slot authentication study | Current-source hardware qualification and collection | Audit review and committed clean-source freeze pending; queue explicitly held | Gateway, STM32/ST67, provisioned five-family broker identities and configured energy instrument | Existing qualification procedure above; after freeze use `./scripts/dev.sh pytest-hardware tests/hardware/test_thesis_baselines_hw.py --pqc-require-hardware` before separately approved collection | Deferred; prior captures are historical evidence only |

## DTR-BROKER-TCP-NODELAY

- Feature: process-wide experiment broker TCP_NODELAY; reporting is unchanged.
- Coverage: unit resolution, identity, editor, frozen-plan, retained-config analysis
  and cleanup checks; local Docker OFF/ON/OFF recreation and mutual-TLS readiness
  in `test_tcp_nodelay_recreates_broker_and_retains_generated_config`.
- Missing layer: matched STM32 qualification for impaired networks, mutual TLS and
  workloads beyond the bounded server-authenticated Ready Metrics 2 pilot.
- Reason: the initial intervention is deliberately limited to baseline network,
  ECDSA P-256 server authentication and five attempts per arm/scheme, energy OFF.
- Required capability: available gateway lease, provisioned credentials and board;
  impairment additionally requires the maintained network-control capability.
- Intended test: fixed-attempt matched profiles with identical firmware per pair,
  indexed effective broker configuration and decrypted packet evidence; never
  extend a pilot until a desired success count appears.
- Command: `./scripts/dev.sh pytest tests/unit/test_broker_tcp_nodelay.py`;
  `./scripts/dev.sh pytest tests/integration/test_mqtt_broker_docker_runtime_in.py -m integration`;
  subsequent authorized profiles use `./scripts/dev.sh campaign-gateway <profile>`.
- Status: broader workload/network qualification deferred. Local broker validation
  does not establish STM32 behavior or socket-level attestation.
