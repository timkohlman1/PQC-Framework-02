# Host and Gateway Setup

## Purpose

This document records how the development PC connects to the experiment gateway.

## Current Gateway

```text
Host alias: pqc-gateway1
User: timk
Local IP: 10.1.1.18
```

## Gateway Role

The gateway is used for:

- remote STM32 flashing
- UART log capture
- later MQTT broker hosting
- later network impairment and traffic shaping
- later benchmark orchestration

## SSH Access

Each development PC should generate its own SSH keypair.

The private key must remain local and must not be committed to Git.

Only the public key should be copied to the experiment gateway.

## Remote Flashing

The gateway has STM32CubeProgrammer CLI installed and provides the helper command:

```text
flash-stm32a
```

## VPN Access

When outside the local network, connect to the VPN first.

VPN private keys and credentials must not be stored in this repository.

If the gateway uses a different VPN hostname or IP address, configure this locally through SSH config rather than hard-coding private keys or credentials into the project.
