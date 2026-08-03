# MQTT broker compose project

This directory contains the gateway-hosted MQTT broker service for transport-security experiments.

The build server remains the normal orchestrator. Commands are run from the repository root and use `ssh`/`scp` with the gateway alias configured in `configs/hosts/gateway.yaml`. The project container can also run these gateway workflows, but only when explicitly enabled and supplied with SSH access at runtime.

Framework build, test, and experiment workflows use the Docker wrappers. Broker administration is the exception: run `mqtt_broker_ctl.py` with host-native Python because it uses the development host SSH configuration. There is no `dev.ps1 mqtt-broker` subcommand. Raw `docker run` and `docker compose` commands remain diagnostic fallback only. Gateway identity and SSH setup are owned by `docs/002_host_gateway_setup.md`; firmware flash/UART workflows are owned by `docs/005_remote_flash_workflow.md`; the canonical capability matrix is `docs/007_framework_architecture.md`.

## Profiles

- `classical`: Eclipse Mosquitto over TLS 1.3 on port `8883` by default. It uses the classical step-ca hierarchy and requires a client certificate (mutual TLS).
- `classical-server-auth`: Eclipse Mosquitto over TLS 1.3 on port `8883` by default. It uses the same step-ca broker identity but does not request a client certificate.
- `oqs`: Open Quantum Safe Mosquitto on port `8884` by default. It uses the same classical step-ca identity hierarchy, performs hybrid `SecP256r1MLKEM768` key exchange, and does not request a client certificate.

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

## Provision localhost-only classical TLS material

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name localhost
```

This creates a local development CA, localhost server certificate, and client certificate under `secrets/mqtt/server-ecdsa-p256/`. These generated files are not committed. This example is for local-only validation and does not add the gateway IP address as an IP subject alternative name. Use the gateway-specific command below when clients connect through `configs/hosts/gateway.yaml` and its configured `network.address`.

## Provision remote OQS TLS material

The OQS broker profile uses the classical Step CA certificate chain for server authentication and the hybrid TLS group `SecP256r1MLKEM768` for key exchange. The STM32 profile therefore compiles ML-KEM-768 support while retaining classical RSA certificate verification.

Run gateway broker administration with the repository Python environment on the development host. `mqtt-broker` is not a `dev.ps1` command. The direct script invocation below is the supported host-native administration path because it uses the host SSH configuration. The framework-level `dev.ps1 experiment mqtt-broker-experiment` command remains the normal recorded orchestration path.

Provisioning and deployment are normally performed automatically by the experiment prerequisite phase. For broker-only diagnosis, the equivalent direct commands are:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-oqs-certs --host-config configs/hosts/gateway.yaml
```

Provisioning verifies the classical certificate chain and the server certificate/private-key match before succeeding. The experiment runner resolves the certificate profile before build fingerprinting and broker startup.

Validate the server-authenticated hybrid TLS handshake after starting the profile:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls --oqs-group SecP256r1MLKEM768 --host-config configs/hosts/gateway.yaml
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
.\scripts\dev.ps1 experiment mqtt-broker-experiment --profile classical --stop-after
.\scripts\dev.ps1 experiment mqtt-broker-experiment --profile oqs --stop-after
```

The wrapper provisions the selected profile's certificates, deploys the compose project, starts the selected profile, checks status, runs the applicable MQTT/TLS validation, retries validation for a bounded startup-readiness window, writes each step as `running` before its subprocess starts, creates the step log immediately, prints progress for each attempt, applies `--step-timeout-seconds` to bound subprocess hangs, attempts log collection even after validation failures, and stops the broker when `--stop-after` is supplied. Use `--dry-run` to write framework evidence while passing dry-run through to the broker control script.

The result manifest labels this path as `host-side/broker-side MQTT/TLS compatibility evidence`. Its evidence boundary is limited to host-side client containers and broker-side Docker status/log output. It must not be used to claim STM32 firmware success, ST67W61M1 or Wi-Fi-module success, lwIP-on-STM32 success, wolfSSL-on-STM32 success, wolfMQTT-on-STM32 success, or end-to-end wireless success.

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

## Host-side broker compatibility validation

After provisioning, deploying, and starting a profile, the broker utility can validate MQTT publish/subscribe through host-side client containers:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-classical-mqtt
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-mqtt
```

The validation command output includes the evidence class, evidence label, profile, and evidence boundary before running the client checks. This output is broker/client compatibility evidence only.

### Native host wolfMQTT validation

For PowerShell, pass upstream wolfMQTT options after `--client-args` and quote each dash-prefixed token individually. Active PowerShell guidance does not use a standalone `--` forwarding boundary.

```powershell
.\scripts\dev.ps1 run python experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py `
  --result-json results/host-wolfmqtt/classical-gateway-validation.json `
  run `
  --client-args '-h' 10.1.1.18 '-p' 8883 '-t' `
  '-A' /workspace/secrets/mqtt/server-ecdsa-p256/ca.crt `
  '-K' /workspace/secrets/mqtt/server-ecdsa-p256/client.key `
  '-c' /workspace/secrets/mqtt/server-ecdsa-p256/client.crt
```

This is native host wolfMQTT/wolfSSL compatibility evidence only. It does not prove wolfMQTT-on-STM32, ST67W61M1 operation, or end-to-end wireless behavior.

## Diagnostic fallback: local Docker smoke test

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


## Diagnostic fallback: raw gateway-capable container execution

The default container command does not run gateway or broker integration tests. To run gateway broker checks from the project container, provide SSH access at runtime and set `PQC_CONTAINER_ENABLE_GATEWAY=1`. The image must not contain SSH keys, VPN keys, broker credentials, private certificates, private signing keys, real `.env` files, or generated broker runtime material.

Example PowerShell pattern:

```powershell
docker run --rm -v ${PWD}:/workspace -w /workspace -e PQC_CONTAINER_ENABLE_GATEWAY=1 -v ${env:USERPROFILE}\.ssh:/root/.ssh:ro pqc-framework-stm32-build python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```

Without `PQC_CONTAINER_ENABLE_GATEWAY=1`, gateway capability checks inside the container skip or fail according to the existing pytest strict flag. Passing this test is broker/gateway evidence only when supported by the pytest output and collected broker logs; it is not hardware, UART, timing, memory, benchmark, or secure-boot runtime evidence.

## Gateway integration test

The gateway integration tests create temporary broker directories under the gateway, deploy the compose project, provision temporary TLS material, start the classical and OQS profiles on alternate host ports, perform TLS 1.3 mutual-auth validation, stop Compose, and remove the temporary gateway directories.

It skips cleanly unless gateway access and Docker Compose are available:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
```

To fail instead of skip when the gateway capability is unavailable:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```


OQS broker logs are emitted to Docker stdout only. The OQS profile disables Mosquitto file logging and persistence so temporary gateway deployments can be cleaned up without root-owned log or data files.

## OQS image user compatibility

The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current shared Eclipse Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.


## STM32 plaintext command/response orchestration

The framework's `mqtt_plaintext_st67_e2e` run starts `mosquitto_sub` on the response topic before resetting the board. Because the command publication is intentionally non-retained, it publishes the configured command repeatedly during the bounded startup window rather than relying on a fixed delay. The run succeeds only when the expected response is received and the UART log contains all MQTT end-to-end success markers.

## Experiment-managed lifecycle

The real STM32 plaintext MQTT gateway experiment manages this Compose project transactionally. It stops only the configured framework Compose project, deploys and starts the classical profile, verifies the port 1883 listener with a bounded MQTT publish/subscribe readiness exchange, then collects the full Compose broker log and stops the project after the hardware exchange. The run retains deploy, start, status, readiness, broker, and stop logs in its result directory. Manual `deploy`, `start`, `status`, and `stop` commands remain available for broker-only diagnosis, but are not required before the managed hardware experiment.

## Classical STM32 TLS profiles

Phase M11 keeps two distinct classical TLS profiles:

- `classical-server-auth` uses TLS 1.3 and requires the STM32 to verify the broker certificate. It does not request a client certificate.
- `classical` retains the existing mutual-TLS listener and client-certificate requirement.
- `oqs` uses TLS 1.3 hybrid key exchange and classical server authentication only.
- `oqs-mtls` uses the same hybrid key exchange and classical certificate hierarchy, and additionally requires a classical client certificate.

Host-side validation commands are mode-specific:

```powershell
.\scripts\dev.ps1 python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-classical-server-auth-mqtt
.\scripts\dev.ps1 python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-classical-mqtt
.\scripts\dev.ps1 python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-mqtt
```

`validate-classical-mqtt` sends `client.crt` and `client.key`. The server-auth and OQS validators deliberately omit client identity material. These commands are host-side/broker-side evidence and do not prove STM32 mTLS. The STM32 experiment set covers classical and hybrid server authentication plus equivalent classical and hybrid mutual-TLS profiles. Mutual-TLS builds embed the experiment-only client certificate and private key and include both files in the immutable build fingerprint.

The experiment prerequisite phase provisions or reuses `secrets/mqtt/server-ecdsa-p256` before fingerprinting. The build embeds only that profile’s public `ca.crt`; private keys remain generated dependency state and are not copied into firmware results or manifests.

## STM32 reconnect validation

The server-authenticated STM32 experiment performs one initial MQTT-over-TLS command/response exchange and, when `mqtt.reconnect_attempts` is non-zero, one reconnect exchange. The gateway orchestration keeps publishing the command until it receives both expected response messages or reaches its bounded timeout. It validates each response line against the configured correlation payload and records the observed and expected response counts in `mqtt-subscriber.log` and the experiment manifest.

A reconnect that starts but fails is reported as `reconnect=failed`; `reconnect=not_run` is reserved for cases where reconnect was not configured or the initial exchange failed before reconnect could start.


### MQTT UART completion and logging

Routine MQTT experiment UART output is intentionally concise. Per-call TLS I/O records and individual Wi-Fi scan entries are disabled by default and may be re-enabled at compile time with `PQC_WOLFMQTT_TLS_IO_TRACE=1` and `PQC_WIFI_SCAN_VERBOSE=1`. The firmware emits `PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done` after the final clock, heap, and task-stack evidence. The gateway stops capture after this marker plus the configured grace period (default three seconds), while retaining the configured UART duration as a hard limit. After completion, the scheduler continues running but the one-second UART tick stream is suppressed.

## Hybrid PQC server-authenticated profile

The `oqs` profile is the broker for the first STM32 PQC MQTT experiment. It requires TLS 1.3, uses the `SecP256r1MLKEM768` hybrid group, validates the broker certificate from the STM32 client, and does not request a client certificate. Its mounted OpenSSL configuration activates the default and OQS providers and sets `Groups = X25519MLKEM768:SecP256r1MLKEM768:SecP384r1MLKEM1024` so the Mosquitto server process can select the same hybrid key share as the client.

Provision OQS certificates after deployment. The provisioning command retrieves only the public CA certificate for the local firmware build. The strict TLS validator fails when OpenSSL exits unsuccessfully, no peer certificate is presented, the cipher is `(NONE)`, TLS 1.3 is not negotiated, or certificate verification fails.

### OQS container resolution

Gateway-managed OQS readiness and STM32 command/response orchestration resolve the running `mqtt-oqs` container by its Docker Compose project and service labels, then invoke the bundled OQS-enabled `mosquitto_sub` and `mosquitto_pub` with `docker exec`. The workflow does not rely on `docker compose exec`, because some gateway Compose versions may list the project while failing to resolve its running service. Readiness requires exactly one running labelled container, successful subscriber and publisher exit codes, and the exact `ready` payload. Failure logs retain container-resolution and client output diagnostics.

## OQS certificate compatibility boundary

The STM32 PQC hybrid TLS profile uses classical server authentication. The experiment configuration must declare `mqtt.tls.server_signature_algorithm: classical`. The build fails before compilation when the configured server signature algorithm is missing or incompatible. Changing the public CA certificate changes the firmware build fingerprint and regenerates the embedded trust anchor.

Do not use `--leaf-algorithm falcon512` with this STM32 profile. Host-side OQS clients may support Falcon, but that does not establish compatibility with the firmware client.

## step-ca certificate source and TLS 1.3 policy

All encrypted MQTT profiles use TLS 1.3. The classical and hybrid-key-exchange profiles share the same classical X.509 identity hierarchy produced by `framework/certs`; the hybrid profile changes only the TLS 1.3 key-exchange group.

Start or refresh the certificate services first, then synchronize the current material:

```powershell
docker compose -f framework/certs/docker-compose.yml up -d --build
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --certificate-profile stepca-classical
```

The synchronization command copies the root trust anchor, intermediate, CA chain, broker leaf certificate, and broker private key from `framework/certs/secrets/` into `secrets/mqtt/stepca-classical`. It always refreshes the staged copy and writes `certificate-provenance.json`; it never creates a fallback CA. A changed root CA therefore changes the firmware build input and build fingerprint, while a broker-leaf-only renewal requires broker redeployment but does not change the embedded root trust anchor.

### Container-local TLS key staging

The repository-root `secrets/mqtt/stepca-classical` directory is mounted read-only. On startup, each TLS broker copies `ca.crt`, `server.crt`, and `server.key` into `/tmp/mosquitto-certs`, assigns the broker runtime user, and applies mode `0640` to the private key. Mosquitto reads TLS material only from that container-local directory. This avoids host bind-mount permission differences on Windows and the gateway while preserving a read-only deployment source.


### mTLS identity mapping

The classical mTLS listener uses `use_identity_as_username true`. The step-ca STM32 client certificate has `CN=stm32-mqtt-client`, so the classical ACL authorises the MQTT username `stm32-mqtt-client` for `pqc/#`. A different client certificate common name requires a corresponding ACL entry.


The `validate-oqs-mqtt` client containers load the project-managed OQS OpenSSL configuration and provider module path so MQTT publish/subscribe uses `SecP256r1MLKEM768`, matching the OQS broker profile.


## STM32 mutual-TLS profiles

The framework provides two mutual-TLS profiles alongside the existing server-authentication profiles:

- `configs/experiments/mqtt_tls_secp256r1_mutual_auth_st67_e2e.yaml`
- `configs/experiments/mqtt_tls_SecP256r1MLKEM768_mutual_auth_st67_e2e.yaml`

The classical mutual-TLS profile uses the same classical TLS algorithm set as
the classical server-authentication profile. The hybrid mutual-TLS profile uses
the same `SecP256r1MLKEM768` key-exchange group as the hybrid
server-authentication profile. Both use classical server and STM32 client
certificates issued by the existing Step CA hierarchy. ML-DSA is not used by
the TLS component.

## Timestamped experiment progress output

Experiment commands print concise progress events while they run. Each event uses
local time in `YYYY-MM-DD HH:MM:SS` format, followed by a stable stage label.
The output reports major orchestration decisions and boundaries, including the
resolved experiment, configured cryptography, prerequisite preparation,
application build or reuse decisions, compiler warning totals when available,
gateway-facing flash and UART stages, and managed MQTT broker lifecycle steps.

Example:

```text
2026-07-29 21:55:06  [EXPERIMENT  ] Starting mqtt_tls_pqc_hybrid_server_auth_st67_e2e
2026-07-29 21:55:06  [CRYPTO      ] MQTT TLS mode=pqc_hybrid_tls_server_auth; key exchange=p256_mlkem768; signatures=rsa_pss_rsae_sha256
2026-07-29 21:55:07  [BUILD       ] Evaluating application build and reuse state
2026-07-29 21:56:42  [BUILD       ] Application build decision complete
                   Build executed because no reusable result was selected. 2 compiler warnings.
```

Progress output is informational. The result manifest and retained logs remain
the authoritative evidence for what ran, its return codes, and its outcomes.

### Experiment console progress

Experiment workflows emit timestamped stage messages using the configured progress timezone. The default is `Australia/Melbourne`; set `PQC_PROGRESS_TIMEZONE` to an IANA timezone such as `UTC` when another basis is required. Timestamps include the timezone abbreviation.

Application builds report reuse evaluation separately from compilation: the framework reports whether a reusable immutable build was selected, why a new build is required, CMake configuration, compilation start, completion, return code, and compiler warning count. Managed MQTT experiments also report broker stop-existing, deployment, startup, status, readiness probing, gateway-side publish/subscribe validation, log collection, and shutdown. These messages are operational context only; retained logs and the result manifest remain authoritative evidence.

## Result-retained certificate material

When an experiment selects an MQTT certificate profile, the owning result retains that complete disposable profile beneath `cryptographic-material/mqtt/<certificate-profile>/` and records each file in `material-inventory.json`. This includes applicable CA chains, broker certificates and private keys, and mutual-TLS client certificates and private keys. These copies support manual broker installation and result reproduction; canonical generated state remains authoritative for later runs. SSH/VPN credentials, tokens, production material, and unrelated host credentials are never retained.


## Packet-level MQTT evidence

All experiment broker profiles enable Mosquitto `log_type all` output with connection messages and explicit timestamps. Recorded broker logs therefore provide an independent source for MQTT CONNECT, SUBSCRIBE/SUBACK, PUBLISH routing, unsubscribe, and disconnect activity where emitted by the installed Mosquitto version.

STM32 end-to-end runs use explicit host publisher and subscriber client IDs. Subscriber output is topic-qualified and retained as `mqtt-subscriber-raw.log`. The framework parses the retained broker log into `mqtt-broker-message-evidence.json` and requires evidence that the command publish was received and routed to the STM32 and that the response publish was received from the STM32 and routed to the host subscriber. UART markers remain supporting firmware evidence; they are not sufficient by themselves when broker packet evidence is required.

Mosquitto debug output records packet direction, client ID, topic, QoS, and packet metadata, but does not provide an authoritative copy of every application payload. The retained host subscriber output remains the payload-level cross-check.


## TLS traffic decryption key log

All broker profiles use the pinned `eclipse-mosquitto:2.1.2-alpine` image. The hybrid profiles select `SecP256r1MLKEM768` through the native OpenSSL 3.5 TLS group configuration; no external OQS provider is loaded. TLS broker processes start with Mosquitto's `--tls-keylog` option.

Recorded TLS firmware experiments retain `mqtt-broker-tls-keylog.log` in the same result directory as `gateway-network-capture.pcap`. The manifest records the key-log filename, byte count, SHA-256 digest, collection return code, and failure status. Plaintext experiments mark TLS key logging as not applicable.

In Wireshark, open **Edit → Preferences → Protocols → TLS** and select the retained `mqtt-broker-tls-keylog.log` as the `(Pre)-Master-Secret log filename`, then open the corresponding packet capture. The key log permits decryption of that experiment's TLS traffic and must be treated as sensitive generated evidence.
