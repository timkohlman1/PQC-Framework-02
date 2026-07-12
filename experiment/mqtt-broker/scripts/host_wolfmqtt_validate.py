#!/usr/bin/env python3
"""Build and run the pinned wolfMQTT example with pinned wolfSSL on the host."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

EVIDENCE = {
    "evidence_class": "host_side",
    "evidence_label": "host-side wolfMQTT/wolfSSL validation utility evidence",
    "claims_stm32_success": False,
    "claims_wifi_module_success": False,
    "claims_lwip_on_stm32_success": False,
    "claims_wolfssl_on_stm32_success": False,
    "claims_wolfmqtt_on_stm32_success": False,
    "claims_end_to_end_wireless_success": False,
}

ACTIONS = {"build", "help", "run"}

RUNTIME_SUCCESS_MARKERS = {
    "tls_socket_connected": "MQTT Socket Connect: Success (0)",
    "mqtt_connected": "MQTT Connect: Proto (v3.1.1), Success (0)",
    "mqtt_connect_acknowledged": "MQTT Connect Ack: Return Code 0",
    "mqtt_subscribed": "MQTT Subscribe: Success (0)",
    "mqtt_published": "MQTT Publish:",
    "mqtt_message_received": "MQTT Message: Done",
    "mqtt_disconnected": "MQTT Disconnect: Success (0)",
    "socket_disconnected": "MQTT Socket Disconnect: Success (0)",
}


class WrapperArguments:
    def __init__(
        self,
        action: str,
        build_dir: str = "build/host-wolfmqtt",
        result_json: str | None = None,
    ) -> None:
        self.action = action
        self.build_dir = build_dir
        self.result_json = result_json


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run(command: list[str], *, cwd: Path | None = None) -> int:
    print("command=" + subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def run_captured(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[int, str]:
    print("command=" + subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    combined = completed.stdout + completed.stderr
    return completed.returncode, combined


def evaluate_runtime_output(output: str) -> dict[str, bool]:
    markers = {
        name: marker in output
        for name, marker in RUNTIME_SUCCESS_MARKERS.items()
    }
    markers["mqtt_publish_succeeded"] = (
        markers["mqtt_published"]
        and "Success (0)" in next(
            (
                line
                for line in output.splitlines()
                if line.startswith("MQTT Publish:")
            ),
            "",
        )
    )
    return markers


def usage_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build or run the Phase M9 host-only wolfMQTT/wolfSSL validation client."
    )
    result.add_argument("action", choices=tuple(sorted(ACTIONS)))
    result.add_argument("--build-dir", default="build/host-wolfmqtt")
    result.add_argument("--result-json")
    return result


def split_arguments(argv: Sequence[str] | None) -> tuple[list[str], list[str]]:
    """Split wrapper and client arguments at a preserved boundary token.

    ``--client-args`` is the documented PowerShell-safe boundary. ``--`` is
    retained for direct POSIX/Python invocation.
    """
    raw = list(argv) if argv is not None else list(sys.argv[1:])
    boundaries = [
        (raw.index(token), token)
        for token in ("--client-args", "--")
        if token in raw
    ]
    if not boundaries:
        return raw, []
    separator, _ = min(boundaries)
    return raw[:separator], raw[separator + 1 :]


def parse_wrapper_arguments(tokens: Sequence[str]) -> WrapperArguments:
    """Parse wrapper options deterministically, independent of option ordering."""
    action: str | None = None
    build_dir = "build/host-wolfmqtt"
    result_json: str | None = None

    index = 0
    values = list(tokens)
    while index < len(values):
        token = values[index]

        if token in ("-h", "--help"):
            usage_parser().print_help()
            raise SystemExit(0)

        if token in ACTIONS:
            if action is not None:
                usage_parser().error(f"multiple actions supplied: {action!r} and {token!r}")
            action = token
            index += 1
            continue

        if token in ("--build-dir", "--result-json"):
            if index + 1 >= len(values):
                usage_parser().error(f"{token} requires a value")
            value = values[index + 1]
            if token == "--build-dir":
                build_dir = value
            else:
                result_json = value
            index += 2
            continue

        usage_parser().error(f"unrecognized wrapper argument: {token}")

    if action is None:
        usage_parser().error("an action is required")

    return WrapperArguments(
        action=action,
        build_dir=build_dir,
        result_json=result_json,
    )


def print_evidence(*, scope: str) -> None:
    print(f"evidence_class={EVIDENCE['evidence_class']}")
    print(f"evidence_label={EVIDENCE['evidence_label']}")
    print(f"evidence_scope={scope}")
    for key, value in EVIDENCE.items():
        if key.startswith("claims_"):
            print(f"{key}={str(value).lower()}")


def print_local_help() -> None:
    print(
        "Phase M9 host wolfMQTT/wolfSSL utility\n"
        "\n"
        "Actions:\n"
        "  build  Configure and build the native host client. No client is executed.\n"
        "  help   Print this local-only help. No build or network access is performed.\n"
        "  run    Build and execute the client with explicit arguments after --.\n"
        "\n"
        "Wrapper options may appear before or after the action:\n"
        "  --build-dir <path>\n"
        "  --result-json <path>\n"
        "\n"
        "Examples:\n"
        "  host_wolfmqtt_validate.py build\n"
        "  host_wolfmqtt_validate.py help\n"
        "  host_wolfmqtt_validate.py run --result-json results/result.json --client-args -h 10.1.1.18 -p 8883 -t\n"
        "\n"
        "Safety:\n"
        "  Through scripts/dev.ps1, use --client-args and quote each dash-prefixed\n  wolfMQTT token (for example '-h', '-p', and '-i') so PowerShell passes\n  it as data rather than binding it as a dev.ps1 parameter.\n  The run action rejects an empty client argument list so the upstream\n"
        "  example cannot silently use its public default broker or plaintext defaults.\n"
        "  Use only explicitly selected broker endpoints and temporary certificate material."
    )


def write_result(
    path: str | None,
    *,
    action: str,
    scope: str,
    return_code: int,
    runtime_markers: dict[str, bool] | None = None,
) -> None:
    if not path:
        return
    output = dict(EVIDENCE)
    marker_evidence = runtime_markers or {}
    required_runtime_markers = (
        "tls_socket_connected",
        "mqtt_connected",
        "mqtt_connect_acknowledged",
        "mqtt_subscribed",
        "mqtt_publish_succeeded",
        "mqtt_message_received",
        "mqtt_disconnected",
        "socket_disconnected",
    )
    broker_compatibility_confirmed = (
        action == "run"
        and return_code == 0
        and all(marker_evidence.get(name, False) for name in required_runtime_markers)
    )
    output.update(
        {
            "action": action,
            "evidence_scope": scope,
            "return_code": return_code,
            "command_succeeded": return_code == 0,
            "runtime_markers": marker_evidence,
            "broker_compatibility_confirmed": broker_compatibility_confirmed,
        }
    )
    destination = repository_root() / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    wrapper_tokens, client_args = split_arguments(argv)
    args = parse_wrapper_arguments(wrapper_tokens)

    if args.action == "help":
        print_evidence(scope="local_help_only")
        print_local_help()
        write_result(
            args.result_json,
            action=args.action,
            scope="local_help_only",
            return_code=0,
        )
        return 0

    if args.action == "run" and not client_args:
        print_evidence(scope="rejected_before_execution")
        print(
            "error=run requires explicit wolfMQTT client arguments after --; "
            "the upstream example defaults are intentionally not permitted"
        )
        write_result(
            args.result_json,
            action=args.action,
            scope="rejected_before_execution",
            return_code=2,
        )
        return 2

    scope = "host_build_only" if args.action == "build" else "host_runtime_command"
    print_evidence(scope=scope)

    root = repository_root()
    source = root / "experiment/mqtt-broker/host-wolfmqtt"
    build = root / args.build_dir
    executable = build / "pqc_host_wolfmqtt_client"

    rc = run(["cmake", "-S", str(source), "-B", str(build), "-G", "Ninja"])
    if rc == 0:
        rc = run(["cmake", "--build", str(build), "--target", "pqc_host_wolfmqtt_client"])
    if rc != 0 or args.action == "build":
        write_result(
            args.result_json,
            action=args.action,
            scope=scope,
            return_code=rc,
        )
        return rc

    if not executable.is_file():
        print(f"host client executable not found: {executable}")
        write_result(
            args.result_json,
            action=args.action,
            scope=scope,
            return_code=2,
        )
        return 2

    rc, runtime_output = run_captured([str(executable), *client_args])
    runtime_markers = evaluate_runtime_output(runtime_output)
    write_result(
        args.result_json,
        action=args.action,
        scope=scope,
        return_code=rc,
        runtime_markers=runtime_markers,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
