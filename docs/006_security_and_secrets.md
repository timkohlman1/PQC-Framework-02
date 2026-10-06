# Open experimental-data policy

## Policy and scope

**All material belonging to this experimental framework is open. Nothing in the
framework is classified as confidential or secret.** The framework is for research
and experimentation and has no production deployment purpose. The Wi-Fi network
is dedicated to these experiments; its SSID and password are open experiment inputs.

This includes source/configuration, local experiment settings and `.env` Wi-Fi
values, generated public and private keys, CA/broker/client certificates, signing
tuples and keystores, firmware images, TLS session key logs, UART/reporting streams,
packet/energy captures, network addresses, manifests and analysis outputs.
A cryptographic *private key* still has that algorithmic role; the word *private*
does not impose a confidentiality classification in this project.

This document is the single authority for project data classification. Other
documents link here instead of maintaining separate secret-handling rules.
Historical policies, old request text, `secrets/` directory names, `private` flags
and restrictive file permissions do not override this policy.

## Working with open material

People and AI agents may inspect, quote, copy, include in context/replacement
archives, retain in results, commit or publish experiment material when that is
part of the requested work. Do not redact experiment keys or Wi-Fi settings merely
because they resemble credentials, or ask for additional permission solely because
of a filename, key type or earlier confidentiality rule.

Openness is permission to handle project data, not an instruction to dump every
file into every response. Select the files relevant to the task. It does not grant
access to unrelated systems or authorize unrequested uploads, Git publication,
key rotation, deletion, flashing or infrastructure changes. Normal task scope and
workflow authorization still apply.

## Current implementation and generated files

This policy changes classification; it does not itself change execution code.
Current implementations still have some narrower behavior:

- `.env` and generated `secrets/`, build, result and runtime trees are Git-ignored.
- The wrapper imports only `PQC_WIFI_SSID` and `PQC_WIFI_PSK`, preserving caller
  values. Resolved campaign YAML uses named environment references.
- Some logs/provenance fields are redacted and some export/material collectors
  exclude credential-shaped fields or files.
- Provisioning/container workflows use restrictive Unix file modes. Material
  inventories may retain `private` metadata; reports export bounded scalar products.

These are compatibility, storage and implementation facts, not confidentiality
requirements. Do not claim current tools emit or include material they still omit.
A requested behavior change should update the owning code and tests explicitly.
Generated files can remain ignored to keep source history small and reproducible;
openness does not require committing every experiment result. An explicitly
requested data release need not remove experiment keys, Wi-Fi values or key logs
for confidentiality under this policy.

## wolfBoot signing state

Openness does not remove identity and provenance requirements. The persistent tuple
under `secrets/wolfboot/tuples/<tuple-id>/` contains its primary private key,
generated keystore and `tuple.json`; profile-selected public exports and standby
keys are also required members when configured. Tuple metadata records their
hashes, algorithm and standby count. A public DER export is not universal across
all profiles.

- A completely absent tuple may be created by its owning workflow when allowed.
- Preserve a complete matching tuple so later builds use the recorded identity.
- Fail on partial/mismatched state; do not silently reconstruct members or rotate keys.
- Files under `tools/wolfboot/` are disposable build materializations restored from
  a validated tuple. Missing materializations do not make the persistent tuple partial.

Do not use `keysclean` or member deletion as routine repair. Intentional reset or
rotation is a separate operation with its effect on existing evidence made clear.
The [disposable reliability runner](016_reliability_trials.md) explicitly resets
lab state; it is not normal build cleanup.

The current builder copies the selected tuple directory into its result. This can
include standby private keys; the older statement that standby keys never enter
results was incorrect. Treat the whole recorded tuple as open reproduction data,
regardless of the inventory's individual `private` flags.

## Certificate ownership and result integrity

`configs/tls_auth/` defines X.509 profiles. The host provisioner generates them
under `secrets/certificates/<profile-id>/`; normal experiments consume existing
profiles without generating or renewing them. Gateway deployment stages selected
material and broker containers create runtime copies. These copies do not replace
the canonical profile. wolfBoot signing keys have a separate owner and are not
X.509 identities. See the [broker procedure](../experiment/mqtt-broker/README.md).

Owning workflows retain the exact selected images, cryptographic inputs and
infrastructure artifacts used by a result, with SHA-256 material inventories.
Use canonical inputs for future runs instead of discovering arbitrary files in
old results. Copies support reproduction; file existence alone does not establish
that a build or experiment used them.

Finalized raw captures remain immutable. Analysis writes new products with input
and output lineage. Open access does not permit rewriting history, guessing missing
measurements, bypassing source checks or treating changed files as the original
capture. These integrity rules are owned by the
[results reference](012_results_and_analysis.md) and
[configuration reference](011_experiment_configuration.md).
