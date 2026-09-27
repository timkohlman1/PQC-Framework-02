# ESP32 / INA228 Energy Instrument

## Extraction scope

This guide and the instrument source were imported from commit
`7a25e8fc507f23a5346dfa6014087be05fab81bd` as the baseline for rebuilding
the surrounding integration. The original guide below is retained as a
historical reference. Its STM32, collector, campaign, configuration-profile,
and end-to-end hardware-test descriptions do not establish functionality in
this branch; those components have not been imported with the device.

The extracted device-only tests are:

```bash
./scripts/dev.sh pytest tests/unit/test_esp32_energy_instrument_source.py
./scripts/dev.sh pytest tests/integration/test_esp32_energy_native_in.py -m integration
```

The source checks inspect only instrument firmware and configuration. The
native tests compile and exercise the ESP32 recorder with SDK/device doubles
and syntax-check the sensor adapter against the pinned SparkFun APIs. No
STM32, host collector, broker, GPIO device, Wi-Fi credentials or physical
instrument is needed. They do not validate an ESP-IDF target build, real
cryptography, acquisition rate, calibration or physical hardware operation.

## Purpose

This guide owns the setup and operational contract for the persistent ESP32-S3 / SparkFun INA228 energy instrument used by the experiment framework. The acquisition electronics are laboratory instrumentation, not target firmware: they are provisioned manually, remain powered between experiment runs, and are not reflashed or reset by normal campaign execution.

The instrument measures the external regulated 5 V rail feeding the NUCLEO-L4R5ZI-P target and ST67 expansion through E5V. ST-LINK USB and the ESP32/INA228 acquisition electronics remain outside the measured power domain.

## Target power setup

For the maintained NUCLEO setup:

- fit JP6 across pins 1-2 to select E5V;
- remove JP1;
- apply the external E5V source before attaching ST-LINK USB during initial laboratory setup;
- retain ST-LINK USB for debugger/SWD/UART power and signalling only; and
- do not route the measured load return current through the INA228 logic-ground lead.

These are physical setup requirements. Normal campaigns may health-check the instrument and evidence, but do not move jumpers or manage the ESP32 firmware lifecycle.

## INA228 power-path wiring

The maintained high-side connection is:

```text
external 5 V (+) -> INA228 IN+
INA228 IN-        -> target/load (+)
INA228 VBUS       -> same load-side positive node as IN-
external 5 V (-)  -> target/load GND
INA228 GND        -> common signal/reference GND
ESP32 GND         -> common signal/reference GND
```

IN- is not ground. The measured load current flows from IN+ through the breakout shunt to IN-. VBUS senses the load-side bus voltage.

## Sensor library and calibration identity

The firmware uses the pinned SparkFun INA2XX driver and SparkFun Toolkit submodules rather than project-local INA228 register-scaling code. The breakout is marked R015 and is retained as a nominal 15 mOhm hardware identity.

Reference-load checks on the maintained instrument showed that using the nominal 15 mOhm value over-reported current by approximately a factor of two. An empirical effective calibration value of 29 mOhm is therefore used by the current firmware. This is intentionally recorded separately from the nominal shunt value.

The current calibration status is laboratory/empirical, not traceable metrology. The maintained checks performed before this integration included bus-voltage comparison and two known resistive loads, including a measured 300.8 ohm load for which the series DMM reference was approximately 17.05 mA and the calibrated firmware reported approximately 16.9-17.0 mA. Do not reinterpret the nominal R015 marking as the calibrated value.

## Persistent framework service

The ESP32 connects opportunistically to the dedicated plaintext, impairment-exempt reporting broker. No experiment TLS credentials are provisioned to the instrument, and reporting-broker availability is **not** an acquisition prerequisite.

INA228 acquisition starts when the persistent ESP32 firmware boots. Every valid sensor sample is timestamped on the continuously running ESP32 microsecond clock and copied into a circular buffer allocated from external PSRAM. The default sample-ring target is 7 MiB on the 8 MiB board. Interval descriptors are allocated first; the ring is then capped by the target, the largest contiguous PSRAM block and free PSRAM minus 512 KiB of headroom. Allocation is rounded down to whole records. Actual allocation, record size, capacity, detected PSRAM and reserved headroom are reported; the configured target is not a claim of actual allocation. When the ring becomes full it overwrites the oldest samples; an interval that references overwritten samples is rejected rather than silently truncated.

## Interval boundaries and raw clock correlation

Wire STM32 D8/PF12 to ESP32 GPIO11, INA228 active-low conversion-ready
ALERT to GPIO12, and common signal ground. Both inputs use 3.3 V logic.
PF12 rising starts an interval; falling ends it. The ESP32 uses its continuous
`esp_timer_get_time()` clock without resetting it at an interval boundary.

STM32 `PQC_EnergyBoundaryBegin/End` read the extended TIM2 1 MHz timebase
immediately **before** the corresponding PF12 BSRR write, with interrupts
briefly masked and the previous PRIMASK restored. Only after falling does
`PQC_EnergyBoundaryAppend` serialize `PQC_ENERGY_BOUNDARY` into the existing
hashed STM32 result stream. It retains `s0_us`, `s1_us`, interval index,
clock identity/frequency, timestamp convention and validity. Ordinary workloads
retain the existing interval around application execution (including network
bring-up). Repeated TLS workloads delimit each iteration separately, ending
before formatting and reporting; they retain one STM32 result epoch per iteration.

Schema 2 and 3 energy interval records retain raw ESP32 `e0_us` and `e1_us` plus
`stm32_boundary_source=stm32.energy_boundary`. S0/S1 and E0/E1 remain in
their respective hashed raw streams, joined by the collector run ID and
zero-based `interval_index`. They are not estimated from MQTT or UART arrival
times. The former permanently false `stm32_start_valid/stm32_end_valid` fields
are replaced by this explicit cross-source contract. Missing STM32 pairs fail
capture acceptance. No additional GPIO pulses per operation are required.

Offline analysis can map the existing STM32 operation timestamps with:

```text
E(S) = E0 + (E1-E0)/(S1-S0) * (S-S0)
```

Two points determine offset and linear rate error. They cannot quantify
nonlinear drift or GPIO/ISR latency; validate those separately. Capture checks
ordered boundaries, matching interval counts and a broad duration-consistency
limit (1% of the STM32 interval or 2 ms, whichever is larger). That check is
not a clock calibration or a timing-accuracy claim. No affine coefficients,
per-operation energy, integrated energy totals, or scientific metrics are
calculated or inserted into the run manifest during capture.

## Persistent collection and association

An energy-enabled collector publishes a fresh 128-bit association token before
STM32 execution, then checks a fresh acknowledgement carrying that exact token,
valid recent sensor data and an allocated ring. An old retained status cannot
satisfy this check. The instrument snapshots the token in the rising-edge ISR.
A new token is refused during an active interval or collection. Energy-enabled
runs fail preflight if the appliance cannot acknowledge healthy acquisition;
energy-disabled runs and preparation do not require this capability. Failure
after execution rejects capture separately from STM32 workload outcome.

After the workload, the collector requests the exact token and expected interval
count (one normally, the selected handshake count for a repeated TLS workload).
Only matching completed intervals may be claimed. **Unlabeled fallback is
disabled**: a single leftover preparation interval is not proof of run identity.
Preparation cases suppress instrument capture and do not publish a measurement
token or claim candidate intervals; they retain the build's energy capability.
Supported runs contain 1–32 intervals. Ring retention is finite: collect before
samples wrap. Long multi-interval runs can exceed it and must fail explicitly.

Only a post-run collect can pause acquisition. Before acknowledging the pause,
the service requires a retained sample after the last falling edge. It never
pauses between repeated TLS handshakes. The frozen ring remains stable during
transfer; acquisition resumes after success, failure, cancellation or timeout.
Resuming resets the intentional pause's timestamp baseline, so it does not
become a sensor gap fault. Genuine in-run gaps remain failures. The live display
labels this state as paused for transfer.

Completed traces use bounded sequenced QoS1 chunks with one outstanding chunk,
followed by a completion containing logical SHA-256, byte/record/chunk counts,
interval/sample counts and raw acquisition status. Every chunk checks the
physical sync input as well as acquisition state. The framework serializes
collection before the next run, so no bulk ESP32 publication is scheduled
during a measured interval. An unexpected rising edge during publication aborts
further chunks and invalidates the overlapping interval; packets already
submitted cannot be retracted. Hardware acceptance must verify this scheduling
and the physical boundary on the reporting path.

Schema 3 uses compact sample arrays with the ordered `sample_fields` declared
in the initial session record. Every previous raw sample field is retained;
voltage/current/power retain the same nine-significant-digit serialization.
Chunks carry `data_b64` instead of hexadecimal text. Hashes and byte/record
counts cover the exact decoded newline-delimited bytes, before normalization.
The collector still accepts historical schema 2 / hexadecimal evidence. It
validates schema 3 arrays using the declared fixed column order. No fitted
clock, integrated energy or per-operation attribution is generated.

Each 4096-byte logical chunk fits, including base64 expansion and its envelope,
in the 8192-byte MQTT output buffer. This avoids fragmenting a large publish
across the former default buffer. Completion records expose chunk payload bytes,
time spent publishing/acknowledging chunks, and elapsed collection time up to
completion creation (excluding its own acknowledgement). These are operational
transport counters, not scientific results. Actual new throughput remains a
hardware verification requirement.

Post-run collection has a bounded 180-second completion deadline. A recorded
8.53-second interval was still transferring after the previous 60-second limit;
raising the deadline does not extend ring retention or relax hash/count checks.
The firmware also limits each collection to 300 seconds, with bounded 5-second
network operations and PUBACK waits; host cancellation is checked between
chunks and during acknowledgement waits. These limits do not guarantee that a
near-full ring transfers in 180 seconds on every network. Increase the profile's
completion deadline up to the host's 300-second cap when measuring long runs,
and establish a practical transfer limit from actual completion counters.

An incomplete or invalid required result collection rejects capture acceptance,
even when the raw file itself was retained successfully. STM32 execution outcome
remains a separate field. The hardware test resolves its repeated-TLS workload
through the campaign matrix and checks the expected epoch count before deployment.

The collector retains `mqtt-reporting-raw.ndjson` as both `stm32_result_stream`
and `energy_result_stream`, validates envelope integrity and raw completeness,
and only then allows broker teardown. A captured file alone does not establish
valid energy evidence. Wrong tokens, missing/duplicate boundaries, overwritten
samples, gaps, sensor/sync faults, calibration/configuration mismatch and
count/hash failures reject capture. Failed traces remain raw evidence.

## Finite retention and capacity failures

`capacity_samples = ring_allocated_bytes / sample_record_bytes`. The maintained
ESP32 record is 64 bytes; a full 7 MiB allocation holds 114688 samples. Actual
session/status metadata is authoritative if compiler layout or allocation changes.
At an **observed** 717 samples/s this is approximately 160 seconds; at 520
samples/s it is approximately 221 seconds. These examples are not a new rate
measurement or a guaranteed duration. Leave margin for both bracketing samples,
variation in sample rate and collection startup.

Retention covers the time from the first required sample until the post-run
pause, including gaps between intervals and STM32 reporting/teardown delays.
It is not merely the sum of measured interval durations. After the pause, transfer
time no longer consumes retention. Normal background ring wrapping is expected.
If this run's first required sample has already been overwritten, the appliance
emits a terminal `type=error`, `status=capacity_exceeded` record on the run's
`/complete` topic. It includes capacity, allocated bytes, record size, retained
sample sequence bounds and retained span. This is not a successful completion.
The collector stops waiting, retains the error and any partial raw stream,
rejects energy capture and preserves any independently valid STM32 stream.
An overwritten interval belonging to an older token cannot invalidate a new run.

Status/session records expose `retained_span_us` as raw buffer coverage. A ring
may span an earlier deliberate collection pause, so do not infer a guaranteed
future retention limit from that span. Use actual sample spacings within a
continuous interval for rate estimates. Offline tools must read schema 3's
`sample_fields` before interpreting compact sample arrays.

## Acquisition rate and retained quality evidence

The I2C bus shared with the touch controller remains at 400 kHz. The sensor uses
back-to-back **triggered bus+shunt conversions**, each set to 50 us with averaging
1. Continuous acquisition means the acquisition task and PSRAM ring run from
boot, except during post-run transfer; it does not require the INA228 ADC continuous-conversion mode. ALERT
provides each completed-conversion timestamp. The task reads diagnostic flags,
bus voltage, calibrated current and sensor power through SparkFun, retains the
snapshot, then triggers the next conversion. Registers therefore remain stable
through the read. This avoids mixing values from successive continuous
conversions. The sensor's hardware energy accumulator is not used in triggered
mode. Per-sample and interval energy integration belongs to offline analysis.

The previous redundant shunt-voltage read and per-sample integration/logging are
removed. I2C command links use bounded local storage instead of per-transaction
heap allocation. Re-triggering reuses the SparkFun ADC configuration bitfield
read back after setup and performs a single write, avoiding a redundant
configuration read for every sample. No faster shared-bus speed or achieved 2000 Hz rate is assumed.
The 100 us ADC-only cycle is **not** the acquisition period: I2C, touch activity,
RTOS scheduling and retention add time. This is the fastest configured ADC
setting with coherent read-before-retrigger handling; only a hardware sweep
can establish the maximum sustainable acquisition rate on this appliance.
The earlier roughly 520 Hz trace is user-reported baseline evidence, not a
measurement of this replacement firmware.

Each raw sample retains its sequence, absolute ALERT timestamp, signed relative
time, bus/current/power values, I2C read duration and diagnostic/status flags.
Intervals include one retained sample on each side of the boundary for later
offline boundary treatment; no interpolation occurs during capture. Cumulative
I2C-error, ALERT-timeout, coalesced-alert, timing-error, saturation and sample-gap
counters are differenced over these bracketing samples. Any increment rejects
the interval. The explicit gap threshold is 10 ms; it is not a rate target.
Sync queue drops and unexpected edges also prevent acceptance. Samples are
located by their timestamps, not by the delayed edge worker's execution time.

Retain sample count, first/last timestamps and all spacings when assessing rate
offline; report `(N-1)*1e6/(t_last-t_first)` with gap and error counts. Never
substitute nominal conversion settings for that evidence. Session metadata
retains a boot-session identity, firmware ELF SHA-256, configuration values,
calibration identity and empirical calibration status. Empirical calibration
is permitted and explicitly distinguished from traceable metrology.

## Live display

The `Live` page shows raw voltage/current/power, sample count and a bounded
rolling power graph. The `Session` page shows recorder/buffer/publication status.
Neither page defines experiment boundaries or calculates scientific energy.

## Configuration

The instrument profile is `configs/instruments/energy/esp32_ina228.yaml`. Selecting:

```yaml
instruments:
  energy: esp32_ina228
```

makes energy evidence independently required for that resolved experiment. Timing, memory and TLS instrumentation remain separately controlled and are not implied or disabled by the energy selection.

The ESP32 local `sdkconfig` owns laboratory Wi-Fi credentials and must remain uncommitted. Non-secret defaults such as reporting-broker host/port, client ID, sensor initialization retry period and continuous PSRAM ring size are exposed through `main/Kconfig.projbuild`.

Hardware campaigns that need gateway access must be launched through the gateway-capable wrapper, for example:

```bash
./scripts/dev.sh python-gateway scripts/run_campaign.py baseline_energy.yaml
```

## Verification and pass criteria

Run from the repository root:

```bash
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh pytest tests/integration -m integration
./scripts/dev.sh pytest-hardware tests/hardware/test_energy_capture_hw.py -m hardware --pqc-require-hardware
./scripts/dev.sh python-gateway scripts/run_campaign.py baseline_energy.yaml
```

The energy hardware test owns broker setup, canonical case resolution, STM32
build/preparation/flash, two repetitions each of single- and two-interval
workloads, capture validation and temporary-configuration cleanup. Gateway,
UART, flash and the manually provisioned persistent instrument are laboratory
capabilities. It neither builds nor resets the ESP32. A missing capability
skips in an ordinary run and fails under `--pqc-require-hardware`.

Unit/native integration gates must pass. A skip is not hardware evidence.
Campaign acceptance requires finalized manifests, accepted capture, both raw
stream roles, complete matching S/E pairs, exact token association, valid
hash/count/completion, positive monotonic sample timing and zero acquisition
error counters. Energy-disabled campaigns and preparation must remain runnable
without claiming energy. The native tests use SDK/device doubles; they are
not an ESP-IDF target build or a hardware rate test.

After applying firmware source changes, explicitly perform manual appliance
maintenance in an ESP-IDF 5.5 environment; normal campaigns never do this:

```bash
cd /home/timk/rmit/PQC-Framework-02/instruments/esp32_ina228
idf.py build
# Set this to the physical ESP32 serial-by-id path before running maintenance.
ESP32_PORT=/dev/serial/by-id/YOUR_ESP32_DEVICE
idf.py -p "$ESP32_PORT" flash
# Reconnect peripherals and leave the appliance powered. Validation uses MQTT;
# startup UART access is not required.
```

Existing local `sdkconfig` files may still contain the retired
`CONFIG_PQC_ENERGY_RING_BYTES` setting. `idf.py reconfigure` loads the new
`CONFIG_PQC_ENERGY_RING_MAX_BYTES` and `CONFIG_PQC_ENERGY_PSRAM_RESERVE_BYTES`
defaults; check their non-secret values before building. Do not share the full
`sdkconfig`, which can contain Wi-Fi credentials. Firmware and host collector
must both be updated for schema 3 and the fresh readiness acknowledgement.

The previously retained repeated-TLS hardware preparation stalled before any
STM32 result epoch. Its cause is not established by the energy transfer fix.
This patch does not change ST67/lwIP behaviour. If preparation still fails,
retain its UART, subscriber, manifest and collector evidence as a separate
network/startup issue; do not claim Request 6 hardware completion.

Before thesis use, retain calibration validation separately from finalized run
capture: actual breakout/shunt identity, a no-load zero-offset check, DMM bus
voltage, at least three known loads spanning the intended range, reference
uncertainties, and a timed constant-load trace. Integrate only in an offline
analysis output with input hashes, tool version, parameters and output hashes;
compare against independently measured power and elapsed time. Do not upgrade
the empirical calibration status without that evidence. Verify GPIO timestamp
latency and absence of reporting chunks inside the measured boundary with a
logic analyzer and reporting capture. Repeat sustained acquisition with the
normal display/Wi-Fi load, including broker outages and buffer exhaustion.
These physical/calibration/rate gates cannot be replaced by unit tests.

Technical references: [TI INA228 datasheet](https://www.ti.com/lit/ds/symlink/ina228.pdf)
(ADC/ALERT behavior) and [ESP-IDF 5.5 legacy I2C implementation](https://github.com/espressif/esp-idf/blob/v5.5/components/driver/i2c/i2c.c)
(static command-link transport). The pinned SparkFun driver still owns scaling.

MQTT buffer configuration reference: [ESP-MQTT / ESP-IDF 5.5](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/protocols/mqtt.html).
