# Baseline HAL Application

## Purpose

This document describes the current direct-flash and relocated STM32 HAL/CMSIS-RTOS v2 FreeRTOS application. It identifies the UART marker sequence and the limits of the local smoke evidence.

## Startup and scheduler sequence

After HAL and peripheral initialization, the application emits the direct-flash boot marker. A relocated secure-boot application first emits its secure-boot application marker and then the normal boot marker:

```text
stm32-basic_hal1 secure-boot app v0.1.0
stm32-basic_hal1 boot v0.1.0
```

The secure-boot application marker identifies the relocated payload; wolfBoot-mediated success still requires the applicable secure-boot workflow evidence.

Before `osKernelStart()`, the firmware emits deterministic status markers in this order:

1. direct-flash or secure-boot application marker
2. pre-scheduler lwIP runtime helper smoke (`context=pre_scheduler scheduler=not_started`)
3. unattached lwIP network-interface state (`evidence=lwip-netif-state-only`)
4. pre-scheduler wolfSSL TLS-context lifecycle smoke (`evidence=tls-context-lifecycle-only`)
5. wolfSSL unavailable transport boundary (`evidence=unavailable-transport-only`)
6. `FreeRTOS defaultTask created: ...`
7. pre-scheduler application memory checkpoint
8. `FreeRTOS scheduler starting: ...`

The firmware then calls `osKernelStart()`. `StartDefaultTask()` emits:

```text
FreeRTOS defaultTask started: periodic tick task active
FreeRTOS task-context smoke starting: context=freertos_task scheduler=running serialized=true
```

It runs one serialized task-context smoke sequence:

- lwIP helper smoke labelled `context=freertos_task scheduler=running`
- STM32-local lwIP UDP loopback at `127.0.0.1`, labelled `evidence=stm32-local-lwip-loopback-only`
- wolfSSL TLS-context lifecycle smoke labelled `context=freertos_task scheduler=running`
- wolfMQTT initialization/deinitialization against unavailable callbacks, labelled `evidence=stm32-fake-no-network-initialization-only backend=fake_no_network`

After the one-shot sequence, the task toggles LD2, emits `tick`, and delays for 1000 ms with `osDelay(1000)`. TIM1 is the HAL timebase so FreeRTOS owns SysTick.

A representative sequence is:

```text
stm32-basic_hal1 boot v0.1.0
lwIP runtime smoke: context=pre_scheduler scheduler=not_started ... network=unavailable
lwIP network interface: evidence=lwip-netif-state-only ... transport=unavailable
wolfSSL TLS context smoke: context=pre_scheduler scheduler=not_started evidence=tls-context-lifecycle-only ...
wolfSSL transport boundary: evidence=unavailable-transport-only ... socket_io=not-performed
FreeRTOS defaultTask created: name=defaultTask ...
FreeRTOS scheduler starting: cmsis_rtos=v2 default_task=defaultTask ...
FreeRTOS defaultTask started: periodic tick task active
FreeRTOS task-context smoke starting: context=freertos_task scheduler=running serialized=true
lwIP local loopback smoke: ... evidence=stm32-local-lwip-loopback-only ... result=passed
wolfMQTT runtime smoke: ... evidence=stm32-fake-no-network-initialization-only ... transport=unavailable
FreeRTOS task-context smoke complete: ... network=unavailable tls_handshake=unavailable mqtt=unavailable
tick
```

Exact status fields remain defined by the firmware sources and tests. A marker may be claimed as runtime evidence only when it appears in an explicit UART log from the applicable image.

## Evidence boundaries

The local helper and loopback markers prove only that selected code executed on the STM32 in the stated scheduler context. UDP loopback uses the lwIP loop interface and `127.0.0.1`; it does not use the Wi-Fi module, a hardware-backed interface, the gateway, or an external broker.
The pre-network helper smoke does not provide evidence of ST67W61M1 detection, association, link-up, DHCP, or external network access; later hardware-backed markers must provide those claims explicitly.

The wolfSSL context lifecycle creates and frees a client `WOLFSSL_CTX`; it does not create a network session, load certificates or private keys, or perform a TLS handshake. The wolfSSL transport boundary performs no socket I/O. The wolfMQTT smoke initializes and deinitializes a client against fake/no-network unavailable callbacks; it does not perform MQTT protocol operations.

The baseline application provides ST67W61M1 initialization, configured-AP association, link-up, and DHCP IPv4 evidence only when the corresponding markers appear in a provenance-backed hardware run. It does not yet provide evidence of external ping/TCP, certificate loading, TLS handshake, MQTT connect/subscribe/publish/receive/disconnect/reconnect, broker access from STM32, or end-to-end protocol success.

## Build profiles

The direct-flash experiment and boot profiles are:

```text
configs/experiments/baseline_direct_uart.yaml
configs/boot/direct_flash.yaml
```

The same application is built for wolfBoot with the `RelocatedDebug` preset and relocated linker script:

```text
CMakePresets.json
STM32L4R5XX_FLASH_RELOCATED.ld
```

The relocated application entry address is `0x08022000`, leaving the current 8192-byte wolfBoot image-header reserve at the signed image slot start.


## ST67 Wi-Fi association and DHCP

The baseline experiment supplies SSID and PSK through `configs/experiments/baseline_direct_uart.yaml`. The build workflow generates `build/pqc_generated/pqc_wifi_config.h`; UART and manifests redact the PSK. Firmware joins the configured AP and obtains IPv4 configuration through DHCP. Explicit UART markers record association and IPv4, gateway, and netmask values. Run manifests record parsed evidence under `network`. Hardware success requires both association and DHCP pass markers from the latest boot and a non-zero IPv4 address.


## ST67 T02 network startup

The normal hardware startup does not perform an active access-point scan.
It connects directly using the configured SSID and password. Diagnostic scan
output is available only in builds that explicitly enable
`PQC_ST67_WIFI_DIAGNOSTIC_SCAN`.

Successful T02 runtime evidence is reported after host-side lwIP DHCP as:

```text
lwIP runtime network: ... evidence=stm32-st67-t02-live-state network=available wifi=connected link=up ip=<assigned-ipv4>
```

The address is read from the live station network interface and is never
hard-coded. Earlier pre-network smoke markers describe only the state at their
execution point.


## ST67 SPI clock diagnostic setting

SPI1 is temporarily configured with prescaler 32, giving approximately 3.75 Mbit/s from the 120 MHz APB2/PCLK2 domain. This isolates SPI bus timing from the unchanged 120 MHz MCU clock while comparing `Invalid magic 0xffff` frequency, association/DHCP behavior, and the recurring READY timeout against the previous 30 Mbit/s configuration. The setting is diagnostic evidence only and is not a production-rate decision.

## ST67 SPI READY timeout diagnostics

The STM32L4 HAL reports both READY edges through one generic EXTI callback. The firmware classifies each callback from the sampled READY level and records ISR-safe counters without logging from interrupt context. The counters include total callbacks, high/rising classifications, low/falling classifications, the latest tick for each classification, and the latest sampled level.

When the transfer engine times out waiting for `SPI_EVT_TXN_RDY`, its existing error line includes a snapshot of those counters and the current task tick:

```text
waiting for spi txn ready timeouted: ready_level=<0|1> ready_irq_count=<n> ready_rising_count=<n> ready_falling_count=<n> last_rising_tick=<tick> last_falling_tick=<tick> current_tick=<tick>
```

Timeout evidence also records the transfer engine's last task wake bits, selected event, `spi_do_xfer` flags, queued transmit state, transfer attempt/result counters, and READY levels before and after the most recent transfer.

The attempted one-transaction-per-wake event-ownership change was reverted after hardware evidence showed repeated SPI hardware-transfer timeouts and a growing transmit backlog. The transfer engine again uses the vendor multi-transaction loop and original event clearing semantics. Diagnostic output now records READY around chip-select assertion, chip-select timing, hardware-transfer start and completion timing, completion-callback counts, and completion-wait results. This is diagnostic instrumentation only; retry limits, DMA behavior, buffer lifetime, packet-drop policy, and protocol ordering are otherwise unchanged.
