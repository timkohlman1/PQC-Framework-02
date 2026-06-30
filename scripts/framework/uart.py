"""Remote UART monitor and capture helpers.

This module supports two UART workflows:

* ad hoc UART monitoring, which writes timestamped logs under ``results/adhoc/``
  and passes when a bounded monitor command captures any UART data
* run-scoped UART capture after flashing, which writes ``results/<run_id>/uart.log``
  and passes only when the configured boot and tick markers are present

All command runners are injectable so unit tests do not require SSH, UART
devices, a gateway, or hardware.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.manifest import update_manifest

UART_MARKER_MISSING_RETURN_CODE = 9
UART_NO_DATA_RETURN_CODE = 10
DEFAULT_CAPTURE_DURATION_SECONDS = 10
TIMEOUT_RETURN_CODE = 124
DEFAULT_RESTART_COMMAND = "reset-stm32a"
DEFAULT_RESTART_DELAY_SECONDS = 0.2


@dataclass(frozen=True)
class CommandExecution:
    """Captured output from one command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class UartResult:
    """Captured output and pass/fail status from one run-scoped UART capture."""

    return_code: int
    duration_seconds: float
    log_path: Path
    capture: CommandExecution
    device: str
    baud: int
    requested_duration_seconds: int
    expected_boot_message: str
    expected_tick_message: str
    expected_secure_boot_message: str | None
    boot_marker_present: bool
    tick_present: bool
    secure_boot_marker_present: bool | None
    data_captured: bool
    verification_time_ms: float | None
    verification_cycles: int | None
    verification_cpu_hz: int | None
    verification_result_code: int | None
    verification_time_source: str
    verification_time_measurement_method: str
    verification_time_limitations: str


@dataclass(frozen=True)
class UartMonitorResult:
    """Captured output and pass/fail status from one ad hoc UART monitor run."""

    return_code: int
    duration_seconds: float
    log_path: Path
    restart: CommandExecution | None
    capture: CommandExecution
    device: str
    baud: int
    requested_duration_seconds: int
    restart_requested: bool
    restart_command: str | None
    data_captured: bool


Runner = Callable[[list[str], Path], CommandExecution]


def construct_ssh_uart_capture_command(
    gateway_alias: str,
    uart_device: str,
    baud: int,
    duration_seconds: int,
) -> list[str]:
    """Construct the SSH command used to capture bounded UART output."""

    device = shlex.quote(uart_device)
    remote_command = (
        f"timeout {int(duration_seconds)}s sh -c "
        f"'stty -F {device} {int(baud)} cs8 -cstopb -parenb raw -echo && cat {device}'"
    )
    return ["ssh", gateway_alias, remote_command]


def construct_ssh_restart_command(
    gateway_alias: str,
    restart_command: str = DEFAULT_RESTART_COMMAND,
) -> list[str]:
    """Construct the SSH command used for an optional ad hoc monitor restart."""

    return ["ssh", gateway_alias, restart_command]


def construct_ssh_uart_monitor_with_restart_command(
    gateway_alias: str,
    uart_device: str,
    baud: int,
    duration_seconds: int,
    restart_command: str = DEFAULT_RESTART_COMMAND,
    restart_delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS,
) -> list[str]:
    """Construct one SSH command that starts UART capture before resetting.

    The reset command runs in a delayed background subshell after the UART
    device has been configured and before the bounded ``cat`` capture window
    starts. Reset stdout is redirected to stderr so the monitor stdout remains
    device UART data only.
    """

    device = shlex.quote(uart_device)
    restart_delay = f"{float(restart_delay_seconds):g}"
    script = (
        f"stty -F {device} {int(baud)} cs8 -cstopb -parenb raw -echo; "
        "stty_rc=$?; "
        'if [ "$stty_rc" -ne 0 ]; then exit "$stty_rc"; fi; '
        f"(sleep {restart_delay}; {restart_command} 1>&2) & "
        "reset_pid=$!; "
        f"timeout {int(duration_seconds)}s cat {device}; "
        "capture_rc=$?; "
        'wait "$reset_pid"; '
        "reset_rc=$?; "
        'if [ "$reset_rc" -ne 0 ]; then exit "$reset_rc"; fi; '
        'exit "$capture_rc"'
    )
    return ["ssh", gateway_alias, f"sh -c {shlex.quote(script)}"]


def default_runner(command: list[str], cwd: Path) -> CommandExecution:
    """Run a command without a shell and capture output and duration."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _capture_completed(return_code: int) -> bool:
    return return_code in {0, TIMEOUT_RETURN_CODE}


DEFAULT_VERIFICATION_TIME_SOURCE = "uart_explicit_verification_time_marker"
DEFAULT_VERIFICATION_TIME_UNAVAILABLE_SOURCE = "unavailable"
DEFAULT_VERIFICATION_TIME_METHOD = (
    "Parse explicit wolfBoot verification timing lines from captured UART output."
)
DEFAULT_VERIFICATION_TIME_UNAVAILABLE_LIMITATIONS = (
    "No explicit wolfBoot verification-time line was present in the captured UART output; "
    "verification_time_ms and verification_cycles are intentionally null rather than estimated."
)
DEFAULT_VERIFICATION_TIME_REPORTED_LIMITATIONS = (
    "Timing is reported by firmware over UART and includes only the values emitted by wolfBoot or the instrumented boot path; "
    "host-side UART capture latency is not used to derive these values."
)
_VERIFICATION_TIME_PATTERNS = [
    re.compile(
        r"\b(?:wolfboot|secure[-_ ]?boot)?[^\r\n]*verification(?: time)?[^\r\n]*?[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*ms\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bverification_time_ms\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
]
_VERIFICATION_CYCLE_PATTERNS = [
    re.compile(
        r"\b(?:wolfboot|secure[-_ ]?boot)?[^\r\n]*verification\s+cycles\s*[:=]\s*(?P<value>\d+)\s*(?:cycles)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bverification_cycles\s*[:=]\s*(?P<value>\d+)\b",
        re.IGNORECASE,
    ),
]
_VERIFICATION_CPU_HZ_PATTERNS = [
    re.compile(
        r"\b(?:wolfboot|secure[-_ ]?boot)?[^\r\n]*verification\s+(?:cpu[-_ ]?hz|clock)\s*[:=]\s*(?P<value>\d+)\s*(?:hz)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bverification_cpu_hz\s*[:=]\s*(?P<value>\d+)\b",
        re.IGNORECASE,
    ),
]
_VERIFICATION_RESULT_PATTERNS = [
    re.compile(
        r"\b(?:wolfboot|secure[-_ ]?boot)?[^\r\n]*verification\s+(?:result|return(?: code)?)\s*[:=]\s*(?P<value>-?\d+)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bverification_result(?:_code)?\s*[:=]\s*(?P<value>-?\d+)\b",
        re.IGNORECASE,
    ),
]


def parse_verification_time_ms(uart_output: str) -> float | None:
    """Parse an explicit wolfBoot verification-time value from UART output.

    The parser intentionally accepts only lines that contain explicit
    verification-time wording and a millisecond unit, or an explicit
    ``verification_time_ms`` key. It does not infer timing from host-side
    command duration or marker ordering.
    """

    for pattern in _VERIFICATION_TIME_PATTERNS:
        match = pattern.search(uart_output)
        if match is not None:
            value = float(match.group("value"))
            return int(value) if value.is_integer() else value
    return None


def _parse_first_int(patterns: list[re.Pattern[str]], uart_output: str) -> int | None:
    for pattern in patterns:
        match = pattern.search(uart_output)
        if match is not None:
            return int(match.group("value"))
    return None


def parse_verification_cycles(uart_output: str) -> int | None:
    """Parse explicit wolfBoot verification cycle count from UART output."""

    return _parse_first_int(_VERIFICATION_CYCLE_PATTERNS, uart_output)


def parse_verification_cpu_hz(uart_output: str) -> int | None:
    """Parse explicit CPU frequency used for cycle-to-ms conversion."""

    return _parse_first_int(_VERIFICATION_CPU_HZ_PATTERNS, uart_output)


def parse_verification_result_code(uart_output: str) -> int | None:
    """Parse explicit wolfBoot verification return code from UART output."""

    return _parse_first_int(_VERIFICATION_RESULT_PATTERNS, uart_output)


def _boot_timing_evidence(uart_output: str) -> dict[str, Any]:
    verification_time_ms = parse_verification_time_ms(uart_output)
    verification_cycles = parse_verification_cycles(uart_output)
    verification_cpu_hz = parse_verification_cpu_hz(uart_output)
    verification_result_code = parse_verification_result_code(uart_output)
    if verification_time_ms is None:
        return {
            "verification_time_ms": None,
            "verification_cycles": verification_cycles,
            "verification_cpu_hz": verification_cpu_hz,
            "verification_result_code": verification_result_code,
            "verification_time_source": DEFAULT_VERIFICATION_TIME_UNAVAILABLE_SOURCE,
            "measurement_method": DEFAULT_VERIFICATION_TIME_METHOD,
            "limitations": DEFAULT_VERIFICATION_TIME_UNAVAILABLE_LIMITATIONS,
        }
    return {
        "verification_time_ms": verification_time_ms,
        "verification_cycles": verification_cycles,
        "verification_cpu_hz": verification_cpu_hz,
        "verification_result_code": verification_result_code,
        "verification_time_source": DEFAULT_VERIFICATION_TIME_SOURCE,
        "measurement_method": DEFAULT_VERIFICATION_TIME_METHOD,
        "limitations": DEFAULT_VERIFICATION_TIME_REPORTED_LIMITATIONS,
    }


def _timestamped_monitor_log_path(results_root: Path) -> Path:
    adhoc_dir = results_root / "adhoc"
    adhoc_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    candidate = adhoc_dir / f"uart_monitor_{timestamp}.log"
    sequence = 1
    while candidate.exists():
        candidate = adhoc_dir / f"uart_monitor_{timestamp}_{sequence:02d}.log"
        sequence += 1
    return candidate


def _write_uart_capture_log(
    log_path: Path,
    repo_root: Path,
    capture_execution: CommandExecution,
    device: str,
    baud: int,
    requested_duration_seconds: int,
    expected_boot_message: str,
    expected_tick_message: str,
    expected_secure_boot_message: str | None,
    boot_marker_present: bool,
    tick_present: bool,
    secure_boot_marker_present: bool | None,
    data_captured: bool,
    restart_command: str | None,
    return_code: int,
    duration_seconds: float,
    boot_timing: dict[str, Any],
) -> None:
    lines = [
        "UART post-flash capture log",
        "===========================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"UART device: {device}",
        f"UART baud: {baud}",
        f"Requested capture duration seconds: {requested_duration_seconds}",
        f"Restart during capture: {str(restart_command is not None).lower()}",
        f"Restart command: {restart_command if restart_command is not None else 'not requested'}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
        "Pass/fail detection",
        "-------------------",
        f"Expected boot marker: {expected_boot_message}",
        f"Expected tick marker: {expected_tick_message}",
        f"Expected secure-boot marker: {expected_secure_boot_message if expected_secure_boot_message is not None else 'not configured'}",
        f"Boot marker present: {str(boot_marker_present).lower()}",
        f"Tick marker present: {str(tick_present).lower()}",
        f"Secure-boot marker present: {str(secure_boot_marker_present).lower() if secure_boot_marker_present is not None else 'not configured'}",
        f"Data captured: {str(data_captured).lower()}",
        "",
        "Boot timing evidence",
        "--------------------",
        f"verification_time_ms: {boot_timing['verification_time_ms'] if boot_timing['verification_time_ms'] is not None else 'unavailable'}",
        f"verification_cycles: {boot_timing['verification_cycles'] if boot_timing['verification_cycles'] is not None else 'unavailable'}",
        f"verification_cpu_hz: {boot_timing['verification_cpu_hz'] if boot_timing['verification_cpu_hz'] is not None else 'unavailable'}",
        f"verification_result_code: {boot_timing['verification_result_code'] if boot_timing['verification_result_code'] is not None else 'unavailable'}",
        f"verification_time_source: {boot_timing['verification_time_source']}",
        f"Measurement method: {boot_timing['measurement_method']}",
        f"Limitations: {boot_timing['limitations']}",
        "",
        "Capture command",
        "---------------",
        f"Command: {_format_command(capture_execution.command)}",
        f"Working directory: {repo_root}",
        f"Capture return code: {capture_execution.return_code}",
        f"Capture duration seconds: {capture_execution.duration_seconds:.3f}",
        "",
        "stdout:",
        capture_execution.stdout.rstrip(),
        "",
        "stderr:",
        capture_execution.stderr.rstrip(),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def _write_uart_monitor_log(
    log_path: Path,
    repo_root: Path,
    restart_execution: CommandExecution | None,
    capture_execution: CommandExecution,
    device: str,
    baud: int,
    requested_duration_seconds: int,
    restart_requested: bool,
    restart_command: str | None,
    data_captured: bool,
    return_code: int,
    duration_seconds: float,
) -> None:
    lines = [
        "Ad hoc UART monitor log",
        "=======================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"UART device: {device}",
        f"UART baud: {baud}",
        f"Requested monitor duration seconds: {requested_duration_seconds}",
        f"Restart requested: {str(restart_requested).lower()}",
        f"Restart command: {restart_command if restart_requested else 'not requested'}",
        f"Data captured: {str(data_captured).lower()}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
    ]

    if restart_execution is None:
        restart_status = (
            "Integrated into monitor command; UART capture starts before delayed reset."
            if restart_requested
            else "Skipped."
        )
        lines += [
            "Restart command",
            "---------------",
            restart_status,
            "",
        ]
    else:
        lines += [
            "Restart command",
            "---------------",
            f"Command: {_format_command(restart_execution.command)}",
            f"Working directory: {repo_root}",
            f"Restart return code: {restart_execution.return_code}",
            f"Restart duration seconds: {restart_execution.duration_seconds:.3f}",
            "",
            "stdout:",
            restart_execution.stdout.rstrip(),
            "",
            "stderr:",
            restart_execution.stderr.rstrip(),
            "",
        ]

    lines += [
        "Monitor command",
        "---------------",
        f"Command: {_format_command(capture_execution.command)}",
        f"Working directory: {repo_root}",
        f"Capture return code: {capture_execution.return_code}",
        f"Capture duration seconds: {capture_execution.duration_seconds:.3f}",
        "",
        "stdout:",
        capture_execution.stdout.rstrip(),
        "",
        "stderr:",
        capture_execution.stderr.rstrip(),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_uart_capture(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    runner: Runner = default_runner,
    duration_seconds: int = DEFAULT_CAPTURE_DURATION_SECONDS,
    restart_command: str | None = None,
    log_name: str = "uart.log",
) -> UartResult:
    """Capture post-flash UART output through the configured gateway.

    A GNU ``timeout`` return code of 124 is accepted as a completed bounded
    capture because the timeout is what stops the otherwise-continuous UART
    stream. The final framework return code is zero only when the capture step
    returned either 0 or 124 and both configured markers were observed. When a
    restart command is supplied, UART capture starts first and the restart is
    triggered from the same remote command after a short delay so one-shot boot
    output can be captured.
    """

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    log_path = result_dir_path / log_name

    gateway_alias = str(bundle["host"]["alias"])
    device = str(bundle["host"]["uart"]["device"])
    baud = int(bundle["host"]["uart"]["baud"])
    expected_boot_message = str(bundle["experiment"]["uart"]["expected_boot_message"])
    expected_tick_message = str(bundle["experiment"]["uart"]["expected_tick_message"])
    expected_secure_boot_message_value = bundle["experiment"].get("uart", {}).get(
        "expected_secure_boot_message"
    )
    expected_secure_boot_message = (
        None
        if expected_secure_boot_message_value in (None, "")
        else str(expected_secure_boot_message_value)
    )

    start = perf_counter()
    if restart_command is None:
        capture_command = construct_ssh_uart_capture_command(
            gateway_alias,
            device,
            baud,
            duration_seconds,
        )
    else:
        capture_command = construct_ssh_uart_monitor_with_restart_command(
            gateway_alias,
            device,
            baud,
            duration_seconds,
            restart_command,
        )

    capture_execution = runner(capture_command, repo_root_path)
    duration = perf_counter() - start

    data_captured = bool(capture_execution.stdout.strip())
    boot_marker_present = expected_boot_message in capture_execution.stdout
    tick_present = expected_tick_message in capture_execution.stdout
    secure_boot_marker_present = (
        None
        if expected_secure_boot_message is None
        else expected_secure_boot_message in capture_execution.stdout
    )
    secure_boot_marker_requirement_met = (
        expected_secure_boot_message is None or secure_boot_marker_present is True
    )
    capture_completed = _capture_completed(capture_execution.return_code)
    boot_timing = _boot_timing_evidence(capture_execution.stdout)

    if capture_completed and boot_marker_present and tick_present and secure_boot_marker_requirement_met:
        return_code = 0
        result_status = "pass"
    elif capture_completed:
        return_code = UART_MARKER_MISSING_RETURN_CODE
        result_status = "fail"
    else:
        return_code = capture_execution.return_code
        result_status = "fail"

    _write_uart_capture_log(
        log_path=log_path,
        repo_root=repo_root_path,
        capture_execution=capture_execution,
        device=device,
        baud=baud,
        requested_duration_seconds=duration_seconds,
        expected_boot_message=expected_boot_message,
        expected_tick_message=expected_tick_message,
        expected_secure_boot_message=expected_secure_boot_message,
        boot_marker_present=boot_marker_present,
        tick_present=tick_present,
        secure_boot_marker_present=secure_boot_marker_present,
        data_captured=data_captured,
        restart_command=restart_command,
        return_code=return_code,
        duration_seconds=duration,
        boot_timing=boot_timing,
    )

    update_manifest(
        result_dir_path / "manifest.json",
        {
            "result": result_status,
            "uart": {
                "return_code": return_code,
                "capture_return_code": capture_execution.return_code,
                "duration_seconds": round(duration, 3),
                "capture_duration_seconds": round(capture_execution.duration_seconds, 3),
                "log": log_name,
                "device": device,
                "baud": baud,
                "requested_duration_seconds": duration_seconds,
                "expected_boot_message": expected_boot_message,
                "expected_tick_message": expected_tick_message,
                "expected_secure_boot_message": expected_secure_boot_message,
                "boot_marker_present": boot_marker_present,
                "tick_present": tick_present,
                "secure_boot_marker_present": secure_boot_marker_present,
                "data_captured": data_captured,
                "restart_command": restart_command,
                "restart_during_capture": restart_command is not None,
                "skipped": False,
                "verification_time_ms": boot_timing["verification_time_ms"],
                "verification_cycles": boot_timing["verification_cycles"],
                "verification_cpu_hz": boot_timing["verification_cpu_hz"],
                "verification_result_code": boot_timing["verification_result_code"],
                "verification_time_source": boot_timing["verification_time_source"],
                "verification_time_measurement_method": boot_timing["measurement_method"],
                "verification_time_limitations": boot_timing["limitations"],
            },
            "boot_timing": boot_timing,
        },
    )

    return UartResult(
        return_code=return_code,
        duration_seconds=duration,
        log_path=log_path,
        capture=capture_execution,
        device=device,
        baud=baud,
        requested_duration_seconds=duration_seconds,
        expected_boot_message=expected_boot_message,
        expected_tick_message=expected_tick_message,
        expected_secure_boot_message=expected_secure_boot_message,
        boot_marker_present=boot_marker_present,
        tick_present=tick_present,
        secure_boot_marker_present=secure_boot_marker_present,
        data_captured=data_captured,
        verification_time_ms=boot_timing["verification_time_ms"],
        verification_cycles=boot_timing["verification_cycles"],
        verification_cpu_hz=boot_timing["verification_cpu_hz"],
        verification_result_code=boot_timing["verification_result_code"],
        verification_time_source=boot_timing["verification_time_source"],
        verification_time_measurement_method=boot_timing["measurement_method"],
        verification_time_limitations=boot_timing["limitations"],
    )


def execute_uart_monitor(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    results_root: Path | str,
    runner: Runner = default_runner,
    duration_seconds: int = DEFAULT_CAPTURE_DURATION_SECONDS,
    restart: bool = False,
    restart_command: str = DEFAULT_RESTART_COMMAND,
) -> UartMonitorResult:
    """Run ad hoc bounded UART monitoring and write a timestamped log.

    This helper does not create or update a result manifest. It is intended for
    interactive diagnostics rather than experiment pass/fail evidence.
    """

    repo_root_path = Path(repo_root)
    results_root_path = Path(results_root)
    log_path = _timestamped_monitor_log_path(results_root_path)

    gateway_alias = str(bundle["host"]["alias"])
    device = str(bundle["host"]["uart"]["device"])
    baud = int(bundle["host"]["uart"]["baud"])

    start = perf_counter()
    restart_execution: CommandExecution | None = None

    if restart:
        capture_execution = runner(
            construct_ssh_uart_monitor_with_restart_command(
                gateway_alias,
                device,
                baud,
                duration_seconds,
                restart_command,
            ),
            repo_root_path,
        )
    else:
        capture_execution = runner(
            construct_ssh_uart_capture_command(
                gateway_alias,
                device,
                baud,
                duration_seconds,
            ),
            repo_root_path,
        )
    duration = perf_counter() - start

    data_captured = bool(capture_execution.stdout.strip())

    if not _capture_completed(capture_execution.return_code):
        return_code = capture_execution.return_code
    elif not data_captured:
        return_code = UART_NO_DATA_RETURN_CODE
    else:
        return_code = 0

    _write_uart_monitor_log(
        log_path=log_path,
        repo_root=repo_root_path,
        restart_execution=restart_execution,
        capture_execution=capture_execution,
        device=device,
        baud=baud,
        requested_duration_seconds=duration_seconds,
        restart_requested=restart,
        restart_command=restart_command if restart else None,
        data_captured=data_captured,
        return_code=return_code,
        duration_seconds=duration,
    )

    return UartMonitorResult(
        return_code=return_code,
        duration_seconds=duration,
        log_path=log_path,
        restart=restart_execution,
        capture=capture_execution,
        device=device,
        baud=baud,
        requested_duration_seconds=duration_seconds,
        restart_requested=restart,
        restart_command=restart_command if restart else None,
        data_captured=data_captured,
    )
