#!/usr/bin/env python3
"""Hardware-free checkout provenance, shared by 00_checkout and a host CLI.

The host only orchestrates; framework Python and pytest run through dev.sh.
No firmware builds, gateway probes, broker operations or credential collection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1
INPUTS = (
    "notebooks/00_checkout.ipynb", "scripts/checkout_report.py", "scripts/dev.sh",
    "scripts/check_dependency_pins.py", "scripts/container_runtime.py", "pytest.ini", "conftest.py", "tests/conftest.py",
    "requirements-dev.txt", "docker/python/Dockerfile", ".github/workflows/ci.yml",
)
LIMITATIONS = [
    "Software checkout evidence only: no gateway, hardware, flashing, UART, broker, networking, firmware runtime, timing, memory or end-to-end validation.",
    "Host elapsed seconds measure check execution, not device performance.",
    "A dirty checkout is not reproducible from its commit alone. Status and selected source hashes are not a complete source archive.",
    "No patch contents, remotes, environment dump, ignored files or credentials are collected. Review test logs before sharing.",
    "The existing pytest startup may clean incompatible generated build state; tests also write their normal ignored automated-test evidence.",
]
CONTAINER_METADATA = """import json, platform, sys, subprocess
from importlib.metadata import version
commands = {'git': ['git','--version'], 'cmake': ['cmake','--version'],
            'ninja': ['ninja','--version'], 'arm_gcc': ['arm-none-eabi-gcc','--version']}
tools = {}
for name, command in commands.items():
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=10)
        tools[name] = {'exit_code': p.returncode, 'version': p.stdout.splitlines()[0] if p.stdout else None}
    except (OSError, subprocess.TimeoutExpired) as exc:
        tools[name] = {'unavailable': type(exc).__name__}
print(json.dumps({'python': sys.version, 'platform': platform.platform(),
                  'packages': {name: version(name) for name in ('pytest','PyYAML')}, 'tools': tools}))
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_repo(start=None):
    start = Path(start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "AI_BUILD_GUIDE.md").is_file() and (candidate / "scripts/dev.sh").is_file():
            return candidate
    raise ValueError("Start in the PQC repository or set REPO_ROOT to its absolute path.")


def redact(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    return re.sub(r"(?im)(\b(?:password|token|psk|PQC_WIFI_PSK|PQC_WIFI_SSID)\b[\"']?\s*[:=]\s*)([^\r\n]+)",
                  r"\1[REDACTED]", text)


def command(argv, root, env=None, timeout=30, sanitize=True):
    started = utc_now()
    tick = time.monotonic()
    result = {"argv": list(argv), "started_at": started, "exit_code": None}
    try:
        completed = subprocess.run(argv, cwd=root, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=timeout)
        result.update(exit_code=completed.returncode,
                      outcome="passed" if completed.returncode == 0 else "failed",
                      stdout=redact(completed.stdout) if sanitize else completed.stdout,
                      stderr=redact(completed.stderr))
    except subprocess.TimeoutExpired:
        result.update(outcome="unavailable", stdout="", stderr="Metadata probe timed out.")
    except OSError as exc:
        result.update(outcome="unavailable", stdout="", stderr=f"{type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        result.update(outcome="interrupted", stdout="", stderr="Interrupted by operator.")
    result.update(completed_at=utc_now(), host_elapsed_seconds=round(time.monotonic() - tick, 6))
    return result


def git_command(root, *args):
    # Do not inherit user-configured external diff tools, or silently hide submodule dirt.
    return command(["git", "-c", f"safe.directory={root}", *args], root, sanitize=False)


def parse_status(raw):
    entries = []
    parts = iter(raw.split("\0"))
    for item in parts:
        if not item:
            continue
        entry = {"index": item[0], "worktree": item[1], "path": item[3:]}
        if "R" in item[:2] or "C" in item[:2]:
            entry["original_path"] = next(parts)
        entries.append(entry)
    return entries


def git_snapshot(root):
    queries = {
        "commit": ("rev-parse", "--verify", "HEAD"),
        "branch": ("symbolic-ref", "--quiet", "--short", "HEAD"),
        "status": ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"),
        "submodules": ("submodule", "status", "--recursive"),
    }
    probes = {key: git_command(root, *args) for key, args in queries.items()}
    status_ok = probes["status"]["exit_code"] == 0
    entries = parse_status(probes["status"]["stdout"]) if status_ok else []
    return {
        "commit": probes["commit"]["stdout"].strip() if probes["commit"]["exit_code"] == 0 else None,
        "branch": probes["branch"]["stdout"].strip() if probes["branch"]["exit_code"] == 0 else None,
        "detached_head": probes["branch"]["exit_code"] == 1 and probes["commit"]["exit_code"] == 0,
        "dirty": bool(entries) if status_ok else None,
        "entries": entries,
        "submodules": probes["submodules"]["stdout"].splitlines() if probes["submodules"]["exit_code"] == 0 else None,
        "unavailable": {key: value["stderr"] or f"exit {value['exit_code']}"
                        for key, value in probes.items()
                        if value["exit_code"] != 0 and not (key == "branch" and value["exit_code"] == 1)},
    }


def input_hashes(root):
    return {name: sha256(root / name) if (root / name).is_file() and not (root / name).is_symlink() else None
            for name in INPUTS}


def junit_counts(path):
    tree = ET.parse(path).getroot()
    suites = [tree] if tree.tag == "testsuite" else list(tree.iter("testsuite"))
    if not suites:
        raise ValueError("JUnit contains no test suites")
    counts = {name: sum(int(suite.get(name, "0")) for suite in suites)
              for name in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return counts


def planned_checks(run_relative):
    evidence = [f"--pqc-test-results-root=/workspace/{run_relative}/automated-tests",
                "-o", f"cache_dir=/workspace/{run_relative}/pytest-cache"]
    return [
        ("wrapper_syntax", ["sh", "-n", "scripts/dev.sh"], None),
        ("unstaged_whitespace", ["git", "diff", "--no-ext-diff", "--check"], None),
        ("staged_whitespace", ["git", "diff", "--no-ext-diff", "--cached", "--check"], None),
        ("dependency_pins", ["./scripts/dev.sh", "python", "scripts/check_dependency_pins.py"], None),
        ("unit_tests", ["./scripts/dev.sh", "pytest", "tests/unit", "-ra",
                        f"--junitxml={run_relative}/unit-tests.xml", *evidence], "unit-tests.xml"),
        ("reporter_integration", ["./scripts/dev.sh", "pytest", "tests/integration/test_checkout_report_in.py",
                                  "-m", "integration", "-ra",
                                  f"--junitxml={run_relative}/reporter-integration.xml", *evidence], "reporter-integration.xml"),
    ]


def overall(checks):
    states = {check["outcome"] for check in checks}
    if "failed" in states:
        return "failed"
    if states - {"passed", "passed_with_skips"} or not states:
        return "incomplete"
    return "passed_with_skips" if "passed_with_skips" in states else "passed"


def cell(value):
    # JSON escapes control characters in filenames and branch names.
    return json.dumps(value, ensure_ascii=True).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("`", "&#96;")


def render_markdown(report):
    before = report["git_before"]
    lines = ["# PQC checkout report", "", f"Outcome: **{report['outcome']}**", "",
             f"Run: `{report['run_id']}`", f"Started (UTC): {report['started_at']}",
             f"Completed (UTC): {report.get('completed_at') or 'not completed'}", "",
             f"Commit: {cell(before['commit'])}", f"Branch: {cell(before['branch'])}",
             f"Detached HEAD: {before['detached_head']}; dirty: {before['dirty']}",
             f"Observed Git/selected-input change during checks: {report.get('checkout_changed', 'not yet compared')}", "",
             "| Check | Outcome | Exit | Host seconds | Test counts |",
             "|---|---|---|---|---|"]
    for check in report["checks"]:
        lines.append(f"| {check['name']} | {check['outcome']} | {check.get('exit_code')} | {check.get('host_elapsed_seconds', '')} | {cell(check.get('counts'))} |")
    for check in report["checks"]:
        if check.get("reason"):
            lines += ["", f"{check['name']}: {cell(check['reason'])}"]
    lines += ["", "## Worktree details before checks", "", "Index/worktree codes follow Git porcelain v1; `??` means untracked.", "",
              "| Index | Worktree | Path | Original path |", "|---|---|---|---|"]
    for entry in before["entries"]:
        lines.append("| " + " | ".join(cell(entry.get(key)) for key in ("index", "worktree", "path", "original_path")) + " |")
    lines += ["", "## Environment", "", "```json", json.dumps(report["environment"], indent=2, sort_keys=True), "```",
              "", "## Interpretation", ""] + [f"- {text}" for text in LIMITATIONS]
    lines += ["- Missing prerequisites, interrupted checks, missing JUnit or unavailable Git identity make the report incomplete.",
              "- Skips are reported separately and never count as demonstrated capability.",
              "- A passed result covers only the checks listed above, not release readiness or the entire integration suite.",
              "", "`report.json` contains commands, UTC times, before/after Git details, selected input hashes and artifact hashes.",
              "`report.sha256` identifies that JSON report for downstream thesis lineage. Retain the entire run directory."]
    return "\n".join(lines) + "\n"


def save_report(report, run_dir):
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    artifacts = list(run_dir.iterdir())
    for name in ("manifest.json", "pytest.log"):
        artifacts.extend((run_dir / "automated-tests").glob(f"*/{name}"))
    report["artifacts"] = {
        path.relative_to(run_dir).as_posix(): {"sha256": sha256(path), "size_bytes": path.stat().st_size}
        for path in sorted(artifacts)
        if path.is_file() and path.name not in {"report.json", "report.sha256"}
    }
    temporary = run_dir / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(run_dir / "report.json")
    (run_dir / "report.sha256").write_text(f"{sha256(run_dir / 'report.json')}  report.json\n", encoding="ascii")


def run_checkout(root=None, progress=print):
    root = find_repo(root)
    # Resolve before creating anything: a source directory is not enough for provenance.
    top = git_command(root, "rev-parse", "--show-toplevel")
    if top["exit_code"] != 0 or Path(top["stdout"].strip()).resolve() != root:
        raise ValueError("Checkout report requires the actual Git working-tree root.")
    before = git_snapshot(root)
    inputs_before = input_hashes(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    run_dir = root / "results" / "checkout" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    run_relative = run_dir.relative_to(root).as_posix()
    packages = {}
    for name in ("ipykernel", "IPython", "nbformat", "nbclient", "jupyterlab"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    report = {
        "schema_version": SCHEMA_VERSION, "record_type": "checkout_report", "run_id": run_id,
        "started_at": utc_now(), "completed_at": None, "outcome": "running",
        "repository_root": str(root), "git_before": before, "selected_inputs_before": inputs_before,
        "environment": {"host": {"python": sys.version, "executable": sys.executable,
                                  "platform": platform.platform(), "machine": platform.machine(),
                                  "packages": packages}},
        "checks": [], "limitations": LIMITATIONS,
    }
    save_report(report, run_dir)
    env = dict(os.environ)
    # Pin every wrapper call to the inspected local image, never pull/build implicitly.
    requested_image = os.environ.get("PQC_DOCKER_IMAGE", "pqc-framework-stm32-build")
    docker = command(["docker", "version", "--format", "{{.Client.Version}} {{.Server.Version}}"], root)
    image = command(["docker", "image", "inspect", "--format", "{{json .Id}}", requested_image], root)
    image_id = None
    if image["exit_code"] == 0:
        try:
            candidate = json.loads(image["stdout"])
            if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate):
                image_id = candidate
        except (ValueError, TypeError):
            pass
    report["environment"]["host"]["git"] = git_command(root, "--version")["stdout"].strip()
    report["environment"]["docker"] = {"requested_image": requested_image, "image_id": image_id,
                                         "versions": docker["stdout"].strip(),
                                         "unavailable_reason": None if image_id else image["stderr"] or "No valid local image ID"}
    if image_id:
        env["PQC_DOCKER_IMAGE"] = image_id
        probe = command(["./scripts/dev.sh", "python", "-c", CONTAINER_METADATA], root, env=env)
        try:
            if probe["exit_code"] != 0:
                raise ValueError(probe["stderr"])
            container = json.loads(probe["stdout"])
            if not isinstance(container, dict) or "python" not in container:
                raise ValueError("Missing container Python metadata")
            report["environment"]["container"] = container
        except ValueError:
            report["environment"]["container"] = {"unavailable": probe["stderr"] or "Invalid metadata response"}
    else:
        report["environment"]["container"] = {"unavailable": "Local Docker image/daemon unavailable"}
    interrupted = any(item["outcome"] == "interrupted" for item in (docker, image))
    if image_id:
        interrupted = interrupted or probe["outcome"] == "interrupted"
    try:
        for name, argv, junit in planned_checks(run_relative):
            progress(f"{name}: starting")
            if interrupted or (argv[0] == "./scripts/dev.sh" and not image_id):
                result = {"argv": argv, "outcome": "not_run", "exit_code": None,
                          "reason": "Earlier interruption" if interrupted else "Local Docker image/daemon unavailable"}
            else:
                result = command(argv, root, env=env, timeout=None)
                interrupted = result["outcome"] == "interrupted"
                if name.endswith("whitespace"):
                    result["stdout"] = "\n".join(line for line in result["stdout"].splitlines() if not line.startswith("+"))
                log_name = f"{name}.log"
                (run_dir / log_name).write_text("$ " + shlex.join(argv) + "\n" + result.pop("stdout") + "\n" + result.pop("stderr"), encoding="utf-8")
                result["log"] = log_name
                if junit:
                    try:
                        result["counts"] = junit_counts(run_dir / junit)
                        counts = result["counts"]
                        if result["outcome"] == "passed":
                            if counts["failures"] or counts["errors"]:
                                result["outcome"] = "failed"
                            elif counts["tests"] == 0 or counts["passed"] <= 0:
                                result.update(outcome="incomplete", reason="No passing tests were recorded")
                            elif counts["skipped"]:
                                result["outcome"] = "passed_with_skips"
                    except (OSError, ValueError, ET.ParseError) as exc:
                        result["reason"] = f"JUnit counts unavailable: {type(exc).__name__}"
                        if result["outcome"] == "passed":
                            result["outcome"] = "incomplete"
            result["name"] = name
            report["checks"].append(result)
            progress(f"{name}: {result['outcome']}")
            save_report(report, run_dir)
    finally:
        report["git_after"] = git_snapshot(root)
        report["selected_inputs_after"] = input_hashes(root)
        report["checkout_changed"] = before != report["git_after"] or inputs_before != report["selected_inputs_after"]
        report["outcome"] = overall(report["checks"])
        if report["outcome"] != "failed" and (len(report["checks"]) != len(planned_checks(run_relative))
                or before["unavailable"] or report["git_after"]["unavailable"]
                or "unavailable" in report["environment"]["container"]):
            report["outcome"] = "incomplete"
        report["completed_at"] = utc_now()
        save_report(report, run_dir)
    progress(f"Checkout {report['outcome']}: {run_dir}")
    return report, run_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()
    report, _ = run_checkout(args.repo_root)
    return 0 if report["outcome"] in {"passed", "passed_with_skips"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
