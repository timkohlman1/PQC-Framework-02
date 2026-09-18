from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.hardware

MARKER_RE = re.compile(
    r"PQC_TIMEBASE_SELF_TEST delay_ms=(?P<delay>\d+) "
    r"elapsed_us=(?P<elapsed>\d+) hal_tick_delta_ms=(?P<hal_ms>\d+) "
    r"timer_input_clock_hz=(?P<input_hz>\d+) prescaler=(?P<prescaler>\d+) "
    r"counter_hz=(?P<counter_hz>\d+)"
)


def test_application_timebase_known_delay_and_hal_tick_unchanged():
    """Validate the opt-in pre-workload 10 ms hardware self-test marker.

    Set PQC_TIMEBASE_UART_LOG to a UART capture from firmware built with
    -DPQC_TIMEBASE_HARDWARE_SELF_TEST=ON. The self-test runs before network/TLS
    workload measurement and emits its marker only after UART initialisation.
    """

    raw_path = os.environ.get("PQC_TIMEBASE_UART_LOG", "").strip()
    if not raw_path:
        pytest.skip("PQC_TIMEBASE_UART_LOG is not set")
    path = Path(raw_path)
    if not path.is_file():
        pytest.fail(f"PQC_TIMEBASE_UART_LOG does not exist: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    match = MARKER_RE.search(text)
    assert match is not None, "PQC_TIMEBASE_SELF_TEST marker was not captured"

    delay_ms = int(match.group("delay"))
    elapsed_us = int(match.group("elapsed"))
    hal_ms = int(match.group("hal_ms"))
    input_hz = int(match.group("input_hz"))
    prescaler = int(match.group("prescaler"))
    counter_hz = int(match.group("counter_hz"))

    assert delay_ms == 10
    # HAL_Delay(10) is scheduler/interrupt based. A +/-20% window is deliberately
    # wider than timer quantisation and interrupt latency while still proving
    # microsecond-scale measurement rather than 1 ms HAL_GetTick granularity.
    assert 8_000 <= elapsed_us <= 12_000
    assert 9 <= hal_ms <= 12
    assert input_hz > 0
    assert input_hz % (prescaler + 1) == 0
    assert input_hz // (prescaler + 1) == 1_000_000
    assert counter_hz == 1_000_000
