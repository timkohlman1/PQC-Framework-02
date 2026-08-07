#!/usr/bin/env python3
"""Plan and execute grouped controlled network-degradation measurements."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import itertools
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import experiment
from framework.network_degradation import gateway_network_degradation_preflight_script


RESULT_DIRECTORY_RE = re.compile(r"(?:^Result directory:|;\s*directory:)\s*(.+?)\s*$")


def _validate_grid(grid: dict[str, Any]) -> None:
    profiles = grid.get("profiles")
    dimensions = grid.get("dimensions")
    if not isinstance(profiles, dict) or not profiles or not all(
        isinstance(name, str) and name and isinstance(path, str) and path
        for name, path in profiles.items()
    ):
        raise ValueError("grid profiles must be a non-empty mapping of names to paths")
    if not isinstance(dimensions, dict):
        raise ValueError("grid dimensions must be a mapping")
    expected = {"rate_kbit", "rtt_ms", "loss_percent", "mtu"}
    if set(dimensions) != expected:
        raise ValueError(
            "grid dimensions must contain exactly rate_kbit, rtt_ms, loss_percent, and mtu"
        )
    for name in expected:
        values = dimensions[name]
        if not isinstance(values, dict) or not values:
            raise ValueError(f"grid dimension {name} must be a non-empty mapping")


def expand_grid(grid: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_grid(grid)
    dimensions = grid["dimensions"]
    cases: list[dict[str, Any]] = []
    for (profile_name, profile_path), rate, rtt, loss, mtu in itertools.product(
        grid["profiles"].items(),
        dimensions["rate_kbit"].values(),
        dimensions["rtt_ms"].values(),
        dimensions["loss_percent"].values(),
        dimensions["mtu"].values(),
    ):
        cases.append(
            {
                "profile_name": profile_name,
                "profile": profile_path,
                "rate_kbit": int(rate),
                "rtt_ms": int(rtt),
                "loss_percent": float(loss),
                "mtu": int(mtu),
            }
        )
    return cases


def _allowed_dimension_values(grid: dict[str, Any], name: str) -> set[int | float]:
    return {value for value in grid["dimensions"][name].values()}


def _filter_cases(
    grid: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    profiles: list[str] | None,
    rates: list[int] | None,
    rtts: list[int] | None,
    losses: list[float] | None,
    mtus: list[int] | None,
) -> list[dict[str, Any]]:
    selectors: list[tuple[str, list[Any] | None, set[Any]]] = [
        ("profile", profiles, set(grid["profiles"])),
        ("rate_kbit", rates, _allowed_dimension_values(grid, "rate_kbit")),
        ("rtt_ms", rtts, _allowed_dimension_values(grid, "rtt_ms")),
        ("loss_percent", losses, _allowed_dimension_values(grid, "loss_percent")),
        ("mtu", mtus, _allowed_dimension_values(grid, "mtu")),
    ]
    for label, requested, allowed in selectors:
        if requested is None:
            continue
        unknown = [value for value in requested if value not in allowed]
        if unknown:
            raise ValueError(
                f"unsupported {label} selection(s): {unknown}; allowed: {sorted(allowed, key=str)}"
            )

    selected = []
    for case in cases:
        if profiles is not None and case["profile_name"] not in profiles:
            continue
        if rates is not None and case["rate_kbit"] not in rates:
            continue
        if rtts is not None and case["rtt_ms"] not in rtts:
            continue
        if losses is not None and case["loss_percent"] not in losses:
            continue
        if mtus is not None and case["mtu"] not in mtus:
            continue
        selected.append(case)
    return selected


def _group_cases(cases: list[dict[str, Any]]) -> OrderedDict[str, list[dict[str, Any]]]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for case in cases:
        grouped.setdefault(case["profile_name"], []).append(case)
    return grouped


def _case_id(base_id: str, case: dict[str, Any], repetition: int) -> str:
    loss = f"{case['loss_percent']:g}".replace(".", "p")
    return (
        f"{base_id}__rate_{case['rate_kbit']}kbit__rtt_{case['rtt_ms']}ms"
        f"__loss_{loss}pct__mtu_{case['mtu']}__rep_{repetition:02d}"
    )


def materialise_case(
    *,
    repo_root: Path,
    output_dir: Path,
    interface: str,
    ifb_interface: str,
    case: dict[str, Any],
    repetition: int,
) -> Path:
    source = repo_root / case["profile"]
    config = experiment.load_config(source)
    base_id = str(config["id"])
    case_id = _case_id(base_id, case, repetition)
    description = (
        str(config.get("description", ""))
        + f" Network degradation: {case['rate_kbit']} kbit/s symmetric, {case['rtt_ms']} ms RTT, "
        + f"{case['loss_percent']:g}% independent loss per direction, MTU {case['mtu']}."
    ).strip()
    lines = source.read_text(encoding="utf-8").splitlines()
    rendered: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("id:"):
            rendered.append(f"id: {case_id}")
            continue
        if line.startswith("description:"):
            rendered.append(f"description: {description}")
            continue
        rendered.append(line)
        if line == "network:":
            rendered.extend(
                [
                    "  degradation:",
                    "    enabled: true",
                    f"    interface: {interface}",
                    f"    ifb_interface: {ifb_interface}",
                    f"    rate_kbit: {case['rate_kbit']}",
                    f"    rtt_ms: {case['rtt_ms']}",
                    f"    loss_percent: {case['loss_percent']:g}",
                    f"    mtu: {case['mtu']}",
                    "    management_safe: true",
                ]
            )
            inserted = True
    if not inserted:
        raise ValueError(
            f"base profile does not contain a top-level network mapping: {source}"
        )
    target = output_dir / f"{case_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    return target


def _run_streamed(command: list[str], *, cwd: Path) -> tuple[int, list[str]]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    lines: list[str] = []
    for raw in process.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        print(line, flush=True)
    return process.wait(), lines


def _result_manifest_from_output(lines: list[str], *, repo_root: Path) -> Path:
    candidates: list[Path] = []
    for line in lines:
        match = RESULT_DIRECTORY_RE.search(line)
        if not match:
            continue
        candidate = Path(match.group(1))
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        candidates.append(candidate / "manifest.json")
    for candidate in reversed(candidates):
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("profile preparation completed without a discoverable result manifest")



def _network_degradation_preflight_command(
    *, repo_root: Path, profile_path: str, interface: str
) -> list[str]:
    bundle = experiment.load_experiment_bundle(repo_root / profile_path)
    gateway_alias = str(bundle["host"]["alias"])
    script = gateway_network_degradation_preflight_script(interface)
    return ["ssh", gateway_alias, f"sh -c {shlex.quote(script)}"]

def _preparation_command(
    *, repo_root: Path, profile_path: str, results_dir: Path, force: bool
) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "scripts" / "experiment.py"),
        "run",
        "--experiment",
        str(repo_root / profile_path),
        "--results-dir",
        str(results_dir),
    ]
    if force:
        command.append("--force")
    return command


def _measurement_command(
    *,
    repo_root: Path,
    profile_path: Path,
    results_dir: Path,
    preparation_manifest: Path | str,
) -> list[str]:
    return [
        sys.executable,
        str(repo_root / "scripts" / "experiment.py"),
        "run",
        "--experiment",
        str(profile_path),
        "--results-dir",
        str(results_dir),
        "--runtime-only",
        "--profile-preparation-manifest",
        str(preparation_manifest),
    ]


def _append_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Run only this named crypto profile. Repeat to select multiple profiles.",
    )
    parser.add_argument(
        "--rate-kbit",
        action="append",
        type=int,
        dest="rates",
        help="Run only this symmetric rate. Repeat to select multiple rates.",
    )
    parser.add_argument(
        "--rtt-ms",
        action="append",
        type=int,
        dest="rtts",
        help="Run only this RTT. Repeat to select multiple RTTs.",
    )
    parser.add_argument(
        "--loss-percent",
        action="append",
        type=float,
        dest="losses",
        help="Run only this loss percentage. Repeat to select multiple loss levels.",
    )
    parser.add_argument(
        "--mtu",
        action="append",
        type=int,
        dest="mtus",
        help="Run only this MTU. Repeat to select multiple MTUs.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grid",
        type=Path,
        default=Path(
            "configs/experiment_grids/tls_handshake_first_telemetry_network_degradation.yaml"
        ),
    )
    parser.add_argument(
        "--interface",
        required=True,
        help="Dedicated gateway experiment-facing interface. Must not carry SSH/VPN management traffic.",
    )
    parser.add_argument("--ifb-interface", default="ifb-pqc0")
    parser.add_argument("--repeat-count", type=int, default=1)
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--case-offset",
        type=int,
        default=0,
        help="Skip this many selected cases after filtering, useful for bounded chunks.",
    )
    parser.add_argument(
        "--case-limit",
        type=int,
        default=None,
        help="Run at most this many selected cases after --case-offset.",
    )
    _append_selection_args(parser)
    args = parser.parse_args(argv)

    if args.repeat_count < 1:
        parser.error("--repeat-count must be at least 1")
    if args.case_offset < 0:
        parser.error("--case-offset must be zero or greater")
    if args.case_limit is not None and args.case_limit < 1:
        parser.error("--case-limit must be at least 1")

    repo_root = Path(__file__).resolve().parents[1]
    grid_path = args.grid if args.grid.is_absolute() else repo_root / args.grid
    grid = experiment.load_config(grid_path)
    all_cases = expand_grid(grid)
    try:
        selected_cases = _filter_cases(
            grid,
            all_cases,
            profiles=args.profiles,
            rates=args.rates,
            rtts=args.rtts,
            losses=args.losses,
            mtus=args.mtus,
        )
    except ValueError as exc:
        parser.error(str(exc))
    selected_cases = selected_cases[args.case_offset :]
    if args.case_limit is not None:
        selected_cases = selected_cases[: args.case_limit]
    if not selected_cases:
        parser.error("case selection produced zero measurements")

    grouped = _group_cases(selected_cases)
    output_dir = (
        repo_root
        / ".pqc-generated-state"
        / "network-degradation-grid"
        / str(grid["id"])
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan: dict[str, Any] = {
        "grid_id": grid["id"],
        "full_grid_case_count": len(all_cases),
        "selected_base_case_count": len(selected_cases),
        "repeat_count": args.repeat_count,
        "selected_measurement_count": len(selected_cases) * args.repeat_count,
        "selected_profile_count": len(grouped),
        "interface": args.interface,
        "ifb_interface": args.ifb_interface,
        "selection": {
            "profiles": args.profiles,
            "rate_kbit": args.rates,
            "rtt_ms": args.rtts,
            "loss_percent": args.losses,
            "mtu": args.mtus,
            "case_offset": args.case_offset,
            "case_limit": args.case_limit,
        },
        "profiles": [],
    }
    final_rc = 0

    for profile_name, profile_cases in grouped.items():
        base_profile = str(profile_cases[0]["profile"])
        preflight_command = _network_degradation_preflight_command(
            repo_root=repo_root, profile_path=base_profile, interface=args.interface
        )
        preparation_command = _preparation_command(
            repo_root=repo_root,
            profile_path=base_profile,
            results_dir=args.results_dir,
            force=args.force,
        )
        profile_record: dict[str, Any] = {
            "profile_name": profile_name,
            "base_profile": base_profile,
            "preflight": {
                "command": preflight_command,
                "return_code": None,
            },
            "preparation": {
                "command": preparation_command,
                "return_code": None,
                "manifest": None,
                "build_flash_smoke_once": True,
            },
            "measurements": [],
        }
        plan["profiles"].append(profile_record)

        if args.plan_only:
            preparation_manifest: Path | str = "<profile-preparation-manifest>"
        else:
            print(
                f"\n=== Checking network degradation prerequisites for {profile_name} ===",
                flush=True,
            )
            preflight_rc, preflight_output = _run_streamed(preflight_command, cwd=repo_root)
            profile_record["preflight"]["return_code"] = preflight_rc
            if preflight_rc != 0:
                final_rc = preflight_rc
                profile_record["preflight"]["failure_stage"] = "network_degradation_preflight"
                error_lines = [line for line in preflight_output if "PQC_NETDEG_ERROR=" in line]
                if error_lines:
                    print(
                        "Error: network degradation preflight failed: " + error_lines[-1].split("PQC_NETDEG_ERROR=", 1)[1],
                        file=sys.stderr,
                    )
                else:
                    print("Error: network degradation preflight failed", file=sys.stderr)
                if args.stop_on_failure:
                    break
                continue

            print(
                f"\n=== Preparing crypto profile {profile_name} "
                f"({len(profile_cases) * args.repeat_count} measurements) ===",
                flush=True,
            )
            preparation_rc, preparation_output = _run_streamed(
                preparation_command, cwd=repo_root
            )
            profile_record["preparation"]["return_code"] = preparation_rc
            if preparation_rc != 0:
                final_rc = preparation_rc
                profile_record["preparation"]["failure_stage"] = "profile_preparation"
                if args.stop_on_failure:
                    break
                # Measurements cannot safely run without a successful build/flash/smoke.
                continue
            try:
                preparation_manifest = _result_manifest_from_output(
                    preparation_output, repo_root=repo_root
                )
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                final_rc = 2
                profile_record["preparation"]["failure_stage"] = "manifest_discovery"
                if args.stop_on_failure:
                    break
                continue
            profile_record["preparation"]["manifest"] = str(preparation_manifest)

        stop_profile = False
        for repetition in range(1, args.repeat_count + 1):
            for case in profile_cases:
                profile_path = materialise_case(
                    repo_root=repo_root,
                    output_dir=output_dir,
                    interface=args.interface,
                    ifb_interface=args.ifb_interface,
                    case=case,
                    repetition=repetition,
                )
                command = _measurement_command(
                    repo_root=repo_root,
                    profile_path=profile_path,
                    results_dir=args.results_dir,
                    preparation_manifest=preparation_manifest,
                )
                record = {
                    "case": case,
                    "repetition": repetition,
                    "profile": str(profile_path),
                    "command": command,
                    "return_code": None,
                }
                profile_record["measurements"].append(record)
                if args.plan_only:
                    continue
                completed = subprocess.run(command, cwd=repo_root, check=False)
                record["return_code"] = completed.returncode
                if completed.returncode != 0:
                    final_rc = completed.returncode
                    if args.stop_on_failure:
                        stop_profile = True
                        break
            if stop_profile:
                break
        if stop_profile:
            break

    plan_path = output_dir / "plan.json"
    plan_path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Grid cases available: {len(all_cases)}")
    print(f"Selected cases: {len(selected_cases)}")
    print(f"Selected profiles: {len(grouped)}")
    print(f"Measurements: {len(selected_cases) * args.repeat_count}")
    print(f"Profile preparations: {len(grouped)} (build + flash + smoke once each)")
    print(f"Plan: {plan_path}")
    return final_rc


if __name__ == "__main__":
    raise SystemExit(main())
