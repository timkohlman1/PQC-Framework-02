# STM32 board and wiring

The target is NUCLEO-L4R5ZI-P / STM32L4R5 with ST67W611M1 Wi-Fi. Canonical hardware
and access values belong to [target configuration](../configs/targets/stm32l4r5_st67.yaml)
and [gateway configuration](../configs/gateways/pqc_gateway1.yaml). Use
[host setup](002_host_gateway_setup.md) for access and
[operation](005_remote_flash_workflow.md) for known-image flash/capture.

## Board, debugger and console

The MCU has 2 MiB Flash, 192 KiB primary RAM, 64 KiB RAM2 and 384 KiB RAM3.
The selected linker script owns reservations and placement; bank capacity is not
measured usage. Normal application vectors use the relocated wolfBoot layout.

The maintained console is LPUART1, 115200 baud, 8N1, no flow control, routed through
ST-LINK. Use the gateway profile's ST-LINK serial and persistent
`/dev/serial/by-id/` UART path rather than assuming a transient `/dev/ttyACM*` name.
The bootloader diagnostic console uses PG7 TX / PG8 RX, AF8. UART availability
also depends on the selected firmware output mode.

## ST67 SPI observation

`networkTask` invokes the ST67 driver after FreeRTOS starts; the driver uses delays,
queues, semaphores and interrupt-driven SPI. `Core/Src/main.c` owns bring-up:
BOOT, CHIP_EN and active-high SPI_CS start low; a 20 ms task delay makes the initial
low state observable; logging/callback setup precedes `W6X_Init()`, which performs
module startup. The old three-second analyzer-start delay is no longer present.
Arm the analyzer before initiating the known-image run/reset.

SPI1 prescaler 4 gives approximately 30 Mbit/s with the configured 120 MHz PCLK2.
Use acquisition equipment capable of resolving that clock. The earlier 12 MHz
FX2 acquisition setting cannot reliably decode it. Expected observations include
CHIP_EN rising, SPI_RDY activity, active-high chip select, clock and MOSI/MISO bursts.
Correlate pins with diagnostics rather than inferring higher-level network success.

The transport derives from
`Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c`, with project
READY guards, bounded polling and diagnostics. It is not an unmodified vendor copy.
The lwIP adapter submits each chained `pbuf` segment to `W6X_Netif_output()` without
coalescing it into a temporary contiguous allocation.

## Energy connection

STM32 D8/PF12 drives the passive recorder's GPIO11; INA228 ALERT goes to ESP32
GPIO12, and its shared I2C uses GPIO48 SDA / GPIO47 SCL. The
[instrument guide](010_esp32_ina228_energy_instrument.md) owns detailed setup,
calibration and interval boundaries. Confirm the actual measured power rail through
collection annotations; wiring alone does not establish calibration accuracy.

## Evidence

[Baseline firmware](004_baseline_hal_app.md) owns startup/task diagnostics.
A module-init marker proves only that stage; association/DHCP, TCP, TLS, MQTT,
secure boot and valid measurements need their respective records. A monitor-only
capture cannot establish which image is running. Use the
[test register](013_testing_and_deferred_coverage.md) for recorded qualification
and the [results reference](012_results_and_analysis.md) for measurement meaning.
