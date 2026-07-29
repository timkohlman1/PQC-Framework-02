
## Framework-managed progress output

When the top-level experiment framework manages a broker run, the console reports
the broker lifecycle as timestamped stages: certificate provisioning when
requested, deployment, start, readiness/status checks, TLS or MQTT validation,
log collection, and stop/cleanup. Validation retries are reported by attempt.
Detailed command output remains in the per-step result logs and the manifest
remains authoritative for stage status and return codes.
