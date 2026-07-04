# Host and Gateway Setup

## Purpose

This document records how each development PC connects to the experiment gateway.

The gateway is used for remote flashing, UART log capture, and later experiment services.

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

Each development PC must generate its own SSH keypair for gateway access.

Do not share SSH private keys between development PCs.

The private key must remain on the development PC where it was generated and must not be committed to Git.

Only the public key should be copied to the experiment gateway.

Use the local SSH alias:

```text
pqc-gateway1
```

rather than hard-coding private key paths into framework code or documentation examples.

### Generate a key on each development PC

On Windows PowerShell, Git Bash, Linux, or macOS:

```bash
ssh-keygen -t ed25519 -C "pqc-framework-dev-pc"
```

When prompted, save the key under the local user SSH directory.

Recommended default paths are:

```text
Windows: C:\Users\<user>\.ssh\id_ed25519
Linux/macOS: ~/.ssh/id_ed25519
```

Use a passphrase where practical.

Do not place SSH keys inside this repository.

### Install the public key on `pqc-gateway1`

Copy only the public key to the gateway account.

From Linux, macOS, or Git Bash:

```bash
ssh-copy-id timk@pqc-gateway1
```

If `ssh-copy-id` is not available, append the public key manually:

```bash
cat ~/.ssh/id_ed25519.pub | ssh timk@pqc-gateway1 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

On Windows PowerShell:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh timk@pqc-gateway1 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

### Configure the local SSH alias

Each development PC should configure the alias locally in its SSH config file.

Example local SSH config entry:

```sshconfig
Host pqc-gateway1
    HostName 10.1.1.18
    User timk
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

On Windows, the config file is usually:

```text
C:\Users\<user>\.ssh\config
```

On Linux and macOS, the config file is usually:

```text
~/.ssh/config
```

This file is local developer-machine configuration and should not be committed to the repository if it contains machine-specific paths, hostnames, usernames, VPN hostnames, or other local access details.

### Verify SSH access

From the development PC:

```bash
ssh pqc-gateway1 "hostname && whoami"
```

Expected result:

```text
pqc-gateway1
timk
```

If the command prompts for the SSH key passphrase, that is normal.

If the command prompts for the gateway account password, the public key may not be installed correctly, the SSH alias may not be configured, or the wrong private key may be selected.

### Security checks

Before committing, check that no private keys or local SSH configuration files have been added to Git:

```bash
git status --short
```

Private key files such as these must not appear in staged or unstaged Git changes:

```text
id_ed25519
id_rsa
*.pem
*.key
.ssh/config
```

Public keys such as `*.pub` are not secret, but developer-specific public keys should normally still remain outside the repository unless there is a deliberate documented reason to include them.

## Remote Flashing

The gateway has STM32CubeProgrammer CLI installed and provides the helper command:

```text
flash-stm32a
```

Manual remote flashing uses the local SSH alias:

```powershell
scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

## UART Capture

Manual UART capture is run on the gateway.

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

Expected baseline UART output:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

## VPN Access

When outside the local network, connect to the VPN first.

VPN private keys and credentials must not be stored in this repository.

If the gateway uses a different VPN hostname or IP address, configure this locally through SSH config rather than hard-coding private keys or credentials into the project.

## MQTT broker service

The repository includes a gateway-hosted Docker Compose project at `experiment/mqtt-broker/` for MQTT-over-TLS experiments.

The build server remains the orchestrator. It provisions local development certificates, copies the compose project to the gateway with `scp`, and starts or stops Docker Compose remotely with `ssh`.

Typical build-server commands from the repository root:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile classical
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py status
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

The deploy command uses the SSH alias from `configs/hosts/gateway.yaml`. It does not require private SSH key paths in repository files.

## Repository Gateway Network Address

`configs/hosts/gateway.yaml` records two different gateway identifiers:

```text
alias: pqc-gateway1
network.address: 10.1.1.18
```

Use the SSH alias for `ssh` and `scp` orchestration. Use `network.address` for MQTT/TLS, Docker service validation, or other client workflows where the SSH alias may not resolve through DNS.

The MQTT broker certificate provisioning command reads `network.address` and includes it as an IP subject alternative name when certificates are generated with the host config:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1 --host-config configs/hosts/gateway.yaml
```

The gateway integration test deploys the broker into a temporary remote directory, starts it on an alternate host port, validates external TLS 1.3 mutual authentication against `network.address`, then stops and removes the temporary deployment:

```powershell
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
```
