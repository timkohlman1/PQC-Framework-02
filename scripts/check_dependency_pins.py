#!/usr/bin/env python3
"""Fail CI when maintained external execution dependencies are not immutable.

Policy:
- Dockerfile FROM images must use @sha256:<64 hex> (except scratch).
- Compose image: references must use @sha256:<64 hex>.
- GitHub Actions external uses: references must use a 40-character commit SHA.
- docker:// action images must use @sha256:<64 hex>.
- Literal Docker image references used by maintained orchestration/CI source must use
  @sha256:<64 hex> when they carry a tag.

This is intentionally a CI/repository policy check rather than a pytest unit test.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
ACTION_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
IMAGE_TOKEN = re.compile(
    r"(?P<image>(?:[A-Za-z0-9._-]+(?::[0-9]+)?/)?"
    r"[A-Za-z0-9._-][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+(?:@sha256:[0-9a-fA-F]{64})?)"
)

SKIP_DIRS = {
    ".git",
    ".venv",
    ".pqc-generated-state",
    "build",
    "results",
    "__pycache__",
    ".pytest_cache",
}


def _walk_files(base: Path):
    """Yield files below an explicitly maintained subtree without following symlinks.

    Callers must pass a bounded project-owned directory (for example ``scripts`` or
    ``experiment``), never the repository root. ``os.walk`` lets us prune skipped
    directories before their contents are stat'ed, avoiding expensive traversal of
    generated trees.
    """
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        current = Path(dirpath)
        for filename in filenames:
            yield current / filename


def _root_files():
    """Yield repository-root files only; never recurse from ROOT."""
    for path in ROOT.iterdir():
        if path.is_file():
            yield path


def _require_image_digest(image: str, where: str, failures: list[str]) -> None:
    if image == "scratch":
        return
    # Project-local images are built from repository Dockerfiles in the same CI run;
    # their external base dependencies are enforced at the Dockerfile FROM boundary.
    if image.startswith("pqc-framework-"):
        return
    if not SHA256.search(image):
        failures.append(f"{where}: Docker image is not pinned by sha256 digest: {image}")


def _check_dockerfiles(failures: list[str]) -> None:
    candidates = list(_root_files())
    for base in (ROOT / "docker", ROOT / "experiment"):
        candidates.extend(_walk_files(base))
    for path in candidates:
        if not path.name.startswith("Dockerfile"):
            continue
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line.upper().startswith("FROM "):
                continue
            tokens = line.split()
            idx = 1
            while idx < len(tokens) and tokens[idx].startswith("--"):
                idx += 1
            if idx >= len(tokens):
                continue
            image = tokens[idx]
            if "$" in image:
                failures.append(
                    f"{path.relative_to(ROOT)}:{lineno}: variable-based FROM cannot be verified as digest-pinned: {image}"
                )
            else:
                _require_image_digest(image, f"{path.relative_to(ROOT)}:{lineno}", failures)


def _check_compose(failures: list[str]) -> None:
    names = {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
    candidates = list(_root_files())
    for base in (ROOT / "docker", ROOT / "experiment"):
        candidates.extend(_walk_files(base))
    for path in candidates:
        if path.name not in names:
            continue
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"^\s*image:\s*['\"]?([^'\"\s#]+)", raw)
            if match:
                _require_image_digest(
                    match.group(1), f"{path.relative_to(ROOT)}:{lineno}", failures
                )


def _check_workflow_actions(failures: list[str]) -> None:
    workflows = ROOT / ".github" / "workflows"
    if not workflows.exists():
        return
    for path in workflows.glob("*.y*ml"):
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"^\s*-?\s*uses:\s*([^\s#]+)", raw)
            if not match:
                continue
            ref = match.group(1).strip("'\"")
            where = f"{path.relative_to(ROOT)}:{lineno}"
            if ref.startswith("./"):
                continue
            if ref.startswith("docker://"):
                _require_image_digest(ref[len("docker://"):], where, failures)
                continue
            if "@" not in ref:
                failures.append(f"{where}: external GitHub Action has no immutable ref: {ref}")
                continue
            _, revision = ref.rsplit("@", 1)
            if not ACTION_SHA.fullmatch(revision):
                failures.append(
                    f"{where}: external GitHub Action is not pinned to a 40-character commit SHA: {ref}"
                )


def _check_orchestration_literals(failures: list[str]) -> None:
    roots = [ROOT / "scripts", ROOT / "experiment", ROOT / ".github" / "workflows"]
    extensions = {".py", ".sh", ".ps1", ".yaml", ".yml"}
    image_assignment = re.compile(
        r"\b[A-Z0-9_]*IMAGE\s*=\s*['\"]([^'\"]+)['\"]"
    )
    docker_pull = re.compile(r"\bdocker\s+pull\s+([^\s'\"]+)")
    known_repositories: set[str] = set()

    source_files: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for path in _walk_files(base):
            if path.suffix.lower() in extensions:
                source_files.append(path)

    # First collect and validate named image dependencies. Repository constants are
    # the required form for programmatic orchestration because they make dependency
    # identity explicit and reusable.
    for path in source_files:
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in image_assignment.finditer(raw):
                image = match.group(1)
                _require_image_digest(image, f"{path.relative_to(ROOT)}:{lineno}", failures)
                known_repositories.add(image.split("@", 1)[0].rsplit(":", 1)[0])
            for match in docker_pull.finditer(raw):
                image = match.group(1)
                if "$" not in image and "${{" not in image:
                    _require_image_digest(image, f"{path.relative_to(ROOT)}:{lineno}", failures)
                    known_repositories.add(image.split("@", 1)[0].rsplit(":", 1)[0])

    # Then reject tag-only copies of any named image dependency elsewhere in
    # maintained orchestration source. This catches duplicated hard-coded literals
    # that could otherwise drift away from the canonical constant.
    if not known_repositories:
        return
    for path in source_files:
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for repository in known_repositories:
                if repository not in raw:
                    continue
                for match in IMAGE_TOKEN.finditer(raw):
                    image = match.group("image")
                    if image.split("@", 1)[0].rsplit(":", 1)[0] == repository:
                        _require_image_digest(
                            image, f"{path.relative_to(ROOT)}:{lineno}", failures
                        )


def main() -> int:
    failures: list[str] = []
    _check_dockerfiles(failures)
    _check_compose(failures)
    _check_workflow_actions(failures)
    _check_orchestration_literals(failures)
    if failures:
        print("Immutable dependency pin policy FAILED:", file=sys.stderr)
        for failure in sorted(set(failures)):
            print(f" - {failure}", file=sys.stderr)
        return 1
    print("Immutable dependency pin policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
