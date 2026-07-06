# MQTT broker compose project

This directory contains the gateway-hosted MQTT broker service for transport-security experiments.

The build server remains the orchestrator. Commands are run from the repository root and use `ssh`/`scp` with the gateway alias configured in `configs/hosts/gateway.yaml`.

## Profiles

- `classical`: Eclipse Mosquitto over TLS 1.3 on port `8883` by default. It uses generated local X.509 test material and mutual TLS client-certificate authentication.
- `oqs`: Open Quantum Safe Mosquitto on port `8884` by default. It uses gateway-generated OQS mutual-TLS material by default and depends on the `openquantumsafe/mosquitto` image.

The OQS profile is for protocol evaluation only. It must not be treated as production TLS infrastructure, and PQC TLS success must be supported by explicit broker/client logs.

Both profiles override the image entrypoint with an explicit shell script, copy the source ACL file to `/tmp/mosquitto-aclfile` inside the container, set container-local ownership and mode there, and run Mosquitto against that copy. This avoids changing bind-mounted repository files and avoids image startup attempts to change ownership of read-only config/certificate mounts.

## Files

```text
experiment/mqtt-broker/compose.yaml
experiment/mqtt-broker/env.example
experiment/mqtt-broker/config/classical/mosquitto.conf
experiment/mqtt-broker/config/classical/aclfile
experiment/mqtt-broker/config/oqs/README.md
experiment/mqtt-broker/scripts/mqtt_broker_ctl.py
```

Generated runtime material is ignored by Git:

```text
experiment/mqtt-broker/runtime/
experiment/mqtt-broker/data/
experiment/mqtt-broker/log/
experiment/mqtt-broker/.env
```

## Provision local classical TLS material

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1
```

This creates a local development CA, server certificate, and client certificate under `experiment/mqtt-broker/runtime/classical/certs/`. These files are not committed.

## Provision remote OQS TLS material

The OQS profile generates its CA, server, client, and healthcheck certificates on the gateway using the OQS-enabled OpenSSL provider inside `openquantumsafe/mosquitto:latest`. The default algorithms are `mldsa65` for the CA and `falcon512` for the leaf certificates. The validation group is `mlkem768`.

Deploy the compose project first, then provision OQS certificates into the remote runtime directory:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-oqs-certs --host-config configs/hosts/gateway.yaml
```

Validate OQS mutual TLS after starting the profile:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls
```

## Deploy to the gateway

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
```

Preview remote commands without running them:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy --dry-run
```

## Framework-level broker experiment orchestration

Use the top-level experiment CLI when the broker is being used as framework infrastructure rather than as a standalone service utility:

```powershell
python scripts/experiment.py mqtt-broker-experiment --profile classical --stop-after
python scripts/experiment.py mqtt-broker-experiment --profile oqs --stop-after
```

The wrapper provisions the selected profile's certificates, deploys the compose project, starts the selected profile, checks status, runs the applicable MQTT/TLS validation, retries validation for a bounded startup-readiness window, writes each step as `running` before its subprocess starts, creates the step log immediately, prints progress for each attempt, applies `--step-timeout-seconds` to bound subprocess hangs, attempts log collection even after validation failures, and stops the broker when `--stop-after` is supplied. Use `--dry-run` to write framework evidence while passing dry-run through to the broker control script.

## Start, inspect, and stop

Start the classical TLS broker:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile classical
```

Start the experimental OQS broker:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs
```

Check status:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py status
```

Show logs:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py logs --profile classical
```

Stop broker services:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

## Local Docker smoke test

After provisioning certificates, the classical profile can be run locally from this directory:

```powershell
cd experiment/mqtt-broker
docker compose --profile classical up -d
docker compose ps
docker compose down
```

Local and gateway Docker success must be confirmed from command output or logs before recording it as experiment evidence.

## Gateway address and certificate SANs

`configs/hosts/gateway.yaml` contains both the SSH alias and `network.address`. The SSH alias is used for orchestration commands, while `network.address` is used for MQTT/TLS validation from clients that cannot resolve the SSH alias through DNS.

Provision certificates with the host config so the server certificate includes the gateway IP address as an IP subject alternative name:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1 --host-config configs/hosts/gateway.yaml
```

External TLS validation can use the configured IP address:

```powershell
openssl s_client `
  -connect 10.1.1.18:8883 `
  -verify_ip 10.1.1.18 `
  -CAfile .\experiment\mqtt-broker\runtime\classical\certs\ca.crt `
  -cert .\experiment\mqtt-broker\runtime\classical\certs\client.crt `
  -key .\experiment\mqtt-broker\runtime\classical\certs\client.key `
  -tls1_3
```

## Gateway integration test

The gateway integration tests create temporary broker directories under the gateway, deploy the compose project, provision temporary TLS material, start the classical and OQS profiles on alternate host ports, perform TLS 1.3 mutual-auth validation, stop Compose, and remove the temporary gateway directories.

It skips cleanly unless gateway access and Docker Compose are available:

```powershell
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
```

To fail instead of skip when the gateway capability is unavailable:

```powershell
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```


OQS broker logs are emitted to Docker stdout only. The OQS profile disables Mosquitto file logging and persistence so temporary gateway deployments can be cleaned up without root-owned log or data files.

## OQS image user compatibility

The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.
