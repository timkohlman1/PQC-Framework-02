"""Wait-only lifecycle for the passive ESP32/INA228 capture appliance."""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from framework.ssh_target import gateway_ssh_target


def enabled(bundle):
    return bool(bundle.get("experiment", {}).get("instruments", {}).get("energy"))


class EnergyCapture:
    """Framework view of one passive GPIO-delimited ESP32 capture.

    The framework sends no MQTT command to the instrument. The common reporting
    subscriber is started before the STM32 run; after the workload finishes this
    helper only waits for a fixed-topic ESP32 completion already being recorded
    in that subscriber stream.
    """

    def __init__(self, bundle, result_dir: Path, runner=subprocess.run):
        self.bundle = bundle
        self.result_dir = result_dir
        self.runner = runner
        timeout = bundle["experiment"]["instruments"]["energy"].get(
            "result_transfer", {}
        ).get("completion_timeout_seconds", 180)
        self.timeout = min(300, max(1, int(timeout)))
        self.run_id = result_dir.name
        self.completion = None

    def wait(self, stream: str) -> bool:
        args = {"stream": stream, "timeout": self.timeout, "run_id": self.run_id}
        script = Path(__file__).with_name("energy_gateway.py").read_text()
        command = [
            "ssh",
            "-o",
            "ConnectTimeout=5",
            gateway_ssh_target(self.bundle["host"]),
            "python3 -c " + shlex.quote(script) + " " + shlex.quote(json.dumps(args)),
        ]
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout + 15,
                check=False,
            )
            code = result.returncode
            output = result.stdout + result.stderr
        except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt) as exc:
            code = 1
            output = f"Gateway energy wait failed: {type(exc).__name__}: {exc}\n"

        with self.result_dir.joinpath("energy-wait.log").open("a", encoding="utf-8") as log:
            log.write(output)

        if code == 0:
            for line in output.splitlines():
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(message, dict)
                    and message.get("type") == "complete"
                    and message.get("source") == "energy"
                ):
                    self.completion = message
        return code == 0 and self.completion is not None
