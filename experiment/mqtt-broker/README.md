# MQTT broker operation

The gateway runs separate experiment and reporting brokers. Firmware campaigns
manage deployment, readiness, capture and cleanup themselves; manual broker setup
is not a prerequisite to each run. This guide owns explicit certificate setup and
broker-only diagnosis. Use [host setup](../../docs/002_host_gateway_setup.md) for
SSH/lease prerequisites and [experiment operation](../../docs/005_remote_flash_workflow.md)
for STM32 runs. Project material follows the
[open experimental-data policy](../../docs/006_security_and_secrets.md).

## Services and TLS choices

All services use the digest-pinned Eclipse Mosquitto image in [compose.yaml](compose.yaml).
The historical `oqs` names select OpenSSL 3.5's native hybrid/ML-KEM group policy;
no external OQS provider is loaded. Certificates and TLS KEX are independent.

| Compose profile | Default host listener | Authentication |
|---|---|---|
| `classical` | Plaintext 1883 and TLS 8883 | TLS requires a client certificate |
| `classical-server-auth` | TLS 8883 | Server certificate only |
| `oqs` | TLS 8884 | Server certificate only; hybrid/standalone ML-KEM policy |
| `oqs-mtls` | TLS 8885 | Client certificate required; hybrid/standalone ML-KEM policy |
| `reporting` | Plaintext 1886 | ACL-scoped reporting/control traffic |

All encrypted listeners require TLS 1.3. Compose defaults to `rsa3072` material;
campaigns explicitly pass the resolved certificate profile, including `mldsa65`,
to startup/status/readiness. Do not infer certificate family from a service name.
The exact groups are maintained in [openssl.cnf](config/oqs/openssl.cnf).
A configured group is not evidence of the negotiated group.

The classical service also supplies the plaintext experiment listener. TLS and
plain readiness are separate from container health. All brokers have a bounded
8,192-message queue; overflow still fails workload evidence. Runtime users, mounts,
ACLs and listener details are owned by Compose and `config/*/mosquitto.conf`.

## Provision certificates once

Run the host launcher as the normal Linux user, from the repository root:

```bash
python3 scripts/provision_certificates.py
```

It owns a pinned Docker/OpenSSL runtime; do not nest it under `dev.sh python`.
It reads `configs/tls_auth/*.yaml`, generates hierarchies and deployment aliases in
`secrets/certificates/<profile-id>/`, and verifies generated key/certificate pairs.
An existing profile is refused unless replacement is explicitly requested:

```bash
python3 scripts/provision_certificates.py --profile rsa3072 --force
```

Use `--force` only for intentional replacement, because changing keys/certificates
changes experiment identity. SANs, validity, identities and algorithms come from
the selected YAML. Update/reprovision deliberately after endpoint changes. Normal
experiments and broker control never generate or renew certificates. Missing or
incomplete material fails prerequisites. No online CA service is required.

The current launcher uses owner-only directories/keys and UID/GID preservation.
These implementation modes do not classify experiment material as secret. Host
ownership checks are documented in [host setup](../../docs/002_host_gateway_setup.md).

## Gateway broker administration

Use `python-gateway` to retain the normal shared gateway lease and runtime SSH
configuration. There is no `dev.sh mqtt-broker` subcommand. An example with an
explicit certificate choice:

```bash
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py status --profile oqs --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py logs --profile oqs
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

Each invocation holds the lease for its duration; this sequence does not reserve
the gateway between commands. Coordinate manual service changes with other users.
`stop` affects this configured Compose project, including reporting. Firmware
campaigns own their transactional lifecycle and should not be interrupted by manual
administration.

`--gateway-config configs/gateways/pqc_gateway1.yaml` selects gateway identity.
The controller prefers `identity.fqdn`, then alias, for SSH and uses
`network.address` for clients when needed. Host-native `python3` invocation is
available for bounded diagnostics; it does not acquire the wrapper lease.
Preview remote commands without gateway access using:

```bash
./scripts/dev.sh python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy --dry-run
```

Deployment stages selected certificates into a gateway repository-shaped workspace.
Containers mount that input read-only, copy required TLS files into `/tmp`, and
run Mosquitto with their configured runtime identity. Read-only source mounts
avoid modifying canonical inputs. mTLS maps certificate identity to the ACL;
changed client names require matching ACL entries. The OQS mTLS health identity
is distinct from the STM32 client and restricted to `pqc/framework/health`.

## Broker-only validation

After provisioning/deploying/starting the matching profile:

```bash
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-classical-server-auth-mqtt --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-classical-mqtt --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls --oqs-group SecP256r1MLKEM768 --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-mqtt --certificate-profile ecdsa-p256
./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-mtls-mqtt --certificate-profile ecdsa-p256
```

These are alternative profile checks, not a sequence that starts all profiles.
Server-only validators omit client identity; mutual-TLS validators supply it.
OQS readiness resolves one running container by Compose labels and uses its MQTT
clients. TLS validation requires a successful TLS 1.3 exchange, a non-`NONE` cipher,
a presented/verified certificate and the requested group where checked.

The compatibility `mqtt-broker-experiment` entry point still defaults to a removed
`provision-certs` controller command. Until that runtime default is changed,
preprovision explicitly and use `--no-provision-certs`:

```bash
./scripts/dev.sh experiment-gateway mqtt-broker-experiment --profile classical --no-provision-certs --stop-after
```

This orchestrates broker steps and retains their logs/status; it is host/broker
compatibility evidence only. Native host wolfMQTT/wolfSSL has a separate tool:

```bash
./scripts/dev.sh python experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py --help
```

Neither client tool proves STM32 execution or end-to-end wireless operation.

## Reporting and retained evidence

The reporting broker carries `pqc/result/#`, `pqc/instrument/#` and `pqc/control/#`
outside experiment impairment. Its health probe performs a retained publish/subscribe
round trip on `pqc/control/health` and removes the probe afterward. The passive
ESP32 publishes fixed capture topics without a command protocol. OTA uses the
reporting plane; [OTA](../../docs/009_dual_bank_ota_workflow.md) owns its delivery contract.

Firmware runs retain broker logs, topic-qualified host observations and, for TLS,
`mqtt-broker-tls-keylog.log` beside `gateway-network-capture.pcap`. Device reporting
and independent broker packet-routing evidence establish workload acceptance;
UART or container health alone is insufficient. Broker logs do not contain an
authoritative copy of every application payload. The runtime image/version and
collected artifacts are recorded by the owning workflow.

To inspect encrypted traffic, select the retained key log in Wireshark's TLS
(Pre)-Master-Secret log preference and open its paired PCAP. Offline analysis and
interpretation are owned by [results](../../docs/012_results_and_analysis.md).
The open-data policy includes these experiment key logs and reproduction material.

## Validation gates

Local Docker and gateway checks exercise different boundaries:

```bash
python3 scripts/check_oqs_mtls_broker.py
./scripts/dev.sh pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e_in.py -m integration --pqc-require-gateway
```

The local gate uses disposable RSA-3072/ML-DSA-65 containers and does not establish
STM32 compatibility. Read the selected test's retained outputs before claiming
success. Profile-matrix and fault qualification remain in the
[test register](../../docs/013_testing_and_deferred_coverage.md).


The four experiment broker profiles provide a workload-feeder listener on port
1884. Before target reset, the responder enters the selected broker's network
namespace and preconnects the same native gateway MQTT clients to its loopback
address. Local request, payload and observer traffic therefore bypasses the
external veth where the framework applies impairment and MTU changes. The
responder verifies its namespace and MQTT acknowledgements before target reset.
It requires gateway `nsenter` and non-interactive sudo, and returns to the owning
user's uid/gid after entering the namespace.

The host's compatibility mapping remains **gateway loopback only**,
`127.0.0.1:1884`; the responder does not use that mapping. This listener must not
be published on `0.0.0.0`. The STM32 uses its selected network-facing transport
and certificate policy. Only one experiment profile owns the feeder endpoint at
a time, under the framework gateway lease.
