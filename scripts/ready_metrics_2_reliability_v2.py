#!/usr/bin/env python3
"""Version 2: reset a disposable laboratory workspace, then run independent RM2 trials.

Run on the Linux host as your normal user. Without --execute, only print a plan.
Uses the standard library; experiment work remains owned by scripts/dev.sh.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

CLEAN_DIRS = (".pqc-generated-state", "build", "results", "secrets")
CAMPAIGN = "ready_metrics_2.yaml"
CAMPAIGN_PATH = Path("configs/campaigns") / CAMPAIGN
CASES = ".pqc-generated-state/campaigns/ready_metrics_2/cases"
ERROR_WORD = re.compile(rb"\bERROR\b")


def command(argv: list[str], root: Path, *, check: bool = True,
            capture: bool = False) -> subprocess.CompletedProcess:
    print("+ " + shlex.join(argv), flush=True)
    return subprocess.run(argv, cwd=root, check=check, text=True,
                          capture_output=capture)


def validate_root(root: Path) -> None:
    for relative in ("scripts/dev.sh", "scripts/resolve_campaign.py",
                     "scripts/provision_certificates.py", "scripts/experiment.py",
                     "docker/python/Dockerfile", CAMPAIGN_PATH):
        if not (root / relative).is_file():
            raise ValueError(f"Required repository file missing: {root / relative}")
    for name in CLEAN_DIRS:
        path = root / name
        if path.is_symlink() or path.is_mount():
            raise ValueError(f"Refusing to clear a symlink or mount point: {path}")
        if path.exists() and not path.is_dir():
            raise ValueError(f"Cleanup target is not a directory: {path}")


def require_local_docker(root: Path) -> None:
    # Honour Docker's context-over-DOCKER_HOST precedence; never purge a gateway.
    endpoint = os.environ.get("DOCKER_HOST", "")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        context = command(["docker", "context", "show"], root, capture=True).stdout.strip()
        endpoint = command(["docker", "context", "inspect", context, "--format",
                            "{{.Endpoints.docker.Host}}"], root, capture=True).stdout.strip()
    if not endpoint.startswith("unix://"):
        raise ValueError("Docker purge requires a local Unix-socket Docker context.")
    command(["docker", "info"], root, capture=True)


def clean_workspace(root: Path) -> None:
    command(["sudo", "-v"], root)
    validate_root(root)
    for name in CLEAN_DIRS:
        target = str(root / name)
        command(["sudo", "mkdir", "-p", "--", target], root)
        # Includes dotfiles. find does not follow symlinks; -xdev protects mounts.
        command(["sudo", "find", "-P", target, "-xdev", "-mindepth", "1", "-delete"], root)
        command(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", "--", target], root)
        command(["sudo", "chmod", "700" if name == "secrets" else "u+rwx", "--", target], root)


def purge_docker(root: Path) -> None:
    containers = command(["docker", "ps", "-aq"], root, capture=True).stdout.split()
    for container in containers:
        command(["docker", "rm", "-f", container], root)
    # system prune alone removes only anonymous volumes; include named volumes.
    volumes = command(["docker", "volume", "ls", "-q"], root, capture=True).stdout.split()
    for volume in volumes:
        command(["docker", "volume", "rm", volume], root)
    command(["docker", "system", "prune", "--all", "--force", "--volumes"], root)
    command(["docker", "builder", "prune", "--all", "--force"], root)


def success_from_manifest(data: dict, return_code: int) -> tuple[bool, str]:
    """Current capture schema plus explicit legacy run verdicts; fail closed."""
    if return_code != 0:
        return False, f"framework process exited {return_code}"
    run = data.get("run") or {}
    if run.get("return_code") != 0 or run.get("failure_stage") not in (None, "", "none"):
        return False, "manifest does not record a successful run"
    if "execution_outcome" in data:
        complete = (data.get("execution_outcome") or {}).get("status") == "completed"
        accepted = (data.get("capture_acceptance") or {}).get("accepted") is True
        finalized = (data.get("final_index") or {}).get("status") == "finalized"
        passed = complete and accepted and finalized
        return passed, "completed and capture accepted" if passed else "execution/capture not accepted or not finalized"
    # Older revisions retained the terminal result instead of a compact index.
    passed = data.get("result") in {"baseline_run_passed", "mqtt_run_passed", "secure_boot_run_passed"}
    return passed, "legacy explicit run pass" if passed else "unrecognised or unsuccessful manifest"


def inspect_trial(directory: Path, return_code: int, previous: set[Path] | None = None) -> dict:
    record = {"return_code": return_code, "success": False, "reason": None,
              "manifest": None, "uart_has_ERROR": None, "uart_logs": [],
              "uart_issue": None}
    manifests = sorted(set(directory.glob("*/manifest.json")) - (previous or set()))
    if len(manifests) != 1:
        record["reason"] = f"expected one run manifest, found {len(manifests)}"
        record["uart_issue"] = "no unambiguous run directory"
        return record
    path = manifests[0]
    record["manifest"] = str(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        record["success"], record["reason"] = success_from_manifest(data, return_code)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        record["reason"] = f"unreadable/invalid manifest: {exc}"

    # Read only UART captures in this invocation's new result, even on failure.
    logs = sorted(path.parent.glob("uart*.log"))
    if not logs:
        record["uart_issue"] = "UART log missing"
        return record
    found = False
    available = False
    issues = []
    for log in logs:
        if log.is_symlink():
            issues.append(f"refused UART symlink: {log.name}")
            continue
        record["uart_logs"].append(str(log))
        try:
            content = log.read_bytes()
            if not content:
                issues.append(f"empty UART log: {log.name}")
            else:
                available = True
                found = found or bool(ERROR_WORD.search(content))
        except OSError as exc:
            issues.append(f"unreadable UART log: {log.name}: {exc}")
    # A positive match is known even if another capture is unreadable.
    record["uart_has_ERROR"] = True if found else (False if available and not issues else None)
    record["uart_issue"] = "; ".join(issues) or None
    return record


def save_summary(batch: Path, summary: dict) -> None:
    rows = summary["trials"]
    total = len(rows)
    successes = sum(row["success"] for row in rows)
    errors = sum(row["uart_has_ERROR"] is True for row in rows)
    known = sum(row["uart_has_ERROR"] is not None for row in rows)
    summary.update(attempted_runs=total, successful_runs=successes,
                   success_percent=100 * successes / total if total else None,
                   runs_with_UART_ERROR=errors,
                   UART_ERROR_percent_of_attempted=100 * errors / total if total else None,
                   UART_ERROR_percent_of_known=100 * errors / known if known else None,
                   UART_unknown_runs=total - known)
    temporary = batch / "summary.json.tmp"
    temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    temporary.replace(batch / "summary.json")
    if total:
        print(f"\nSuccess: {successes}/{total} ({summary['success_percent']:.2f}%). "
              f"UART ERROR: {errors}/{total} ({summary['UART_ERROR_percent_of_attempted']:.2f}%). "
              f"UART unknown: {total - known}.\nSummary: {batch / 'summary.json'}", flush=True)


def print_plan(root: Path, runs: int) -> None:
    print(f"Repository: {root}\nTrials: {runs}\n"
          "EXECUTION WILL DELETE all contents (including hidden files and keys) of:\n"
          + "\n".join(f"  {root / name}" for name in CLEAN_DIRS))
    print("It will remove ALL containers, images, volumes, unused custom networks "
          "and default-builder cache on the selected LOCAL Docker daemon, including "
          "unrelated projects. Gateway Docker is managed only by the framework.\n"
          "+ sudo find -P <each directory above> -xdev -mindepth 1 -delete\n"
          "+ docker rm -f <each container from docker ps -aq>\n"
          "+ docker volume rm <each volume from docker volume ls -q>\n"
          "+ docker system prune --all --force --volumes\n"
          "+ docker builder prune --all --force\n"
          "+ ./scripts/dev.sh build-image\n"
          "+ python3 scripts/provision_certificates.py\n"
          f"+ ./scripts/dev.sh python scripts/resolve_campaign.py {CAMPAIGN}\n"
          f"Select the lexically first YAML under {CASES}.\n"
          "For each trial, in sequence:\n"
          "+ ./scripts/dev.sh experiment-gateway run --experiment <first case> "
          "--results-dir results/reliability/<batch>/runs\n"
          "Full run path on every trial; no campaign repetitions/runtime-only mode.\n"
          "Requires normal-user Docker access, sudo, existing SSH/Wi-Fi configuration "
          "and the configured gateway/board. Setup runs once; secrets/image persist "
          "between trials. No short gateway-lock timeout is imposed.")


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runs", type=positive_int, default=10)
    parser.add_argument("--execute", action="store_true", help="perform the destructive reset and hardware runs")
    parser.add_argument("--dry-run", action="store_true", help="print the plan only (also the default)")
    args = parser.parse_args(argv)
    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run are mutually exclusive")
    root = args.repo_root.resolve()
    batch = None
    summary = None
    try:
        validate_root(root)
        print_plan(root, args.runs)
        if not args.execute:
            print("\nDry run only. Add --execute to perform this plan.")
            return 0
        if os.geteuid() == 0:
            raise ValueError("Run as your normal user; this script uses sudo only for directory cleanup.")
        require_local_docker(root)
        clean_workspace(root)
        purge_docker(root)
        command(["./scripts/dev.sh", "build-image"], root)
        # This repository provisioner owns its own pinned Docker runtime. Running
        # it through dev.sh would require unsupported Docker-in-Docker/socket access.
        command([sys.executable, "scripts/provision_certificates.py"], root)
        command(["./scripts/dev.sh", "python", "scripts/resolve_campaign.py", CAMPAIGN], root)
        cases = sorted((root / CASES).glob("*.yaml"))
        if not cases:
            raise ValueError("Campaign resolution produced no cases")
        case = cases[0].relative_to(root).as_posix()
        print(f"Resolved {len(cases)} case(s); using only {case}", flush=True)
        batch = root / "results" / "reliability" / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        batch.mkdir(parents=True, mode=0o700)
        revision = command(["git", "rev-parse", "HEAD"], root, check=False, capture=True)
        summary = {"requested_runs": args.runs, "repository": str(root),
                   "git_commit": revision.stdout.strip() if revision.returncode == 0 else None,
                   "selected_case": case, "resolved_case_count": len(cases),
                   "success_definition": "zero process/run exit, explicit manifest completion; current schema also requires finalized accepted capture",
                   "UART_ERROR_definition": "case-sensitive whole word ERROR; missing/empty/unreadable captures are unknown",
                   "status": "running", "trials": []}
        save_summary(batch, summary)
        # Share a parent so the framework allocates a new sequential run ID.
        # A fresh parent for each invocation would repeat the same run ID.
        trials_root = batch / "runs"
        trials_root.mkdir()
        for index in range(1, args.runs + 1):
            previous = set(trials_root.glob("*/manifest.json"))
            argv_run = ["./scripts/dev.sh", "experiment-gateway", "run", "--experiment", case,
                        "--results-dir", trials_root.relative_to(root).as_posix()]
            print(f"\nTrial {index}/{args.runs}", flush=True)
            interrupted = False
            try:
                return_code = command(argv_run, root, check=False).returncode
            except KeyboardInterrupt:
                return_code, interrupted = 130, True
            except OSError as exc:
                print(f"Could not launch trial: {exc}", file=sys.stderr)
                return_code = 127
            row = inspect_trial(trials_root, return_code, previous)
            row.update(index=index, command=argv_run)
            summary["trials"].append(row)
            summary["status"] = "interrupted" if interrupted else "running"
            save_summary(batch, summary)
            if interrupted:
                return 130
        summary["status"] = "completed"
        save_summary(batch, summary)
        return 0 if all(row["success"] for row in summary["trials"]) else 1
    except KeyboardInterrupt:
        print("Interrupted; no further commands will be launched.", file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Reliability test stopped: {exc}", file=sys.stderr)
        if batch is not None and summary is not None:
            summary.update(status="aborted", error=str(exc))
            save_summary(batch, summary)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
