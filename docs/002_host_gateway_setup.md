# Host and Gateway Setup

## Purpose

This document owns development-host access to the experiment gateway. Operational flash and UART commands are owned by `docs/005_remote_flash_workflow.md`; board and UART hardware details are owned by `docs/003_stm32_board_setup.md`; broker-specific operation is owned by `experiment/mqtt-broker/README.md`.

## Canonical gateway configuration

Repository-owned gateway identity and helper configuration is stored in `configs/hosts/gateway.yaml`. Use its SSH alias for SSH/SCP orchestration and its `network.address` for MQTT/TLS client validation when the alias is not resolvable through DNS.

Current configured values are:

```text
SSH alias: pqc-gateway1
SSH user: timk
Network address: 10.1.1.18
Flash helper: flash-stm32a
Reset helper: reset-stm32a
```

Do not duplicate these values in framework code or add private-key paths to repository configuration. Update `configs/hosts/gateway.yaml` and the relevant canonical documentation when the lab identity changes.

## Gateway role and evidence boundary

The gateway provides remote STM32 flashing, reset, bounded UART capture, and broker orchestration. A successful SSH probe proves gateway reachability only. Broker logs prove broker-side or host-side compatibility only. Flash and UART success require the workflow logs or manifests described in `docs/005_remote_flash_workflow.md`. None of these outcomes alone proves Wi-Fi-module, ST67W61M1, STM32 network, TLS-handshake, MQTT, timing, memory, benchmark, or end-to-end wireless success.

## SSH access

Each development PC must generate its own SSH keypair. Keep the private key on that development PC and outside the repository. Install only the public key on the gateway.

Generate a key:

```bash
ssh-keygen -t ed25519 -C "pqc-framework-dev-pc"
```

Recommended local paths are:

```text
Windows: C:\Users\<user>\.ssh\id_ed25519
Linux/macOS: ~/.ssh/id_ed25519
```

Install the public key from Linux, macOS, or Git Bash:

```bash
ssh-copy-id timk@pqc-gateway1
```

When `ssh-copy-id` is unavailable:

```bash
cat ~/.ssh/id_ed25519.pub | ssh timk@pqc-gateway1 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

Windows PowerShell equivalent:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh timk@pqc-gateway1 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Configure the alias in the local SSH config, not in tracked repository files:

```sshconfig
Host pqc-gateway1
    HostName 10.1.1.18
    User timk
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Typical SSH config locations are `C:\Users\<user>\.ssh\config` on Windows and `~/.ssh/config` on Linux/macOS.

Verify reachability:

```bash
ssh pqc-gateway1 "hostname && whoami"
```

This is a host-native connectivity diagnostic, not a repository validation gate and not hardware-runtime evidence.

## Docker-wrapper gateway execution

Repository workflows normally run in the project container. Gateway-capable wrappers set `PQC_CONTAINER_ENABLE_GATEWAY=1`, mount the configured host SSH directory read-only, and copy the required SSH material into the temporary container for that run.

Representative checks from the repository root:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
.\scripts\dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
```

`PQC_DOCKER_SSH_DIR` may override the host-side SSH directory. SSH keys, VPN material, broker credentials, or TLS private keys must never be copied into the image or committed. See `docs/006_security_and_secrets.md`.

## VPN access

When the gateway is reachable only through a VPN, establish the VPN on the development host before invoking gateway wrappers. Keep VPN profiles, keys, and credentials outside the repository and container image. Resolve alternate gateway addresses through local SSH configuration rather than hard-coding private access details.

## Operational links

- Direct flash, secure boot, generated-state provenance, and UART evidence: `docs/005_remote_flash_workflow.md`
- Board, ST-LINK, and UART hardware configuration: `docs/003_stm32_board_setup.md`
- Broker deployment, certificate provisioning, and host/broker evidence: `experiment/mqtt-broker/README.md`
- Secret and generated-state handling: `docs/006_security_and_secrets.md`
- Canonical capability and evidence matrix: `docs/007_framework_architecture.md`
