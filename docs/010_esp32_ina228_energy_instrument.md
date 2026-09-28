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
PQC_ENERGY_BOUNDARY scope=experiment s0_us=<...> s1_us=<...> valid=1 clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write
```

There is one GPIO HIGH interval per experiment. Repeated TLS therefore does not
pulse the GPIO once per handshake. Existing TIM2 TLS/benchmark instrumentation
continues to describe internal sub-intervals; offline analysis projects those
TIM2 intervals onto the one ESP32 trace.

The former UART `PQC_ENERGY_WAITING` / `PQC_ENERGY_GO` start gate is retired.
STM32 reset/initialization returns PF12 LOW. During the normal framework lifecycle
there is no next rising edge until the preceding ESP32 publication has completed.
An unexpected rising edge during publication cancels that old transfer and leaves
the abnormal new window without a valid capture.

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

While acquisition is paused, the selected pre-trigger history plus all usable
samples through `e1_us` are immutable in PSRAM and are published over MQTT. There
is no concurrent ring writer and therefore no ring-overwrite tracking during
publication. When publication succeeds, fails, or reaches the instrument's bounded
publication timeout, the ring is reset and INA228 acquisition resumes to build the
next pre-trigger history. The framework does not begin another normal experiment
until the preceding capture publication has completed.

The maintained pre-trigger target is 3000 ms. Capture acceptance requires the
requested history to be present; an undersized/newly started ring is not silently
accepted as a complete measurement.

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

The former 64-byte record size could hold:

```text
7,340,032 / 64 = 114,688 samples
```

Thus the compact record provides about `64 / 20 = 3.2` times the sample history
at the same byte limit. Actual allocation may be smaller because the firmware
also preserves a 512 KiB PSRAM reserve and is bounded by the largest available
PSRAM block; the firmware reports the actual capacity.

Voltage and current remain in the raw record even though offline energy can be
derived from power. They preserve the measurements used to diagnose/calibrate
power without reintroducing per-sample protocol/session metadata. A future
format reduction to timestamp+power would be a separate evidence-format change.

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
incomplete pre-trigger history, or incompatible GPIO-window duration fails
energy capture and therefore fails an energy-enabled experiment.

Because the ESP32 deliberately has no run ID, the framework chooses the newest
completed capture whose ESP32 edge duration agrees with the single STM32
experiment-window duration within 5 ms or 1%, then performs full integrity/format
validation. During normal operation the framework serializes experiments so a new
GPIO window cannot begin while the previous capture is being published. If an
unexpected rising edge is nevertheless observed during publication, the ESP32
cancels the old transfer and intentionally does not accept that abnormal new
window as a valid capture because its requested pre-trigger history was not sampled.

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

## Configuration and secrets

The instrument profile is `configs/instruments/energy/esp32_ina228.yaml`. Its
endpoint is descriptive and declares `direction: publish_only` and
`command_plane: none`.

The ESP32 local `sdkconfig` may contain laboratory Wi-Fi credentials and must
remain uncommitted. Non-secret defaults are maintained in
`main/Kconfig.projbuild`, including broker host/port/client ID, GPIOs,
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

Do not share the generated local `sdkconfig` if it contains Wi-Fi credentials.

After the updated ESP32 has been manually flashed, the hardware gate is:

```bash
cd /home/timk/rmit/PQC-Framework-02
./scripts/dev.sh pytest-hardware tests/hardware/test_energy_capture_hw.py -m hardware --pqc-require-hardware
```

The earlier 2026-09-27 single-interval evidence belongs to the superseded
session/association protocol. It is useful historical evidence that the physical
measurement path could complete, but it does **not** validate this simplified
wire format, passive lifecycle, one-window repeated-TLS behaviour, or new host
matching logic. Fresh hardware evidence is required before those behaviours are
claimed successful. The corresponding deferred-test entry is DTR-013 in
`docs/007_framework_architecture.md`.
