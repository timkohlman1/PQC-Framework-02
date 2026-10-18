# Linux host and gateway setup

This guide owns environment setup, access, output ownership and gateway coordination.
Use [board setup](003_stm32_board_setup.md) for wiring,
[operation](005_remote_flash_workflow.md) for runs and the
[broker guide](../experiment/mqtt-broker/README.md) for certificates/services.
All experiment data follows the [open policy](006_security_and_secrets.md).

## Development environment

Use a normal non-root Linux shell with Docker access and the complete pinned
submodule checkout. From the repository root:

```bash
./scripts/dev.sh build-image
./scripts/dev.sh run id
./scripts/dev.sh check-host-user
./scripts/dev.sh pytest tests/unit
```

Python analysis/test dependencies are pinned in [requirements-dev.txt](../requirements-dev.txt).
After changing those requirements, rerun `./scripts/dev.sh build-image` before
validation: normal wrapper commands reuse the existing image and do not rebuild it.

The image bootstrap creates a container-local account/home, then permanently drops
real/effective/saved UID/GID to the invoking user's numeric identity before executing
repository commands. Supplementary groups and umask are retained. The wrapper uses
`no-new-privileges`; workloads are not rerun as root to hide permission failures.
Hardware tests mount empty anonymous build/state volumes with `volume-nocopy`.
The bootstrap adjusts only those volume roots, not recursive host trees.

Gateway wrappers mount the host SSH directory read-only and copy it into a fresh
container home. The copy's directories/files use `0700`/`0600`; symlinks are retained
without changing target permissions. That runtime copy is discarded with the
container. These modes describe implementation, not project confidentiality.

`check-host-user` is a host Python gate using synthetic SSH files and a temporary
checkout-shaped tree. It checks host-visible ownership, home/passwd behavior,
groups, isolated volumes and exit codes. It needs a built image and local rootful
Docker without UID remapping; it rejects unsupported remote/rootless/userns setups.
Do not change daemon settings merely to suppress a failure. Its pytest counterpart
skips inside the development image because nested Docker is unavailable.

Certificate provisioning has its own pinned container and must run on the host.
It drops privileges before reading profiles/generating material, with umask `0077`.
Check that boundary without replacing canonical certificates:

```bash
python3 scripts/check_certificate_ownership.py
```

Expected: `status: verified`, invoking UID/GID and two disposable profiles checked.
An image rebuild does not repair existing host ownership. Inspect/repair ownership
instead of regenerating keys with `--force`. Sealed results can legitimately remain
read-only; ownership repair is not content verification or resealing.

## Gateway identity and access

[configs/gateways/pqc_gateway1.yaml](../configs/gateways/pqc_gateway1.yaml) owns SSH
identity, network address, helper names, ST-LINK serial and UART path. Different
adapters use the alias or FQDN; configure both locally. Do not hard-code duplicated
lab identities into framework code.

For a new development host, generate a key and install its public half:

```bash
ssh-keygen -t ed25519 -C "pqc-framework-dev-pc"
ssh-copy-id timk@pqc-gateway1
```

An example `~/.ssh/config` matching the current gateway profile is:

```sshconfig
Host pqc-gateway1 pqc-gateway1.pqcnet
    HostName 10.1.1.18
    User timk
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Update local access configuration if lab identity changes. Where a VPN is needed,
establish it on the development host before running wrappers. Authentication setup
is an operator prerequisite; normal runs do not alter it.

```bash
ssh pqc-gateway1 "hostname && whoami"
```

This bounded diagnostic establishes reachability only. Gateway wrappers set
`PQC_CONTAINER_ENABLE_GATEWAY=1`; `PQC_DOCKER_SSH_DIR` overrides the host SSH mount.
The gateway needs its configured flash/reset helpers, UART access, Python 3,
Docker Compose and the acquisition/impairment tools below.

## Packet capture and impairment prerequisites

Install `tcpdump` on the gateway and grant the experiment user noninteractive
capture permission under the lab's OS policy. A capability-based setup, run on
the gateway by its administrator, is:

```bash
sudo apt-get update
sudo apt-get install -y tcpdump
sudo setcap cap_net_raw,cap_net_admin=eip "$(command -v tcpdump)"
getcap "$(command -v tcpdump)"
tcpdump --version
```

The workflow invokes tcpdump directly. `network.packet_capture` selects interface
and optional STM32 MAC filter; canonical gateway capture configuration should match
the actual topology. Without a device filter, captures can contain unrelated traffic.
[Results](012_results_and_analysis.md#packets-and-network) explains attribution.

Impairment also requires noninteractive `tc`, `ip`, IFB/module support and `nsenter`.
The framework requires distinct experiment/reporting broker veth peers, shapes only
the experiment path in both directions, and restores MTUs/qdiscs on cleanup.
It refuses occupied non-default qdiscs and existing IFBs. The physical/control
interface is inspected rather than changed. Disconnection/reboot/SIGKILL can leave
uncertain state; inspect it before another run. The lease is cooperative coordination,
not an access-control boundary.

Selected live checks build/flash and change temporary gateway state:

```bash
./scripts/dev.sh pytest-gateway tests/integration/test_gateway_flash_helper_in.py -m integration --pqc-require-gateway
./scripts/dev.sh pytest-hardware tests/hardware/test_reporting_plane_isolation_hw.py --pqc-require-hardware
```

Add `--pqc-request8-esp32-hardware` to the second command only with the provisioned
energy instrument to qualify that reporting path too. Configured qdisc state and
packet counters do not independently measure achieved RTT, loss or throughput.
Refer to the [test register](013_testing_and_deferred_coverage.md) for remaining
qualification; no setup instruction is itself evidence of a pass.

## Gateway lock and recovery

`pytest-gateway`, `pytest-hardware`, `experiment-gateway`, `campaign-gateway` and
`python-gateway` acquire one gateway-side POSIX flock lease for the full container
run. Local `experiment`, `python` and generic `run` do not. All cooperating hosts
must use the same gateway user/wrappers and a filesystem supporting flock.

Waiting owners retry until free; interactive terminals show elapsed waiting time,
while logs report changes. Ctrl-C cancels waiting without releasing another owner.
Do not impose a short timeout unless requested. Owner metadata does not prove its
originating workload is still running. Inspect status with:

```bash
./scripts/dev.sh gateway-lock status
```

After verifying abandonment and obtaining explicit recovery authorization, release
only the exact current owner:

```bash
./scripts/dev.sh gateway-lock release --owner-id OWNER_ID_FROM_STATUS --force
```

This terminates the lease holder; a still-running client detects lease loss and
terminates its local group. Never unlink the lock file: multiple lock inodes can
permit overlapping owners. Normal completion, Ctrl-C and SSH termination release
the lease, but release does not prove remote helpers or impairment cleanup finished.
Inspect interrupted board/broker/network state before proceeding.

For a generic coordinated command use `./scripts/dev.sh gateway-lock run -- <command>`.
Arbitrary SSH, direct helpers and host-native broker commands bypass the advisory
lock. Separate local preparation from locked hardware work when the gateway need
not be reserved throughout the build.

## One-time ownership repair


Changing future runtime identity does not change existing ownership. Stop active
builds, exports and experiments first. Inspect the explicitly selected generated
paths below. Do not substitute the repository root, source/submodule trees or the
host home directory, and do not run this over nested mounts. Missing paths are
skipped. The repair selects root-owned/root-group directories and single-link
ordinary files without set-ID bits. It does not follow symlinks, rotate signing material, rewrite
contents, or run `chmod`. Existing restrictive modes, including read-only sealed
files, are retained rather than forcibly made writable. Chown changes ownership
metadata; it is not an evidence reseal or a content-integrity check.

```bash
(
    set -eu
    cd /home/timk/rmit/PQC-Framework-02
    owner_uid=$(id -u)
    owner_gid=$(id -g)
    [ "$owner_uid" -ne 0 ] && [ "$owner_gid" -ne 0 ] || {
        printf '%s\n' 'Run from the normal non-root user shell.' >&2
        exit 1
    }
    paths=(build .pqc-generated-state results secrets .pytest_cache)
    for path in "${paths[@]}"; do
        [ ! -L "$path" ] || {
            printf 'Refusing symlink: %s\n' "$path" >&2
            exit 1
        }
        [ ! -e "$path" ] || [ -d "$path" ] || {
            printf 'Expected directory: %s\n' "$path" >&2
            exit 1
        }
    done
    for path in "${paths[@]}"; do
        [ -d "$path" ] || continue
        sudo find -P "$path" -xdev \
            \( -type d -o \( -type f -links 1 \) \) \
            ! -perm /6000 -uid 0 -gid 0 \
            -exec chown --no-dereference --from=0:0 \
                "$owner_uid:$owner_gid" -- {} +
    done
)
```

Root-owned generated files outside those paths, hard-linked/special files and
pre-existing ACL/setgid policies require separate inspection, not a broader
automatic ownership sweep. In particular, review old in-source wolfBoot tools
or keystore outputs by exact filename rather than changing its whole source tree.

## Optional UniFi access-point telemetry

Provision the AP separately from the experiment gateway. This collector runs on
linuxdev1 using an SSH alias; no AP credentials belong in a campaign profile.
The controller provisions public keys persistently: see [Ubiquiti's SSH-key
instructions](https://help.ui.com/hc/en-us/articles/235247068-Adding-SSH-Keys-to-UniFi-Devices).

1. Generate a dedicated key without overwriting an existing file:
   `ssh-keygen -t rsa -b 3072 -f ~/.ssh/pqc_ap -C pqc-ap-telemetry`.
   For unattended collection, use a dedicated unencrypted key or load a protected
   key into the SSH agent available to the collector.
2. Display `cat ~/.ssh/pqc_ap.pub` and add the complete public-key line in UniFi
   Network's Device SSH Settings / SSH Keys. Depending on application version,
   this appears under Devices / Device Updates and Settings, or Settings /
   System / Advanced / Device Authentication. Enable device SSH, save, and note
   the AP address and device SSH username (separate from console SSH access).
3. Add the following host block to `~/.ssh/config`, replacing both placeholders:

   ```sshconfig
   Host pqc-ap
       HostName AP_IP_ADDRESS
       User DEVICE_SSH_USERNAME
       IdentityFile ~/.ssh/pqc_ap
       IdentitiesOnly yes
       StrictHostKeyChecking ask
   ```

4. Run `ssh pqc-ap true` once. Confirm the address identifies the intended AP
   before accepting its host key; compare a trusted fingerprint where available.
5. Verify unattended access:

   ```bash
   ssh -o BatchMode=yes -o StrictHostKeyChecking=yes pqc-ap \
       'uname -a; command -v iw; cat /proc/net/wireless'
   ```

6. Use the capability-check collection command in the
   [analysis reference](012_results_and_analysis.md). Unsupported driver counters
   remain unavailable. This step does not scan, reconfigure channels or generate
   experiment traffic; it does not by itself establish a low-interference link.
