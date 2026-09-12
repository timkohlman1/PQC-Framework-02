"""Repository-wide pytest evidence capture.

This file intentionally uses only Python and pytest public hooks so collection,
setup, call, teardown, gateway, integration, and hardware failures retain
inspectable evidence under results/automated-tests/.
"""
from __future__ import annotations

import json
import os
import platform
import sys

import pytest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent
_ACTIVE_CONFIG = None
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from framework.provenance import (  # noqa: E402
    allocate_test_result_dir,
    safe_test_run_id,
    sha256_file,
    utc_now,
    write_json_atomic,
)


def _state(config) -> dict[str, Any] | None:
    return getattr(config, "_pqc_test_provenance", None)


def _save(config) -> None:
    state = _state(config)
    if state is None:
        return
    run_dir = Path(state["result_dir"])
    artifacts = {}
    for name in ("pytest.log",):
        path = run_dir / name
        if path.is_file():
            artifacts[name] = {"path": name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    state["artifacts"] = artifacts
    write_json_atomic(run_dir / "manifest.json", state)


def _log(config, event: str, **fields: Any) -> None:
    state = _state(config)
    if state is None:
        return
    record = {"timestamp": utc_now(), "event": event, **fields}
    with (Path(state["result_dir"]) / "pytest.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def pytest_addoption(parser):
    group = parser.getgroup("pqc provenance")
    group.addoption("--pqc-test-run-id", action="store", default=None, help="Override automated-test run identity.")
    group.addoption("--pqc-test-results-root", action="store", default=None, help="Override automated-test result root.")


def pytest_configure(config):
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
    requested = config.getoption("--pqc-test-run-id") or safe_test_run_id()
    override_root = config.getoption("--pqc-test-results-root")
    if override_root:
        root = Path(override_root)
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / requested
        suffix = 1
        while run_dir.exists():
            run_dir = root / f"{requested}-{suffix:02d}"
            suffix += 1
        run_dir.mkdir(parents=True)
    else:
        run_dir = allocate_test_result_dir(_REPO_ROOT, requested)

    state = {
        "schema_version": 1,
        "record_type": "automated_test_run",
        "test_run_id": run_dir.name,
        "result_dir": str(run_dir),
        "started_at": utc_now(),
        "completed_at": None,
        "outcome": "running",
        "failure_stage": None,
        "exit_code": None,
        "invocation": {"args": list(config.invocation_params.args), "cwd": str(config.invocation_params.dir)},
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "ci": bool(os.environ.get("CI")),
        },
        "counts": {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0},
        "cases": [],
        "unavailable_artifacts": [],
        "referenced_results": [],
        "builds": [],
    }
    config._pqc_test_provenance = state
    os.environ["PQC_BUILD_PURPOSE"] = "automated_test"
    os.environ["PQC_TEST_RUN_ID"] = run_dir.name
    os.environ["PQC_TEST_RESULT_DIR"] = str(run_dir)
    _log(config, "session_started", test_run_id=run_dir.name, args=state["invocation"]["args"])
    _save(config)


def pytest_collection_finish(session):
    state = _state(session.config)
    if state is not None:
        state["counts"]["collected"] = len(session.items)
        _log(session.config, "collection_finished", collected=len(session.items))
        _save(session.config)


def pytest_collectreport(report):
    if report.failed and _ACTIVE_CONFIG is not None and _state(_ACTIVE_CONFIG) is not None:
        state = _state(_ACTIVE_CONFIG)
        state["outcome"] = "failed"
        state["failure_stage"] = "collection"
        state["counts"]["error"] += 1
        _log(_ACTIVE_CONFIG, "collection_failed", nodeid=getattr(report, "nodeid", ""), longrepr=str(report.longrepr))
        _save(_ACTIVE_CONFIG)


def pytest_runtest_logreport(report):
    config = getattr(report, "_pqc_config", None)
    if config is None:
        return


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    state = _state(item.config)
    if state is None:
        return
    record = {
        "nodeid": report.nodeid,
        "stage": report.when,
        "outcome": report.outcome,
        "duration_seconds": round(report.duration, 6),
    }
    if report.failed:
        record["failure"] = str(report.longrepr)
        state["outcome"] = "failed"
        state["failure_stage"] = report.when
        state["counts"]["failed" if report.when == "call" else "error"] += 1
    elif report.when == "call":
        state["counts"]["passed" if report.passed else "skipped"] += 1
    state["cases"].append(record)
    _log(item.config, "test_stage_finished", **record)
    _save(item.config)




def pytest_sessionfinish(session, exitstatus):
    state = _state(session.config)
    if state is None:
        return
    state["completed_at"] = utc_now()
    state["exit_code"] = int(exitstatus)
    if state["outcome"] == "running":
        state["outcome"] = "passed" if int(exitstatus) == 0 else "failed"
    if int(exitstatus) != 0 and state["failure_stage"] is None:
        state["failure_stage"] = "session"
    _log(session.config, "session_finished", exit_code=int(exitstatus), outcome=state["outcome"])
    _save(session.config)


def pytest_unconfigure(config):
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = None
    for key in ("PQC_BUILD_PURPOSE", "PQC_TEST_RUN_ID", "PQC_TEST_RESULT_DIR"):
        os.environ.pop(key, None)

