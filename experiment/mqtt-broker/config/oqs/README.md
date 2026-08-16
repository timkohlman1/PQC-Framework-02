# OQS Mosquitto profile

The `mqtt-oqs` Compose profile uses the maintained Eclipse Mosquitto image with the host OpenSSL configuration for the supported hybrid TLS groups.

This profile implements server-authenticated TLS 1.3 without mutual TLS. The STM32 client validates the broker certificate, but the broker does not request or require a client certificate.

Default OQS cryptographic choices:

```text
CA signature algorithm: mldsa65
server key algorithm: mldsa65
TLS key-share group: SecP256r1MLKEM768
TLS version: TLS 1.3
client authentication: disabled
```

The broker enables anonymous MQTT connections for this bounded experiment profile and restricts access through the OQS ACL file:

```text
topic readwrite pqc/#
topic read $SYS/#
```

The OQS-specific OpenSSL configuration sets `SecP256r1MLKEM768` as the default TLS group for the Mosquitto process. Provider availability alone is not sufficient; the server must also select a compatible TLS group.

Certificate material is provisioned once from the repository root using the shared config-driven provisioner:

```powershell
.\scripts\dev.ps1 python scripts/provision_certificates.py
```

This profile uses the certificate profile selected by the experiment, for example `mldsa65`. Generated material is authoritative under `secrets/certificates/<profile-id>/` and is never generated or synchronized by broker control commands. Missing certificate material is a prerequisite failure.

Validate the broker-side TLS handshake with:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls `
    --oqs-group SecP256r1MLKEM768 `
    --host-config configs/hosts/gateway.yaml
```

Confirm negotiated algorithms from both broker-side validation and STM32 UART evidence.

A valid result must show TLS 1.3, a negotiated non-`NONE` cipher, a presented and verified certificate chain, and the forced `SecP256r1MLKEM768` group.

Broker-side validation is host-side evidence only. Confirm the STM32-negotiated group and MQTT transaction markers from UART and experiment manifests before recording end-to-end claims.

The OQS Mosquitto configuration logs to stdout and disables persistence to avoid container-owned bind-mount files during gateway experiments. Docker logs are the source of truth for OQS broker runtime diagnostics.

Runtime readiness and experiment orchestration locate the broker container using the Compose project label `pqc-framework-mqtt-broker` and service label `mqtt-oqs`, then run the image-provided MQTT clients with `docker exec`. This avoids depending on Compose service lookup for an already running labelled container.
