# OQS Mosquitto profile

The `mqtt-oqs` Compose profile uses `openquantumsafe/mosquitto:latest` for post-quantum TLS evaluation.

This profile now uses project-managed mutual-TLS material generated on the gateway with the OQS-enabled OpenSSL provider from the same container image. Generated files are written under `runtime/oqs/certs/` on the target host and must not be committed.

Default OQS certificate choices:

```text
CA signature algorithm: mldsa65
server/client/healthcheck key algorithm: falcon512
TLS key-share group used for validation: mlkem768
```

The broker requires client certificates and maps the client certificate common name to the MQTT username with `use_identity_as_username true`, matching the classical profile.

Confirm negotiated algorithms from explicit broker/client logs before recording benchmark or security claims.


The OQS Mosquitto configuration logs to stdout only and disables persistence to avoid container-owned bind-mount files during gateway experiments. Docker logs are the source of truth for OQS broker runtime diagnostics.
