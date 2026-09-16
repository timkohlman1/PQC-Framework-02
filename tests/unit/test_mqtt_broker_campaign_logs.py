from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_CTL = REPO_ROOT / "experiment/mqtt-broker/scripts/mqtt_broker_ctl.py"


def _load():
    spec = importlib.util.spec_from_file_location("mqtt_broker_campaign_logs", BROKER_CTL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_logs_parser_accepts_since_boundary_for_reused_broker():
    module = _load()
    args = module.build_parser().parse_args([
        "logs", "--profile", "oqs", "--tail", "100000", "--since", "2026-09-16T00:00:00+00:00"
    ])
    assert args.since == "2026-09-16T00:00:00+00:00"


def test_logs_forwards_since_before_service(monkeypatch):
    module = _load()
    captured = []
    monkeypatch.setattr(module, "compose_remote", lambda args, values: captured.append(values))
    args = module.build_parser().parse_args([
        "logs", "--profile", "reporting", "--tail", "200", "--since", "15s"
    ])
    module.logs(args)
    assert captured == [["logs", "--tail", "200", "--since", "15s", "mqtt-reporting"]]
