# Certificate Sub-component Build Guide

This directory is an independently testable sub-component of the main framework.

## Scope

The component owns:
- Vault bootstrap for certificate/signing material storage.
- AppRole authentication and Vault KV v2 access.
- Safe per-run materialisation of certificates and private keys.
- Docker Compose definitions for LocalStack KMS, Vault and step-ca.

It does not own MQTT orchestration, firmware builds, wolfBoot signing implementation, or the main framework result model.

## Development rules

- Run commands from `framework/certs`.
- Do not log Vault tokens, private keys, recovery keys, AppRole SecretIDs, or secret values.
- Vault is the authoritative persistent store for private material.
- `secrets/public` may retain public certificates and verification keys.
- The root CA private key is archived in Vault and must not remain in the online step-ca state.
- step-ca is the online intermediate issuer; no continuously running root CA service is used.
- `secrets/runtime` is temporary per-run material and must not be committed.
- Docker volumes remain authoritative for Vault, LocalStack and step-ca internal state.
- Keep unit tests independent of Docker and network services.
- Mark tests requiring the Compose stack with `integration`.
- Do not change the main framework outside this directory without a separate request.

## Commands

```powershell
python -m pip install -e ".[test]"
python -m pytest tests/unit
python -m pytest -m integration tests/integration

docker compose up -d --build
python -m pytest -m integration tests/integration
```
