# Certificate and Key Services

This sub-component provides a local, independently testable certificate and key-management environment for the PQC experiment framework.

## Components

- LocalStack KMS persists the Vault auto-unseal key.
- Vault stores authoritative private certificate and signing material in the `pqc-secrets` KV v2 mount.
- step-ca runs as the online intermediate issuer for classical X.509 identities.
- `stepca_secure_root` archives the root CA private key to Vault and removes it from the online step-ca state.
- `securedata` provides AppRole authentication, KV v2 access, certificate record encoding, and temporary per-run materialisation.

## Issued identities

- `mqtt-broker_cert` writes the MQTT broker server certificate and key to `secrets/runtime/mqtt-broker`.
- `stm32_client_cert` writes the future STM32 mTLS client certificate and key to `secrets/runtime/stm32`.
- `localstack_server_cert` writes LocalStack's service certificate and key to `secrets/runtime/localstack`.

Public CA material is exported to `secrets/public/ca`:

- `root-ca.crt` — root trust anchor containing the CA public key.
- `intermediate-ca.crt` — online issuer certificate.
- `ca-chain.crt` — intermediate plus root chain.
- `ca.crt` — compatibility copy of the root trust anchor for clients and sidecars.

The MQTT broker normally presents its leaf certificate plus intermediate chain. MQTT clients authenticate it using `root-ca.crt`/`ca.crt`. For mTLS, the STM32 also presents `client.crt` and proves possession of `client.key`.

## Runtime lifecycle

Normal experiment runs own the local CA/Vault Compose lifecycle. Existing broker and client certificates are reused while they remain valid for more than 30 days. Missing, expired, invalid, or near-expiry identities trigger finite provisioning jobs using one-year leaf certificates. The CA/Vault/LocalStack/step-ca project is stopped and removed after provisioning, including failure paths.

A development-only full PKI reset is available:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --reset-pki
```

This removes the local Compose volumes and generated CA, broker, and STM32 identity material before creating a new hierarchy. Do not use it where certificate continuity matters.

Vault is exposed only on `127.0.0.1:8200` while the temporary infrastructure is running.

## Test

```powershell
python -m pip install -e ".[test]"
python -m pytest tests/unit
python -m pytest -m integration tests/integration
```

## Storage boundary

| Data | Location |
|---|---|
| Vault, KMS and step-ca internal state | Docker volumes |
| Authoritative root CA private key | Vault KV v2 at `pqc-secrets/ca/root/classical` |
| Online intermediate private key | step-ca Docker volume |
| Public root and intermediate certificates | `secrets/public/ca` |
| MQTT broker identity | `secrets/runtime/mqtt-broker` |
| STM32 mTLS identity | `secrets/runtime/stm32` |
| LocalStack service identity | `secrets/runtime/localstack` |
