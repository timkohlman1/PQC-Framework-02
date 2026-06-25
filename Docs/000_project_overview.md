# Project Overview

## Purpose

This project is an STM32-based embedded security experiment framework for evaluating boot security, MQTT communication, TLS, classical cryptography, PQC/hybrid cryptography, network degradation, and benchmark collection.

The project is broader than wolfBoot. wolfBoot and wolfSSL are expected to be major components, but the framework should remain general enough to support multiple experiment types.

## Current Status

The current known-good baseline is a CubeMX-generated STM32 HAL application for the NUCLEO-L4R5ZI-P / STM32L4R5 board.

The application builds, flashes through the experiment gateway, and prints a boot message plus repeated `tick` messages over ST-LINK VCP UART.

## Planned Major Areas

- STM32 firmware build automation
- Remote flashing
- UART log capture
- Result manifests
- wolfBoot secure boot
- wolfSSL MQTT over TLS
- Classical crypto baselines
- PQC/hybrid crypto experiments
- Network degradation simulation
- Benchmark aggregation and analysis

## Notes

This document should be updated whenever the project scope or current implementation phase changes.
