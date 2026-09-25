"""Small source-only helpers for self-owned, sequential hardware test files.

This module does not invoke Docker or access hardware. The existing framework
runner remains responsible for build, provisioning, flash, capture and manifests.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from framework.config_resolver import ConfigResolver


@dataclass(frozen=True)
class HardwareFileRun:
    repo_root: Path
    generated_root: Path
    evidence_root: Path

    @classmethod
    def create(cls, *, repo_root: Path, session_result_dir: Path, module_name: str) -> "HardwareFileRun":
        # Fresh identity for every execution of a module, including reruns inside
        # the same pytest session. Canonical build and generated-state paths stay
        # unchanged for the underlying framework.
        identity = uuid.uuid4().hex
        generated = repo_root / ".pqc-generated-state" / "hardware-tests" / module_name / identity
        evidence = session_result_dir / "hardware" / module_name / identity
        generated.mkdir(parents=True, exist_ok=False)
        evidence.mkdir(parents=True, exist_ok=False)
        return cls(repo_root, generated, evidence)

    def case(self, *, template: str, workload: str | None = None,
             network_condition: str | None = None,
             repetitions: int | None = None, case_name: str = "default",
             instruments: dict[str, str] | None = None) -> Path:
        if not case_name or not all(character.isalnum() or character in "_-" for character in case_name):
            raise ValueError("case_name must be a nonempty simple path component")
        case_root = self.generated_root / case_name
        case_root.mkdir(parents=True, exist_ok=False)
        case_evidence = self.evidence_root / "configuration" / case_name
        case_evidence.mkdir(parents=True, exist_ok=False)
        template_path = self.repo_root / "configs" / "campaigns" / f"{template}.yaml"
        campaign: dict[str, Any] = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        campaign["id"] = f"hw_{self.generated_root.parent.name}_{self.generated_root.name[:12]}_{case_name}"
        campaign["matrix"] = {}
        if template == "secure_boot":
            # The canonical secure-boot campaign is a full algorithm matrix.
            # These specific MQTT tests require its integrity baseline only.
            campaign["fixed"]["secure_boot"] = "integrity_sha256"
        if instruments is not None:
            campaign["instruments"] = dict(instruments)
        if workload is not None:
            campaign["workload"] = workload
        if network_condition is not None:
            campaign["fixed"]["network_condition"] = network_condition
        if repetitions is not None:
            campaign["execution"]["repetitions"] = repetitions
        source = case_root / "campaign.yaml"
        source.write_text(yaml.safe_dump(campaign, sort_keys=False), encoding="utf-8")
        # Keep the non-secret source and resolved case in persistent evidence,
        # because Docker's generated-state overlay disappears after the session.
        (case_evidence / "campaign.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        generated = ConfigResolver(self.repo_root).materialize_campaign(
            source, case_root / "resolved"
        )
        cases = sorted((generated / "cases").glob("*.yaml"))
        if len(cases) != 1:
            raise AssertionError(f"expected one resolved case, found {len(cases)}")
        (case_evidence / "resolved-case.yaml").write_bytes(cases[0].read_bytes())
        (case_evidence / "campaign-resolved.yaml").write_bytes(
            (generated / "campaign-resolved.yaml").read_bytes()
        )
        return cases[0]

    def run_experiment(self, *, case: Path, name: str) -> tuple[Path, subprocess.CompletedProcess[str]]:
        results = self.evidence_root / name
        results.mkdir(parents=True, exist_ok=False)
        completed = subprocess.run(
            [sys.executable, "scripts/experiment.py", "run", "--experiment", str(case),
             "--results-dir", str(results)],
            cwd=self.repo_root, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False,
        )
        (results / "experiment.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (results / "experiment.stderr.log").write_text(completed.stderr, encoding="utf-8")
        (results / "experiment.returncode.json").write_text(
            json.dumps({"return_code": completed.returncode}, indent=2) + "\n", encoding="utf-8"
        )
        manifests = sorted(results.glob("*/manifest.json"))
        if completed.returncode != 0:
            raise AssertionError(
                f"experiment failed (rc={completed.returncode}); retained logs/results: {results}"
            )
        if len(manifests) != 1:
            raise AssertionError(f"expected one experiment manifest, found {len(manifests)}: {results}")
        return manifests[0].parent, completed


def session_result_dir(pytestconfig: Any) -> Path:
    state = getattr(pytestconfig, "_pqc_test_provenance", None)
    if not isinstance(state, dict) or not state.get("result_dir"):
        raise RuntimeError("pytest session evidence directory was not initialised")
    return Path(state["result_dir"])
