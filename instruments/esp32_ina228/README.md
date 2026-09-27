# Persistent ESP32-S3 / INA228 acquisition appliance

Setup, power-domain wiring, GPIO assignments, calibration identity, acquisition
protocol, manual maintenance and verification are maintained in
[the energy instrument guide](../../docs/010_esp32_ina228_energy_instrument.md).

The appliance records ALERT-timestamped raw sensor samples in a PSRAM ring
targeting 7 MiB with 512 KiB free headroom, and records GPIO11 interval boundaries.
Actual allocated capacity is reported. Acquisition pauses only for post-run
transfer and resumes on every exit; overflowing this run's retention fails capture.
GPIO12 receives INA228 ALERT; the shared
400 kHz I2C bus uses SDA GPIO48 and SCL GPIO47. PF12 on the STM32 supplies the
3.3 V interval signal. Retained evidence is published only after a framework
run's measured intervals, through the plaintext reporting broker.

Source implementation is not hardware validation. No achieved sample rate is
claimed from ADC settings. Integration, affine clock fitting and scientific
energy attribution belong to offline analysis. Local `sdkconfig` may contain
Wi-Fi credentials and must never be committed or packaged. Campaigns do not
build, flash or reset this persistent instrument.

This revision requires the matching host collector for schema 3 compact arrays,
base64 chunks and fresh token readiness. Historical schema 2 remains readable.
