#!/usr/bin/env python3
"""Run every runnable wolfBoot algorithm profile sequentially.

This script discovers canonical wolfBoot algorithm profiles under
configs/algorithms/, then runs the normal experiment workflow once per profile.

It is intended to be launched through the gateway-capable project wrapper, e.g.:

    .\\scripts\\dev.ps1 python-gateway scripts/run_all_wolfboot_profiles.py

Each experiment is allowed to finish independently. A failed profile is recorded
and the next profile is still executed. After all profiles have run, this script
returns 0 only when every profile passed; otherwise it returns 1.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ALGORITHMS_DIR = Path("configs/algorithms")
DEFAULT_EXPERIMENT = Path("configs/experiments/baseline_direct_uart.yaml")
DEFAULT_TARGET = "stm32l4r5_wolfboot"
REQUIRED_PROFILE_SECTIONS = {"build", "signing", "experiment", "boot"}


@dataclass(frozen=True)
class AlgorithmProfile:
    algorithm_id: str
    path: Path


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_profile_metadata(path: Path) -> tuple[str | None, str | None, set[str]]:
    """Read only the small top-level YAML shape needed for discovery.

    Avoids adding a PyYAML dependency to this orchestration script.
    """
    algorithm_id: str | None = None
    target: str | None = None
    profile_sections: set[str] = set()
    in_profiles = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0:
            in_profiles = stripped == "profiles:"
            if stripped.startswith("id:"):
                algorithm_id = _strip_yaml_scalar(stripped.split(":", 1)[1])
            elif stripped.startswith("target:"):
                target = _strip_yaml_scalar(stripped.split(":", 1)[1])
            continue

        if in_profiles and indent == 2 and stripped.endswith(":"):
            profile_sections.add(stripped[:-1].strip())

    return algorithm_id, target, profile_sections


def discover_profiles(algorithms_dir: Path, target: str) -> list[AlgorithmProfile]:
    """Discover complete wolfBoot algorithm profiles in deterministic order."""
    profiles: list[AlgorithmProfile] = []

    for path in sorted(algorithms_dir.glob("*.yaml")):
        algorithm_id, profile_target, sections = _read_profile_metadata(path)

        if not algorithm_id:
            print(f"SKIP {path}: no top-level id", file=sys.stderr)
            continue
        if profile_target != target:
            print(
                f"SKIP {path}: target={profile_target!r}, expected {target!r}",
                file=sys.stderr,
            )
            continue

        missing = REQUIRED_PROFILE_SECTIONS - sections
        if missing:
            print(
                f"SKIP {path}: incomplete wolfBoot profile; missing "
                + ", ".join(sorted(missing)),
                file=sys.stderr,
            )
            continue

        profiles.append(AlgorithmProfile(algorithm_id=algorithm_id, path=path))

    return profiles


def run_profile(
    *,
    repo_root: Path,
    experiment: Path,
    profile: AlgorithmProfile,
    force: bool,
    uart_duration_seconds: int | None,
) -> int:
    command = [
        sys.executable,
        "scripts/experiment.py",
        "run",
        "--experiment",
        experiment.as_posix(),
        "--boot-mode",
        "wolfboot",
        "--boot-algorithm",
        profile.algorithm_id,
    ]
    if force:
        command.append("--force")
    if uart_duration_seconds is not None:
        command.extend(["--uart-duration-seconds", str(uart_duration_seconds)])

    print()
    print("=" * 78)
    print(f"wolfBoot profile: {profile.algorithm_id}")
    print(f"config:           {profile.path.as_posix()}")
    print("command:          " + " ".join(command))
    print("=" * 78, flush=True)

    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
    )

    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(
        f"\n[{status}] {profile.algorithm_id} "
        f"(return code {completed.returncode})",
        flush=True,
    )
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and run all canonical wolfBoot algorithm profiles "
            "sequentially, continuing after failures."
        )
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        default=DEFAULT_EXPERIMENT,
        help=(
            "Non-TLS experiment used as the application/runtime workload. "
            f"Default: {DEFAULT_EXPERIMENT.as_posix()}"
        ),
    )
    parser.add_argument(
        "--algorithms-dir",
        type=Path,
        default=DEFAULT_ALGORITHMS_DIR,
        help=f"Algorithm profile directory. Default: {DEFAULT_ALGORITHMS_DIR.as_posix()}",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"Only run profiles for this target. Default: {DEFAULT_TARGET}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass --force to every experiment run to force application rebuilds.",
    )
    parser.add_argument(
        "--uart-duration-seconds",
        type=int,
        default=None,
        help="Override the experiment CLI UART capture duration for every profile.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print discovered profiles without running hardware experiments.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent

    algorithms_dir = args.algorithms_dir
    if not algorithms_dir.is_absolute():
        algorithms_dir = repo_root / algorithms_dir

    experiment = args.experiment
    if not experiment.is_absolute():
        experiment = repo_root / experiment

    if not algorithms_dir.is_dir():
        print(f"Error: algorithm directory not found: {algorithms_dir}", file=sys.stderr)
        return 2
    if not experiment.is_file():
        print(f"Error: experiment config not found: {experiment}", file=sys.stderr)
        return 2

    profiles = discover_profiles(algorithms_dir, args.target)
    if not profiles:
        print(
            f"Error: no complete wolfBoot profiles found in {algorithms_dir}",
            file=sys.stderr,
        )
        return 2

    print(f"Discovered {len(profiles)} wolfBoot profile(s):")
    for profile in profiles:
        print(f"  - {profile.algorithm_id}: {profile.path.relative_to(repo_root)}")

    if args.list_only:
        return 0

    results: list[tuple[AlgorithmProfile, int]] = []
    experiment_relative = experiment.relative_to(repo_root)

    for profile in profiles:
        return_code = run_profile(
            repo_root=repo_root,
            experiment=experiment_relative,
            profile=profile,
            force=args.force,
            uart_duration_seconds=args.uart_duration_seconds,
        )
        results.append((profile, return_code))

    print()
    print("=" * 78)
    print("wolfBoot profile suite summary")
    print("=" * 78)

    failed = 0
    for profile, return_code in results:
        status = "PASS" if return_code == 0 else "FAIL"
        if return_code != 0:
            failed += 1
        print(f"{status:4}  rc={return_code:<3}  {profile.algorithm_id}")

    passed = len(results) - failed
    print("-" * 78)
    print(f"Total: {len(results)}  Passed: {passed}  Failed: {failed}")
    print(
        "All profiles were attempted; failures did not stop subsequent profiles."
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
