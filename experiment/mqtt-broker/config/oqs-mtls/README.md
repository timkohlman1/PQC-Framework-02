# Hybrid/PQC mutual-TLS broker profile

The `oqs-mtls` service requires client-certificate authentication in addition to
the selected TLS 1.3 key-exchange group. Certificate family and KEX are independent;
the resolved `configs/tls_auth/` profile can select classical or ML-DSA material.
Health checks use a distinct client identity from the STM32 workload.

Use the [broker operating guide](../../README.md) for provisioning, deployment
and validation. This profile's presence or a host-client test is not STM32
hardware evidence.
