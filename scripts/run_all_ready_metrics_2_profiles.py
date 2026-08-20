#!/usr/bin/env python3
"""Run every Ready Metrics 2 experiment sequentially and stop on first failure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    profile_root = repo_root / "configs" / "experiments" / "applications" / "ready_metrics_2"
    experiment_cli = repo_root / "scripts" / "experiment.py"

    profiles = sorted(profile_root.rglob("*.yaml"))
    if not profiles:
        print(f"No Ready Metrics 2 profiles found under {profile_root}", file=sys.stderr)
        return 2

    print(f"Found {len(profiles)} Ready Metrics 2 profiles.")

    for index, profile in enumerate(profiles, start=1):
        relative_profile = profile.relative_to(repo_root)
        print()
        print("=" * 80)
        print(f"[{index}/{len(profiles)}] {relative_profile}")
        print("=" * 80)

        result = subprocess.run(
            [
                sys.executable,
                str(experiment_cli),
                "run",
                "--experiment",
                str(relative_profile),
            ],
            cwd=repo_root,
        )

        if result.returncode != 0:
            print()
            print(
                f"FAILED [{index}/{len(profiles)}]: {relative_profile} "
                f"(return code {result.returncode})",
                file=sys.stderr,
            )
            return result.returncode

        print(f"PASSED [{index}/{len(profiles)}]: {relative_profile}")

    print()
    print(f"All {len(profiles)} Ready Metrics 2 profiles passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
