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
    verification_cycles: int | None
    derived_verification_time_ms: float | None
    derived_time_clock_source: str | None
    bootloader_clock_hz: dict[str, int | None]
    bootloader_hclk_hz: int | None
    application_clock_hz: dict[str, int | None]
    application_memory_checkpoints: list[dict[str, Any]]
    verification_result_code: int | None
    verification_time_source: str
    verification_time_measurement_method: str
    verification_time_limitations: str
    max_stack_used_bytes: int | None
    stack_metric_source: str
    heap_used_bytes: int | None
    heap_metric_source: str
    runtime_memory_limitations: str


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




_WIFI_ASSOCIATION_RE = re.compile(r"^ST67 Wi-Fi association: result=(?P<result>\S+) ssid=(?P<ssid>\S+) state=(?P<state>\S+) security=(?P<security>\S+) channel=(?P<channel>\d+)$", re.MULTILINE)
_WIFI_DHCP_RE = re.compile(r"^ST67 DHCP: result=(?P<result>\S+) ipv4=(?P<ipv4>\d{1,3}(?:\.\d{1,3}){3}) gateway=(?P<gateway>\d{1,3}(?:\.\d{1,3}){3}) netmask=(?P<netmask>\d{1,3}(?:\.\d{1,3}){3})$", re.MULTILINE)

def parse_wifi_dhcp_evidence(output: str) -> dict[str, Any]:
    association_match = _WIFI_ASSOCIATION_RE.search(output)
    dhcp_match = _WIFI_DHCP_RE.search(output)
    association = None if association_match is None else association_match.groupdict()
    dhcp = None if dhcp_match is None else dhcp_match.groupdict()
    return {"evidence_source": "uart_explicit_st67_markers", "wifi_association": association, "dhcp": dhcp, "association_success": association is not None and association["result"] == "passed", "dhcp_success": dhcp is not None and dhcp["result"] == "passed" and dhcp["ipv4"] != "0.0.0.0"}

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
    """Construct one SSH command that captures only post-reset UART output.

    The configured UART is first drained for the short restart-delay interval
    so bytes emitted by firmware that was already running cannot satisfy marker
    checks for the next boot. A bounded UART capture is then opened before the
    reset command is issued, ensuring the earliest post-reset bytes are retained.
    Reset stdout is redirected to stderr so monitor stdout remains device UART
    data only.
    """

    device = shlex.quote(uart_device)
    restart_delay = f"{float(restart_delay_seconds):g}"
    script = (
        f"stty -F {device} {int(baud)} cs8 -cstopb -parenb raw -echo; "
        "stty_rc=$?; "
        'if [ "$stty_rc" -ne 0 ]; then exit "$stty_rc"; fi; '
        f"timeout {restart_delay}s cat {device} >/dev/null 2>&1 || true; "
        f"timeout {int(duration_seconds)}s cat {device} & "
        "capture_pid=$!; "
        f"{restart_command} 1>&2; "
        "reset_rc=$?; "
        'wait "$capture_pid"; '
        "capture_rc=$?; "
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
        encoding="utf-8",
        errors="replace",
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


DEFAULT_VERIFICATION_TIME_SOURCE = "framework_derived_from_uart_cycles_and_reported_hclk"
DEFAULT_VERIFICATION_TIME_UNAVAILABLE_SOURCE = "unavailable"
DEFAULT_VERIFICATION_TIME_METHOD = (
    "Parse explicit wolfBoot verification timing lines from captured UART output."
)
DEFAULT_VERIFICATION_TIME_UNAVAILABLE_LIMITATIONS = (
    "Raw DWT verification cycles or reported HCLK were unavailable; derived_verification_time_ms is intentionally null."
)
DEFAULT_VERIFICATION_TIME_REPORTED_LIMITATIONS = (
    "Raw DWT cycles and RCC-derived clock state are reported by firmware over UART. Milliseconds are derived by the framework from cycles and reported HCLK; no RTC, wall clock, UART duration, or reset delay is used."
)
DEFAULT_STACK_MEMORY_SOURCE = "uart_explicit_stack_high_water_marker"
DEFAULT_HEAP_MEMORY_SOURCE = "uart_explicit_application_memory_checkpoint"
DEFAULT_RUNTIME_MEMORY_UNAVAILABLE_SOURCE = "unavailable"
DEFAULT_RUNTIME_MEMORY_UNAVAILABLE_LIMITATIONS = (
    "No explicit firmware-side stack high-water mark line was present in the captured UART output; "
    "runtime stack and heap values are intentionally null rather than inferred."
)
DEFAULT_RUNTIME_MEMORY_REPORTED_LIMITATIONS = (
    "Stack high-water usage is reported by firmware over UART from wolfBoot verification instrumentation; "
    "host-side timing, UART capture duration, reset delay, linker output, and build output are not used to derive runtime memory values."
)
DEFAULT_HEAP_MEMORY_UNAVAILABLE_LIMITATIONS = (
    "Heap usage is not recorded because no explicit firmware-side heap measurement evidence was emitted."
)
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
_BOOTLOADER_CLOCK_PATTERNS = {
    "sysclk_hz": re.compile(r"\bwolfBoot clock sysclk_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "hclk_hz": re.compile(r"\bwolfBoot clock hclk_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "pclk1_hz": re.compile(r"\bwolfBoot clock pclk1_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "pclk2_hz": re.compile(r"\bwolfBoot clock pclk2_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
}
_APPLICATION_CLOCK_PATTERNS = {
    "sysclk_hz": re.compile(r"application clock sysclk_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "hclk_hz": re.compile(r"application clock hclk_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "pclk1_hz": re.compile(r"application clock pclk1_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    "pclk2_hz": re.compile(r"application clock pclk2_hz\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
}
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

_STACK_HIGH_WATER_PATTERNS = [
    re.compile(
        r"\b(?:wolfboot|secure[-_ ]?boot)?[^\r\n]*(?:max(?:imum)?\s+)?stack(?:\s+high[-_ ]?water|\s+used)?[^\r\n]*[:=]\s*(?P<value>\d+)\s*(?:bytes|B)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmax_stack_used_bytes\s*[:=]\s*(?P<value>\d+)\b",
        re.IGNORECASE,
    ),
]
_HEAP_USED_PATTERNS = [
    re.compile(
        r"\bwolfBoot verification heap used:\s*(?P<value>\d+)\s+bytes\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bheap_peak_used_bytes\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
    re.compile(r"\bheap_used_bytes\s*[:=]\s*(?P<value>\d+)\b", re.IGNORECASE),
]
_APPLICATION_MEMORY_CHECKPOINT_PATTERN = re.compile(
    r"application memory checkpoint:\s*"
    r"stage=(?P<stage>[a-z0-9_]+)\s+"
    r"heap_total_bytes=(?P<heap_total_bytes>\d+)\s+"
    r"heap_free_bytes=(?P<heap_free_bytes>\d+)\s+"
    r"heap_min_ever_free_bytes=(?P<heap_min_ever_free_bytes>\d+)\s+"
    r"heap_current_used_bytes=(?P<heap_current_used_bytes>\d+)\s+"
    r"heap_peak_used_bytes=(?P<heap_peak_used_bytes>\d+)\s+"
    r"task_stack_total_bytes=(?P<task_stack_total_bytes>\d+|unavailable)\s+"
    r"task_stack_high_water_bytes=(?P<task_stack_high_water_bytes>\d+|unavailable)\s+"
    r"task_stack_used_bytes=(?P<task_stack_used_bytes>\d+|unavailable)",
    re.IGNORECASE,
)



def _parse_first_int(patterns: list[re.Pattern[str]], uart_output: str) -> int | None:
    for pattern in patterns:
        match = pattern.search(uart_output)
        if match is not None:
            return int(match.group("value"))
    return None


def parse_verification_cycles(uart_output: str) -> int | None:
    """Parse explicit wolfBoot verification cycle count from UART output."""

    return _parse_first_int(_VERIFICATION_CYCLE_PATTERNS, uart_output)


def parse_bootloader_clock_hz(uart_output: str) -> dict[str, int | None]:
    """Parse separately reported bootloader clock values from UART output."""
    result: dict[str, int | None] = {}
    for name, pattern in _BOOTLOADER_CLOCK_PATTERNS.items():
        match = pattern.search(uart_output)
        result[name] = int(match.group("value")) if match is not None else None
    return result


def parse_application_clock_hz(uart_output: str) -> dict[str, int | None]:
    """Parse application clocks reported after SystemClock_Config and UART initialization."""

    result: dict[str, int | None] = {}
    for name, pattern in _APPLICATION_CLOCK_PATTERNS.items():
        match = pattern.search(uart_output)
        result[name] = int(match.group("value")) if match is not None else None
    return result


def parse_verification_result_code(uart_output: str) -> int | None:
    """Parse explicit wolfBoot verification return code from UART output."""

    return _parse_first_int(_VERIFICATION_RESULT_PATTERNS, uart_output)


def parse_max_stack_used_bytes(uart_output: str) -> int | None:
    """Parse explicit firmware-side maximum stack high-water mark from UART output."""

    return _parse_first_int(_STACK_HIGH_WATER_PATTERNS, uart_output)


def parse_application_memory_checkpoints(uart_output: str) -> list[dict[str, Any]]:
    """Parse bounded application heap and task-stack lifecycle checkpoints."""

    checkpoints: list[dict[str, Any]] = []
    for match in _APPLICATION_MEMORY_CHECKPOINT_PATTERN.finditer(uart_output):
        checkpoint: dict[str, Any] = {"stage": match.group("stage").lower()}
        for field in (
            "heap_total_bytes",
            "heap_free_bytes",
            "heap_min_ever_free_bytes",
            "heap_current_used_bytes",
            "heap_peak_used_bytes",
            "task_stack_total_bytes",
            "task_stack_high_water_bytes",
            "task_stack_used_bytes",
        ):
            raw = match.group(field)
            checkpoint[field] = None if raw.lower() == "unavailable" else int(raw)
        checkpoints.append(checkpoint)
    return checkpoints


def parse_heap_used_bytes(uart_output: str) -> int | None:
    """Parse explicit firmware-side heap usage evidence from UART output."""

    return _parse_first_int(_HEAP_USED_PATTERNS, uart_output)


def _runtime_memory_evidence(uart_output: str) -> dict[str, Any]:
    max_stack_used_bytes = parse_max_stack_used_bytes(uart_output)
    checkpoints = parse_application_memory_checkpoints(uart_output)
    heap_used_bytes = max(
        (checkpoint["heap_peak_used_bytes"] for checkpoint in checkpoints),
        default=None,
    )
    return {
        "max_stack_used_bytes": max_stack_used_bytes,
        "stack_metric_source": DEFAULT_STACK_MEMORY_SOURCE
        if max_stack_used_bytes is not None
        else DEFAULT_RUNTIME_MEMORY_UNAVAILABLE_SOURCE,
        "heap_used_bytes": heap_used_bytes,
        "heap_metric_source": DEFAULT_HEAP_MEMORY_SOURCE
        if heap_used_bytes is not None
        else DEFAULT_RUNTIME_MEMORY_UNAVAILABLE_SOURCE,
        "application_checkpoints": checkpoints,
        "limitations": (
            "wolfBoot maximum stack usage and application FreeRTOS memory checkpoints are separate UART evidence. "
            "Application heap values cover only the FreeRTOS heap implementation; task stack values cover only "
            "the default task at the named checkpoint. Host timing, linker output, and configured sizes alone are not runtime usage evidence."
            if checkpoints or max_stack_used_bytes is not None
            else DEFAULT_RUNTIME_MEMORY_UNAVAILABLE_LIMITATIONS
        ),
    }


def _boot_timing_evidence(uart_output: str) -> dict[str, Any]:
    verification_cycles = parse_verification_cycles(uart_output)
    clocks = parse_bootloader_clock_hz(uart_output)
    hclk_hz = clocks.get("hclk_hz")
    derived_time = None
    if verification_cycles is not None and hclk_hz not in (None, 0):
        derived_time = (verification_cycles * 1000.0) / hclk_hz
    verification_result_code = parse_verification_result_code(uart_output)
    return {
        "verification_cycles": verification_cycles,
        "verification_cycles_source": "uart_explicit_dwt_cycles_marker" if verification_cycles is not None else "unavailable",
        "bootloader_clock_hz": clocks,
        "bootloader_hclk_hz": hclk_hz,
        "bootloader_clock_source": "uart_reported_rcc_register_model" if any(v is not None for v in clocks.values()) else "unavailable",
        "derived_verification_time_ms": derived_time,
        "derived_time_clock_source": "hclk_hz" if derived_time is not None else None,
        "verification_result_code": verification_result_code,
        "verification_time_source": DEFAULT_VERIFICATION_TIME_SOURCE if derived_time is not None else DEFAULT_VERIFICATION_TIME_UNAVAILABLE_SOURCE,
        "measurement_method": DEFAULT_VERIFICATION_TIME_METHOD,
        "limitations": DEFAULT_VERIFICATION_TIME_REPORTED_LIMITATIONS if derived_time is not None else DEFAULT_VERIFICATION_TIME_UNAVAILABLE_LIMITATIONS,
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
    application_clock_hz: dict[str, int | None],
    runtime_memory: dict[str, Any],
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
        f"derived_verification_time_ms: {boot_timing['derived_verification_time_ms'] if boot_timing['derived_verification_time_ms'] is not None else 'unavailable'}",
        f"verification_cycles: {boot_timing['verification_cycles'] if boot_timing['verification_cycles'] is not None else 'unavailable'}",
        f"derived_time_clock_source: {boot_timing['derived_time_clock_source'] or 'unavailable'}",
        f"bootloader_sysclk_hz: {boot_timing['bootloader_clock_hz']['sysclk_hz'] if boot_timing['bootloader_clock_hz']['sysclk_hz'] is not None else 'unavailable'}",
        f"bootloader_hclk_hz: {boot_timing['bootloader_clock_hz']['hclk_hz'] if boot_timing['bootloader_clock_hz']['hclk_hz'] is not None else 'unavailable'}",
        f"bootloader_pclk1_hz: {boot_timing['bootloader_clock_hz']['pclk1_hz'] if boot_timing['bootloader_clock_hz']['pclk1_hz'] is not None else 'unavailable'}",
        f"bootloader_pclk2_hz: {boot_timing['bootloader_clock_hz']['pclk2_hz'] if boot_timing['bootloader_clock_hz']['pclk2_hz'] is not None else 'unavailable'}",
        f"verification_result_code: {boot_timing['verification_result_code'] if boot_timing['verification_result_code'] is not None else 'unavailable'}",
        f"verification_time_source: {boot_timing['verification_time_source']}",
        f"Measurement method: {boot_timing['measurement_method']}",
        f"Limitations: {boot_timing['limitations']}",
        "",
        "Application clock evidence",
        "--------------------------",
        f"application_sysclk_hz: {application_clock_hz['sysclk_hz'] if application_clock_hz['sysclk_hz'] is not None else 'unavailable'}",
        f"application_hclk_hz: {application_clock_hz['hclk_hz'] if application_clock_hz['hclk_hz'] is not None else 'unavailable'}",
        f"application_pclk1_hz: {application_clock_hz['pclk1_hz'] if application_clock_hz['pclk1_hz'] is not None else 'unavailable'}",
        f"application_pclk2_hz: {application_clock_hz['pclk2_hz'] if application_clock_hz['pclk2_hz'] is not None else 'unavailable'}",
        "application_clock_source: uart_reported_hal_rcc_from_running_default_task" if any(value is not None for value in application_clock_hz.values()) else "application_clock_source: unavailable",
        "",
        "Runtime memory evidence",
        "-----------------------",
        f"max_stack_used_bytes: {runtime_memory['max_stack_used_bytes'] if runtime_memory['max_stack_used_bytes'] is not None else 'unavailable'}",
        f"stack_metric_source: {runtime_memory['stack_metric_source']}",
        f"heap_used_bytes: {runtime_memory['heap_used_bytes'] if runtime_memory['heap_used_bytes'] is not None else 'unavailable'}",
        f"heap_metric_source: {runtime_memory['heap_metric_source']}",
        f"runtime_memory_limitations: {runtime_memory['limitations']}",
        "application_memory_checkpoints:",
        *[
            "  " + " ".join(
                f"{key}={value if value is not None else 'unavailable'}"
                for key, value in checkpoint.items()
            )
            for checkpoint in runtime_memory["application_checkpoints"]
        ],
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
    output_lines = {line.strip() for line in capture_execution.stdout.splitlines()}
    boot_marker_present = expected_boot_message in capture_execution.stdout
    tick_present = expected_tick_message.strip() in output_lines
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
    application_clock_hz = parse_application_clock_hz(capture_execution.stdout)
    runtime_memory = _runtime_memory_evidence(capture_execution.stdout)
    network_evidence = parse_wifi_dhcp_evidence(capture_execution.stdout)

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
        application_clock_hz=application_clock_hz,
        runtime_memory=runtime_memory,
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
                "derived_verification_time_ms": boot_timing["derived_verification_time_ms"],
                "derived_time_clock_source": boot_timing["derived_time_clock_source"],
                "bootloader_clock_hz": boot_timing["bootloader_clock_hz"],
                "bootloader_hclk_hz": boot_timing["bootloader_hclk_hz"],
                "bootloader_clock_source": boot_timing["bootloader_clock_source"],
                "application_clock_hz": application_clock_hz,
                "application_clock_source": "uart_reported_hal_rcc_from_running_default_task" if any(value is not None for value in application_clock_hz.values()) else "unavailable",
                "verification_cycles": boot_timing["verification_cycles"],
                
                "verification_result_code": boot_timing["verification_result_code"],
                "verification_time_source": boot_timing["verification_time_source"],
                "verification_time_measurement_method": boot_timing["measurement_method"],
                "verification_time_limitations": boot_timing["limitations"],
                "max_stack_used_bytes": runtime_memory["max_stack_used_bytes"],
                "stack_metric_source": runtime_memory["stack_metric_source"],
                "heap_used_bytes": runtime_memory["heap_used_bytes"],
                "heap_metric_source": runtime_memory["heap_metric_source"],
                "runtime_memory_limitations": runtime_memory["limitations"],
                "application_memory_checkpoints": runtime_memory["application_checkpoints"],
            },
            "boot_timing": boot_timing,
            "application_clock": {
                "clock_hz": application_clock_hz,
                "source": "uart_reported_hal_rcc_from_running_default_task" if any(value is not None for value in application_clock_hz.values()) else "unavailable",
                "measurement_point": "after FreeRTOS scheduler start in defaultTask",
            },
            "runtime_memory": runtime_memory,
            "network": network_evidence,
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
        derived_verification_time_ms=boot_timing["derived_verification_time_ms"],
        derived_time_clock_source=boot_timing["derived_time_clock_source"],
        bootloader_clock_hz=boot_timing["bootloader_clock_hz"],
        bootloader_hclk_hz=boot_timing["bootloader_hclk_hz"],
        application_clock_hz=application_clock_hz,
        application_memory_checkpoints=runtime_memory["application_checkpoints"],
        verification_cycles=boot_timing["verification_cycles"],
        verification_result_code=boot_timing["verification_result_code"],
        verification_time_source=boot_timing["verification_time_source"],
        verification_time_measurement_method=boot_timing["measurement_method"],
        verification_time_limitations=boot_timing["limitations"],
        max_stack_used_bytes=runtime_memory["max_stack_used_bytes"],
        stack_metric_source=runtime_memory["stack_metric_source"],
        heap_used_bytes=runtime_memory["heap_used_bytes"],
        heap_metric_source=runtime_memory["heap_metric_source"],
        runtime_memory_limitations=runtime_memory["limitations"],
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
