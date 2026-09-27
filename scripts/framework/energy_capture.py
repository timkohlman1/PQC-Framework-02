"""Framework-owned association, collection and confirmed-resume lifecycle."""
from __future__ import annotations

import json
import re
import secrets
import shlex
import subprocess
from pathlib import Path

from framework.result_collector import reporting_config
from framework.ssh_target import gateway_ssh_target


def enabled(bundle):
    return bool(bundle.get("experiment", {}).get("instruments", {}).get("energy"))


def interval_count(bundle):
    value = int(bundle["experiment"].get("workload", {}).get("iterations", {}).get("handshakes_per_run", 1))
    if not 1 <= value <= 32:
        raise ValueError("energy supports 1 to 32 intervals")
    return value


def start_gate_script(device):
    # A marker buffered before reset must not release the new boot. Require
    # another periodic announcement after the reset helper has returned.
    return (
        'gate_seen=$(grep -Fc PQC_ENERGY_WAITING "$uart_file" || true); gate_attempts=0; '
        'while [ "$reset_rc" -eq 0 ] && '
        '[ "$(grep -Fc PQC_ENERGY_WAITING "$uart_file" || true)" -le "$gate_seen" ]; do '
        'if [ "$gate_attempts" -ge 300 ]; then reset_rc=46; break; fi; '
        'gate_attempts=$((gate_attempts + 1)); sleep 0.1; done; '
        f'if [ "$reset_rc" -eq 0 ]; then printf "PQC_ENERGY_GO\\n" >{shlex.quote(device)}; fi; '
    )


class EnergyCapture:
    def __init__(self, bundle, result_dir: Path, runner=subprocess.run):
        self.bundle = bundle
        self.result_dir = result_dir
        self.run_id = result_dir.name
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,79}", self.run_id):
            raise ValueError("energy run ID must contain 1-79 safe characters")
        self.token = secrets.token_hex(16)
        self.runner = runner
        self.readiness = None
        self.resumed_status = None
        self.intervals = interval_count(bundle)
        timeout = bundle["experiment"]["instruments"]["energy"].get("result_transfer", {}).get("completion_timeout_seconds", 180)
        self.timeout = min(300, max(1, int(timeout)))
        self.result_dir.joinpath("energy-association.json").write_text(json.dumps({
            "run_id": self.run_id, "association_token": self.token, "expected_intervals": self.intervals,
        }, indent=2) + "\n")

    def _control(self, action, *, stream=None):
        host, port = reporting_config(self.bundle)
        args = {"action": action, "host": host, "port": port, "run_id": self.run_id,
                "token": secrets.token_hex(16) if action == "cleanup" else self.token,
                "intervals": self.intervals, "stream": stream,
                "timeout": self.timeout if action == "collect" else 20 if action == "cleanup" else 8}
        script = Path(__file__).with_name("energy_gateway.py").read_text()
        command = ["ssh", "-o", "ConnectTimeout=5", gateway_ssh_target(self.bundle["host"]),
                   "python3 -c " + shlex.quote(script) + " " + shlex.quote(json.dumps(args))]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=args["timeout"]+15, check=False)
            code, output = result.returncode, result.stdout + result.stderr
        except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt) as exc:
            code, output = 1, f"Gateway energy control failed: {type(exc).__name__}: {exc}\n"
        with self.result_dir.joinpath(f"energy-{action}.log").open("a", encoding="utf-8") as log:
            log.write(output)
        if code == 0 and action in {"associate", "cleanup"}:
            for line in output.splitlines():
                try:
                    status = json.loads(line)
                except ValueError:
                    continue
                if isinstance(status, dict) and status.get("type") == "status":
                    if action == "associate":
                        self.readiness = status
                    else:
                        self.resumed_status = status
        return code == 0

    def associate(self):
        # Cancel stale retained requests and prove resumed acquisition before
        # assigning this attempt's token. Never use empty-association as an ACK.
        return self._control("cleanup") and self._control("associate")

    def collect(self, stream):
        return self._control("collect", stream=stream)

    def cleanup(self):
        return self._control("cleanup")

    def sync_valid(self):
        """Reject unexpected edges/drops anywhere in the associated run."""
        if self.readiness is None or self.resumed_status is None:
            return False
        expected = {"sync_unexpected_rising": 0, "sync_orphan_falling": 0,
                    "sync_queue_drops": 0, "sync_processed_rising": self.intervals,
                    "sync_processed_falling": self.intervals}
        try:
            return all(self.resumed_status[k] - self.readiness[k] == v for k, v in expected.items())
        except (KeyError, TypeError):
            return False
