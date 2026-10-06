# Disposable-lab reliability trials

This optional procedure owns `scripts/ready_metrics_2_reliability_v2.py`.
It is separate from normal [campaign collection](015_campaign_collection.md)
because execution deliberately resets the local lab workspace and Docker state.
It has not been qualified by merely passing simulated process tests; see DTR-016
in the [test register](013_testing_and_deferred_coverage.md).

## Scope of the reset

Run as the normal Linux user on a dedicated idle checkout and local Docker daemon.
`--execute` deletes **all contents**, including hidden files and keys, from
`.pqc-generated-state/`, `build/`, `results/` and `secrets/`. It also removes all
containers, images, named/anonymous volumes, unused custom networks and default-
builder cache on the selected local daemon, including other projects. Existing
results and signing identities are lost. This is not routine tuple cleanup.

The runner refuses symlink/mount cleanup roots and non-local Docker endpoints.
It leaves remote gateway Docker, other Docker contexts/builders, host configuration
and built-in networks alone. Save required results/material first and wait for all
other operations to finish. Do not run it merely to repair a failed build.

## Preview and execute

From the repository root, preview before explicitly selecting destructive execution:

```bash
python3 scripts/ready_metrics_2_reliability_v2.py --runs 10 --dry-run
```

On the disposable lab only, after preserving required state:

```bash
python3 scripts/ready_metrics_2_reliability_v2.py --runs 100 --execute
```

The host launcher needs normal-user Docker and uses sudo for workspace cleanup.
It rebuilds the development image, runs the host certificate provisioner, resolves
`ready_metrics_2.yaml`, chooses the first case and launches a fresh
`experiment-gateway run` per trial. It does not use campaign runtime-only reuse.
Framework builds can reuse compatible object files. Image/certificates persist
between trials. SSH/VPN access and Wi-Fi inputs must exist outside cleared folders.

Setup failure stops the batch; a trial failure is retained and the next trial
proceeds. Ctrl-C stops further trials. Gateway contention retains normal waiting.
The older `ready_metrics_2_reliability.py` remains a legacy script; use version 2
for this documented sequence, without replacing a script while it is executing.

## Interpretation

`results/reliability/<timestamp>-<id>/summary.json` updates after each trial and
retains source identity, case, exit status, the new run manifest and UART paths.
Success requires process/run exit 0, completed execution, accepted finalized
capture and no recorded failure stage; supported legacy records require an explicit
run-pass verdict. This measures execution/capture reliability, not every metric.

Case-sensitive whole-word UART `ERROR` is counted separately from success.
Missing/empty/unreadable UART is unknown, not verified clean. Headline percentages
use attempted trials including failed launches; a separate rate uses known UART
captures. With unknown captures the observed ERROR rate is a lower bound.
Exit codes are 0 for all attempted trials successful, 1 for trial failures,
2 for invalid arguments/setup failure and 130 for interruption. Zero trials has
no rate. Process tests with command doubles do not prove live purge/rebuild,
provisioning or hardware acceptance.
