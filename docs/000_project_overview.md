# Project overview

This STM32 embedded-security research framework compares cryptographic and
protocol choices under recorded workload and network conditions. Its target is
the NUCLEO-L4R5ZI-P / STM32L4R5 with ST67W61M1 Wi-Fi, a Linux gateway and an
optional passive ESP32/INA228 energy instrument.

The research domains are firmware authentication, TLS key establishment,
endpoint authentication, application performance and bounded OTA behavior.
The framework supports repeatable acquisition and offline interpretation; it does
not turn missing measurements into results or provide production release assurance.

The [root README](../README.md) owns getting started and common commands.
The [documentation index](README.md) selects the owner for a specific task.
The [architecture](007_framework_architecture.md) owns the current component and
capability model; the [results reference](012_results_and_analysis.md) defines
measurement meaning and comparison limits. This overview intentionally carries
no separate algorithm inventory, capability matrix or operational procedure.
