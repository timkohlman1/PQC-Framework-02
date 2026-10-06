# Hybrid/PQC server-authenticated broker profile

`oqs` selects TLS 1.3 server authentication with the native OpenSSL group policy in
[openssl.cnf](openssl.cnf). The historical profile name does not imply an external
OQS provider or a fixed certificate family. The resolved certificate profile is
independent of KEX; this listener does not require client certificates.

Use the [broker guide](../../README.md) for provisioning, deployment, validation
and evidence boundaries. Host/broker success does not prove STM32 operation.
Project data classification is owned by the
[open-data policy](../../../../docs/006_security_and_secrets.md).
