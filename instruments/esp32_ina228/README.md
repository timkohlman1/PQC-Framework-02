# Persistent ESP32-S3 / INA228 passive recorder

The instrument is a manually provisioned, persistent GPIO-triggered measurement
appliance. Setup, wiring, calibration status, wire format, framework contract and
verification are maintained in
[`docs/010_esp32_ina228_energy_instrument.md`](../../docs/010_esp32_ina228_energy_instrument.md).

The ESP32 samples the INA228 continuously while idle and while the STM32 GPIO
window is HIGH. STM32 PF12 drives ESP32 GPIO11 HIGH for one complete experiment
window and LOW at its conclusion. The ESP32 retains available pre-trigger
history up to one second (short or absent history is allowed), timestamps the falling edge, pauses acquisition, and publishes the frozen
20-byte `<qfff` timestamp/voltage/current/power capture to:

```text
pqc/instrument/energy/capture/chunk
pqc/instrument/energy/capture/complete
```

There is no application-level MQTT command plane, association token, run ID or
measurement name on the appliance. Acquisition remains paused while the immutable
capture is published, then the ring is reset and sampling resumes to rebuild the
next pre-trigger history. An unexpected rising edge during publication cancels the
old transfer and invalidates that abnormal window; the normal framework does not
start another experiment until the preceding publication has completed.

The ring targets at most 7 MiB while preserving 512 KiB PSRAM headroom. At 20
bytes/sample, 7 MiB can theoretically hold 367,001 records; actual allocated
capacity is reported by the firmware and may be smaller.

GPIO12 receives INA228 ALERT. The shared 400 kHz I2C bus uses SDA GPIO48 and SCL
GPIO47. Local `sdkconfig` may contain Wi-Fi credentials and must not be committed
or packaged.

Source/native tests are not hardware validation. Cross-clock alignment and
energy integration are performed offline from the two GPIO timestamps plus raw
sample timestamps. Fresh hardware validation is required after changing this
firmware.
