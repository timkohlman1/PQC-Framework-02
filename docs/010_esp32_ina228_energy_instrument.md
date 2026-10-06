# ESP32-S3 / INA228 passive energy instrument

## Purpose

The ESP32-S3/INA228 is a persistent, manually provisioned measurement appliance.
It is intentionally outside the experiment control plane. The STM32 exposes one
GPIO window for the complete measured workload; the ESP32 observes that window,
retains raw samples around it, and publishes the completed capture through the
impairment-exempt plaintext reporting broker.

The appliance does **not** receive experiment commands over MQTT. It does not
know the experiment run ID, workload name, TLS algorithm, handshake number, or
TIM2 timestamps. Those semantics remain in STM32/framework evidence and are
joined offline using the two GPIO edges.

Selecting the instrument remains optional:

```yaml
instruments:
  energy: esp32_ina228
```

Normal campaigns never build, flash, reset, or reconfigure the ESP32.

## Hardware boundary

The maintained wiring is:

- STM32 D8/PF12 -> ESP32 GPIO11: 3.3 V experiment-window signal.
- INA228 ALERT -> ESP32 GPIO12.
- shared ESP32 I2C: SDA GPIO48, SCL GPIO47, 400 kHz.
- reporting transport: plaintext MQTT on the dedicated reporting broker.

PF12 is configured LOW during STM32 energy-boundary initialization. Immediately
before asserting PF12 HIGH the STM32 records `s0_us` from the maintained 1 MHz
TIM2 timebase. Immediately before deasserting PF12 LOW it records `s1_us`.
The retained marker is:

```text
PQC_ENERGY_BOUNDARY scope=experiment s0_us=<...> s1_us=<...> workload_end_us=<...> tail_guard_ms=20 valid=1 clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write
```

There is one GPIO HIGH interval per experiment. Repeated TLS therefore does not
pulse the GPIO once per handshake. Existing TIM2 TLS/benchmark instrumentation
continues to describe internal sub-intervals; offline analysis projects those
TIM2 intervals onto the one ESP32 trace.

## ESP32 acquisition lifecycle

The appliance starts INA228 acquisition at boot and continuously writes raw
samples into a PSRAM circular buffer. MQTT connectivity is not required for
sampling.

On GPIO11 rising edge the ESP32 records `e0_us` from `esp_timer_get_time()` and
opens a capture. Acquisition continues normally throughout the measured HIGH
interval. On the falling edge it records `e1_us` first, closes the measured
interval, and then requests the INA228 acquisition task to pause. The pause waits
for any in-flight sample to finish; samples later than `e1_us` are excluded when
the capture range is selected.

The STM32 records `workload_end_us` when application work finishes, then waits
20 ms before recording `s1_us` and lowering PF12. The GPIO timestamps still define
the two-edge clock mapping. Whole-workload energy ends at `workload_end_us`,
excluding this tail guard; the existing ESP32 therefore records samples after
the workload endpoint without requiring a firmware update. Acquisition gaps and
missing brackets still invalidate the affected energy metric. Older captures
without this marker retain the old GPIO-window definition.

While acquisition is paused, the selected pre-trigger history plus all usable
samples through `e1_us` are immutable in PSRAM and are published over MQTT. There
is no concurrent ring writer and therefore no ring-overwrite tracking during
publication. When publication succeeds, fails, or reaches the instrument's bounded
publication timeout, the ring is reset and INA228 acquisition resumes to build the
next pre-trigger history. The framework does not begin another normal experiment
until the preceding capture publication has completed.

Pre-trigger history is optional and capped at 1000 ms. The recorder retains only
available samples at or after `e0_us - pretrigger_us`; short or absent pre-edge
history does not invalidate the measured interval. `pretrigger_complete` is
informational. The validator records `available_pretrigger_us` and
`pretrigger_max_gap_us`; gaps wholly before the rising edge are informational.
Measured coverage must begin within 10 ms after the rising edge and end within
10 ms before the falling edge for legacy captures, or at most one bracket sample
within 10 ms after it, with no measured-interval gap exceeding 10 ms. Energy
integration requires samples bracketing the selected interval; legacy captures
ending before `e1_us` remain unavailable for full GPIO-window energy.
Hash, ordering, sample format, calibration and acquisition-fault checks remain
mandatory. A gap crossing the rising edge is checked only for its measured part.
Firmware caps local pre-trigger settings at 1000 ms. Firmware changes require
manual appliance maintenance; existing captures are not rewritten or retroactively
marked successful.

Sensor acquisition remains the calibrated alert-triggered bus/shunt path:

- bus conversion: 50 us;
- shunt conversion: 50 us;
- averaging: 1;
- I2C: 400 kHz;
- nominal shunt: 0.015 ohm;
- effective empirical shunt value: 0.029 ohm;
- calibration identity: `empirical_dmm_reference_loads_2026-09-25`.

These settings are configuration evidence, not a claimed sampling rate. Actual
sample timestamps remain the rate evidence. The existing empirical calibration
status is retained; this change does not upgrade it to traceable metrology.

## Compact sample format

Only information needed for later analysis is stored in the PSRAM ring. Each
sample is a packed little-endian 20-byte record:

| Offset | Type | Field | Meaning |
| ---: | --- | --- | --- |
| 0 | signed 64-bit | `timestamp_us` | ESP32 monotonic sample timestamp |
| 8 | IEEE-754 float32 | `bus_v` | bus voltage, V |
| 12 | IEEE-754 float32 | `current_a` | current, A |
| 16 | IEEE-754 float32 | `power_w` | instantaneous power, W |

Python struct notation is `<qfff`.

Sequence numbers, I2C read duration, diagnostic flags, cumulative fault
counters, experiment identity, measurement names, interval descriptors, and
association state are not repeated in every sample. Capture-level acquisition
counter deltas are retained once in the completion message instead.

For the configured 7 MiB maximum ring, the theoretical record capacity is:

```text
7 * 1024 * 1024 = 7,340,032 bytes
floor(7,340,032 / 20) = 367,001 samples
```

Actual allocation may be smaller than this limit: firmware preserves a 512 KiB
PSRAM reserve and is bounded by the largest free block. Completion metadata
reports the actual capacity.

Voltage and current remain in the raw record even though offline energy can be
derived from power. They preserve the measurements used to diagnose/calibrate
power without reintroducing per-sample protocol/session metadata.

## MQTT transfer contract

The ESP32 is publish-only at the application level. It subscribes to no MQTT
control topic and receives no collect/associate/cleanup command.

It publishes QoS 1 messages to two fixed topics:

```text
pqc/instrument/energy/capture/chunk
pqc/instrument/energy/capture/complete
```

Chunk messages contain only schema/source, an opaque 16-hex-digit `capture_id`,
chunk sequence, and base64 packed sample bytes. The capture ID groups transport
messages; it is not an experiment identity.

The completion message retains the minimum information needed to validate and
interpret the stream: `e0_us`, `e1_us`, pre-trigger status, sample count and
bounds, sample format, chunk count, logical byte count, SHA-256 of the packed
sample bytes, firmware identity, actual ring capacity, calibration/configuration
identity, and capture-level acquisition/sync fault deltas.

The framework starts its normal reporting subscriber before the STM32 run. After
the workload, it waits up to the configured completion timeout for a completed
ESP32 capture already present in that raw stream. It sends no ESP32 command.
A missing capture, malformed transfer, hash/count mismatch, acquisition fault,
missing measured coverage, measured-interval gaps, or incompatible GPIO-window duration fails
energy capture and therefore fails an energy-enabled experiment.

Because the ESP32 deliberately has no run ID, the framework chooses the newest
completed capture whose ESP32 edge duration agrees with the single STM32
experiment-window duration within 5 ms or 1%, then performs full integrity/format
validation. During normal operation the framework serializes experiments so a new
GPIO window cannot begin while the previous capture is being published. If an
unexpected rising edge is nevertheless observed during publication, the ESP32
cancels the old transfer and intentionally does not accept that abnormal new
window as a valid capture because acquisition was still paused at its rising edge.

The raw reporting file is retained under both the normal STM32 result-stream
role and the energy-result-stream role. `energy-capture.json` records the energy
acceptance and the selected cross-clock anchors. Scientific integration remains
outside the execution manifest.

## TIM2 alignment and offline analysis

Let the STM32 edge timestamps be `(s0, s1)` and the ESP32 observed edge
timestamps be `(e0, e1)`. A first-order two-point mapping is:

```text
scale = (s1 - s0) / (e1 - e0)
TIM2(e) = s0 + (e - e0) * scale
```

This corrects a constant offset and first-order relative clock-rate difference
instead of assuming the STM32 and ESP32 oscillators are identical. Pre-trigger
samples use the same mapping by extrapolation.

Once a TIM2 interval has been mapped into the ESP32 sample time domain, offline
analysis can integrate `power_w` over sample time to derive energy for that
interval. Boundary interpolation/integration policy belongs to the analysis
artifact and must record its method and input hashes; the firmware does not
calculate scientific interval energy.

The two-edge fit does not remove GPIO propagation delay, ESP32 interrupt latency,
or any edge-asymmetry bias. A logic-analyser comparison is still required before
claiming a bounded cross-device timing error.

## Configuration and maintenance

The instrument profile is `configs/instruments/energy/esp32_ina228.yaml`. Its
endpoint is descriptive and declares `direction: publish_only` and
`command_plane: none`.

The generated/ignored ESP32 `sdkconfig` contains local experiment settings,
including Wi-Fi. Their classification follows the [open-data policy](006_security_and_secrets.md).
Defaults are maintained in `instruments/esp32_ina228/main/Kconfig.projbuild`, including broker host/port/client ID, GPIOs,
pre-trigger duration, MQTT/publisher task stacks, ring limit, and PSRAM reserve.

Energy-enabled resolution still requires a workload with deferred reporting and
hardware reset between runs. OTA multi-boot energy capture remains unsupported.
Unsupported combinations warn and resolve with energy disabled where the
maintained resolver already defines that behaviour.

## Verification

Run software checks from the repository root:

```bash
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh pytest tests/integration -m integration
```

The ESP32 source/native tests validate the publish-only protocol, 20-byte record,
pre-trigger selection, post-falling-edge acquisition pause, frozen-ring publication,
resume/reset behaviour, packed transport framing, source configuration and pinned
SparkFun API using software doubles. They are not ESP-IDF/hardware evidence.

Manual appliance maintenance remains explicit and outside normal campaigns:

```bash
cd /home/timk/rmit/PQC-Framework-02/instruments/esp32_ina228
idf.py reconfigure
idf.py build
ESP32_PORT=/dev/serial/by-id/YOUR_ESP32_DEVICE
idf.py -p "$ESP32_PORT" flash
```

Use the selected appliance configuration when interpreting retained captures.

After the updated ESP32 has been manually flashed, the hardware gate is:

```bash
cd /home/timk/rmit/PQC-Framework-02
./scripts/dev.sh pytest-hardware tests/hardware/test_energy_capture_hw.py -m hardware --pqc-require-hardware
```

DTR-013 in [testing and deferred coverage](013_testing_and_deferred_coverage.md)
records current-protocol normal acquisition/endpoint evidence and remaining live
fault recovery. Older session/association captures do not validate the passive
protocol. This guide does not independently rerun or requalify historical results.

## Offline A6 energy reports

The [energy analysis reference](012_results_and_analysis.md#energy)
owns energy definitions, interpolation/pairing policy, output lineage and batch/
notebook commands. `--energy` on `scripts/summarise_timing_dataset.py` analyses
existing captures only. It reuses instrument acceptance checks, but requires valid
sample brackets for joule integration: a capture may pass acquisition checks and
still lack energy for the selected endpoint when sample brackets are absent.
Current whole-workload integration stops at `workload_end_us`; legacy GPIO-window
integration ends at `s1_us`/`e1_us`. No tail
extrapolation or inferred reporting-time trimming is permitted. Physical electrical
boundary assertions require a lab evidence reference before comparison inclusion.
Mathematical parser tests do not replace the physical qualification limits above.
