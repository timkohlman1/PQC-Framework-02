# OQS Mosquitto profile

The `mqtt-oqs` Compose profile uses `openquantumsafe/mosquitto:latest` for post-quantum TLS evaluation.

This profile implements server-authenticated TLS 1.3 without mutual TLS. The STM32 client validates the broker certificate, but the broker does not request or require a client certificate.

Default OQS cryptographic choices:

```text
CA signature algorithm: mldsa65
server key algorithm: falcon512
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

Certificate provisioning is performed from the development host with:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-oqs-certs `
    --host-config configs/hosts/gateway.yaml
```

Generated broker certificate material is written on the gateway under:

```text
~/pqc-framework-02/experiment/mqtt-broker/runtime/oqs/certs/
```

Private keys remain on the gateway. Only the public CA certificate is copied back to the development repository at:

```text
experiment/mqtt-broker/runtime/oqs/certs/ca.crt
```

Generated runtime certificate material must not be committed.

Validate the broker-side TLS handshake with:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls `
    --oqs-group SecP256r1MLKEM768 `
    --host-config configs/hosts/gateway.yaml
```

A valid result must show TLS 1.3, a negotiated non-`NONE` cipher, a presented and verified certificate chain, and the forced `SecP256r1MLKEM768` group.

Broker-side validation is host-side evidence only. Confirm the STM32-negotiated group and MQTT transaction markers from UART and experiment manifests before recording end-to-end claims.

The OQS Mosquitto configuration logs to stdout and disables persistence to avoid container-owned bind-mount files during gateway experiments. Docker logs are the source of truth for OQS broker runtime diagnostics.

Runtime readiness and experiment orchestration locate the broker container using the Compose project label `pqc-framework-mqtt-broker` and service label `mqtt-oqs`, then run the image-provided MQTT clients with `docker exec`. This avoids depending on Compose service lookup for an already running labelled container.
