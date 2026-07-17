from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.uart import (
    construct_ssh_uart_monitor_with_restart_command,
)


def test_uart_is_drained_then_capture_opens_before_reset():
    command = construct_ssh_uart_monitor_with_restart_command(
        gateway_alias="gateway",
        uart_device="/dev/ttyUSB0",
        baud=115200,
        duration_seconds=10,
        restart_command="reset-board",
        restart_delay_seconds=0.2,
    )
    script = command[2]

    drain = script.index(
        "timeout 0.2s cat /dev/ttyUSB0 >/dev/null 2>&1 || true"
    )
    capture = script.index("timeout 10s cat /dev/ttyUSB0 &")
    reset = script.index("reset-board 1>&2")
    wait = script.index('wait "$capture_pid"')

    assert drain < capture < reset < wait
    assert "capture_pid=$!" in script
    assert "reset_rc=$?" in script
    assert "capture_rc=$?" in script
