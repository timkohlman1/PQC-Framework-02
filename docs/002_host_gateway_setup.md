# Host and Gateway Setup

## Purpose

This document owns development-host access to the experiment gateway. Operational flash and UART commands are owned by `docs/005_remote_flash_workflow.md`; board and UART hardware details are owned by `docs/003_stm32_board_setup.md`; broker-specific operation is owned by `experiment/mqtt-broker/README.md`.

## Canonical gateway configuration

Repository-owned gateway identity and helper configuration is stored in `configs/gateways/pqc_gateway1.yaml`. Use its SSH alias for SSH/SCP orchestration and its `network.address` for MQTT/TLS client validation when the alias is not resolvable through DNS.

Current configured values are:

```text
SSH alias: pqc-gateway1
SSH user: timk
Network address: 10.1.1.18
Flash helper: flash-stm32a
Reset helper: reset-stm32a
```

Do not duplicate these values in framework code or add private-key paths to repository configuration. Update `configs/gateways/pqc_gateway1.yaml` and the relevant canonical documentation when the lab identity changes.

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
Linux: ~/.ssh/id_ed25519
```

Install the public key from Linux:

```bash
ssh-copy-id timk@pqc-gateway1
```

When `ssh-copy-id` is unavailable:

```bash
cat ~/.ssh/id_ed25519.pub | ssh timk@pqc-gateway1 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

Configure the alias in the local SSH config, not in tracked repository files:

```sshconfig
Host pqc-gateway1
    HostName 10.1.1.18
    User timk
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Typical SSH config locations are `~/.ssh/config` on Linux.

Verify reachability:

```bash
ssh pqc-gateway1 "hostname && whoami"
```

This is a host-native connectivity diagnostic, not a repository validation gate and not hardware-runtime evidence.

## Docker-wrapper gateway execution

Repository workflows normally run in the project container. Gateway-capable wrappers set `PQC_CONTAINER_ENABLE_GATEWAY=1`, mount the configured host SSH directory read-only, and copy the required SSH material into the temporary container for that run.

Representative checks from the repository root:

```bash
./scripts/dev.sh pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration
./scripts/dev.sh pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
./scripts/dev.sh experiment-gateway monitor --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --duration-seconds 10
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

## Gateway packet-capture prerequisite

Firmware experiments containing a top-level `network` configuration start a bounded packet capture on the gateway before the STM32 is reset. Install `tcpdump` on the gateway and grant the experiment SSH user permission to capture packets without an interactive privilege prompt. A typical Linux capability-based setup is:

```bash
sudo apt-get update
sudo apt-get install -y tcpdump
sudo setcap cap_net_raw,cap_net_admin=eip "$(command -v tcpdump)"
getcap "$(command -v tcpdump)"
tcpdump --version
```

The expected `getcap` result includes `cap_net_admin,cap_net_raw=eip`. Site policy may instead provide an equivalent dedicated capture group or wrapper. The experiment workflow invokes `tcpdump` directly and does not issue interactive `sudo` commands.

Packet-capture settings belong under `network.packet_capture` in the experiment profile. `interface` defaults to `any`. `stm32_mac_address` is optional but preferred when the ST67W61M1 MAC address is known because it limits the capture to Ethernet frames involving that device while retaining DHCP, DNS, TCP, TLS, MQTT, ARP, and related traffic. The address must use six colon-separated hexadecimal octets.

## Gateway experiment certificate staging

Broker deployment may stage ignored experiment certificate profiles under the repository-shaped gateway workspace. This state is not an alternate source of truth. Staged certificate directories must remain mode `0700`, private `*.key` files mode `0600`, and public/non-key certificate files may be `0644`. Do not use recursive `chmod a+rX` on a certificate tree containing private keys. The broker containers consume the staged tree through read-only mounts and create their own restricted runtime copies.
