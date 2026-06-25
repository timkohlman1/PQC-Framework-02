# Framework Architecture

## Purpose

This document describes the planned architecture of the PQC IoT experiment framework.

## Planned Layers

The framework is expected to cover:

1. firmware builds
2. remote flashing
3. UART and log capture
4. result manifests
5. boot-security variants
6. MQTT transport variants
7. TLS/classical crypto variants
8. PQC/hybrid crypto variants
9. network degradation profiles
10. benchmark aggregation and analysis

## Current Status

The framework automation has not yet been implemented.

The current repository contains the known-good STM32 HAL baseline firmware project.

## Design Rule

The framework should run experiment variants.

It should not be hard-coded only for wolfBoot or only for MQTT.

## Future Structure

Planned top-level framework folders:

```text
configs/
scripts/
tests/
results/
tools/
```

These should be added incrementally as framework features are implemented.

## Notes

This document should be updated as the framework structure becomes concrete.
