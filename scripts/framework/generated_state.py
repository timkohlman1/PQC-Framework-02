"""Generated build-state isolation and artifact provenance helpers.

The framework stores project-owned manifests under ``.pqc-generated-state``.
Each manifest binds generated state to a workflow scope, profile, host/runtime,
toolchain, inputs, key tuple, and successful output artifact.  Preflight removes
or quarantines only configured generated paths; canonical keys and other
secrets are never cleanup targets.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

GENERATED_STATE_DIRNAME = ".pqc-generated-state"
GENERATED_STATE_SCHEMA_VERSION = 1


class GeneratedStateError(RuntimeError):
    """Raised when generated-state provenance is malformed or incompatible."""


@dataclass(frozen=True)
class GeneratedStatePreflight:
    scope: str
    compatible: bool
    reason: str
    manifest_path: Path
    removed_paths: tuple[Path, ...]
    quarantined_paths: tuple[Path, ...]
    previous_manifest: dict[str, Any] | None
    expected_identity: dict[str, Any]


def _safe_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise GeneratedStateError("Generated-state scope must contain a safe character")
    return cleaned


def generated_state_root(repo_root: Path | str) -> Path:
    return Path(repo_root) / GENERATED_STATE_DIRNAME


def generated_state_manifest_path(repo_root: Path | str, scope: str) -> Path:
    return generated_state_root(repo_root) / "scopes" / f"{_safe_component(scope)}.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path | str) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def fingerprint_paths(paths: Iterable[Path | str], *, repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    entries: list[dict[str, Any]] = []
    for raw_path in sorted({Path(path) for path in paths}, key=lambda item: item.as_posix()):
        path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = path.resolve()
        try:
            display = resolved.relative_to(root).as_posix()
        except ValueError:
            display = str(resolved)
        if path.is_file():
            entries.append({"path": display, "kind": "file", "sha256": file_sha256(path)})
        elif path.is_dir():
            children = [child for child in path.rglob("*") if child.is_file()]
            digest = hashlib.sha256()
            for child in sorted(children):
                digest.update(child.relative_to(path).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(bytes.fromhex(file_sha256(child)))
            entries.append({"path": display, "kind": "directory", "sha256": digest.hexdigest()})
        else:
            entries.append({"path": display, "kind": "missing", "sha256": None})
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"algorithm": "sha256", "fingerprint": _sha256_bytes(encoded), "entries": entries}


def detect_execution_identity(environment: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environment is None else environment
    container_marker = str(env.get("PQC_CONTAINER", "")).strip().lower()
    return {
        "host_system": platform.system(),
        "host_machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "container": container_marker in {"1", "true", "yes", "on"},
        "workspace": str(Path.cwd().resolve()),
        "hostname": socket.gethostname(),
    }


def command_identity(command: list[str], cwd: Path | str) -> dict[str, Any]:
    if not command:
        raise GeneratedStateError("Toolchain command must not be empty")
    executable = shutil.which(command[0]) or command[0]
    version = "unavailable"
    try:
        completed = subprocess.run(
            [executable, "--version"], cwd=Path(cwd), capture_output=True, text=True,
            check=False, timeout=10,
        )
        output = (completed.stdout or completed.stderr).splitlines()
        if output:
            version = output[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"command": command, "executable": str(executable), "version": version}


def build_identity(
    *,
    workflow: str,
    profile: str,
    input_fingerprint: dict[str, Any],
    toolchain: dict[str, Any],
    execution: dict[str, Any] | None = None,
    key_tuple: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "workflow": workflow,
        "profile": profile,
        "input_fingerprint": input_fingerprint,
        "toolchain": toolchain,
        "execution": detect_execution_identity() if execution is None else execution,
        "key_tuple": key_tuple,
        "extra": extra or {},
    }


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeneratedStateError(f"Generated-state manifest is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != GENERATED_STATE_SCHEMA_VERSION:
        raise GeneratedStateError(f"Generated-state manifest has an unsupported schema: {path}")
    if not isinstance(value.get("identity"), dict):
        raise GeneratedStateError(f"Generated-state manifest is missing identity: {path}")
    return value


def _identity_digest(identity: dict[str, Any]) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _cleanup_path(path: Path, *, repo_root: Path, quarantine_root: Path | None) -> tuple[str, Path]:
    resolved = path.resolve()
    root = repo_root.resolve()
    if not _is_within(resolved, root):
        raise GeneratedStateError(f"Refusing generated-state cleanup outside repository: {path}")
    secrets_root = root / "secrets"
    if _is_within(resolved, secrets_root):
        raise GeneratedStateError(f"Refusing generated-state cleanup of canonical secret path: {path}")
    if not path.exists():
        return "absent", path
    if quarantine_root is not None:
        relative = resolved.relative_to(root)
        destination = quarantine_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(path), str(destination))
        return "quarantined", destination
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return "removed", path


def preflight_generated_state(
    *,
    repo_root: Path | str,
    scope: str,
    expected_identity: dict[str, Any],
    cleanup_paths: Iterable[Path | str],
    final_artifact_paths: Iterable[Path | str] = (),
    quarantine: bool = False,
) -> GeneratedStatePreflight:
    root = Path(repo_root)
    manifest_path = generated_state_manifest_path(root, scope)
    previous: dict[str, Any] | None
    reason = "no_previous_state"
    compatible = False
    try:
        previous = _read_manifest(manifest_path)
    except GeneratedStateError:
        previous = None
        reason = "malformed_previous_state"
    if previous is not None:
        compatible = _identity_digest(previous["identity"]) == _identity_digest(expected_identity)
        reason = "compatible" if compatible else "identity_mismatch"

    removed: list[Path] = []
    quarantined: list[Path] = []
    if not compatible:
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        quarantine_root = generated_state_root(root) / "quarantine" / _safe_component(scope) / timestamp if quarantine else None
        targets = list(cleanup_paths) + list(final_artifact_paths)
        for raw_path in dict.fromkeys(Path(item) for item in targets):
            path = raw_path if raw_path.is_absolute() else root / raw_path
            action, action_path = _cleanup_path(path, repo_root=root, quarantine_root=quarantine_root)
            if action == "removed":
                removed.append(action_path)
            elif action == "quarantined":
                quarantined.append(action_path)
        if manifest_path.exists():
            manifest_path.unlink()

    return GeneratedStatePreflight(
        scope=scope,
        compatible=compatible,
        reason=reason,
        manifest_path=manifest_path,
        removed_paths=tuple(removed),
        quarantined_paths=tuple(quarantined),
        previous_manifest=previous,
        expected_identity=expected_identity,
    )


def record_generated_state_success(
    *,
    repo_root: Path | str,
    scope: str,
    identity: dict[str, Any],
    artifacts: Iterable[Path | str],
    record_refs: dict[str, Any] | None = None,
) -> Path:
    root = Path(repo_root)
    artifact_entries: list[dict[str, Any]] = []
    for raw_path in artifacts:
        path = Path(raw_path)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise GeneratedStateError(f"Cannot record missing successful artifact: {path}")
        try:
            display = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            display = str(path.resolve())
        artifact_entries.append({"path": display, "sha256": file_sha256(path), "size_bytes": path.stat().st_size})
    manifest = {
        "schema_version": GENERATED_STATE_SCHEMA_VERSION,
        "scope": scope,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "identity": identity,
        "identity_sha256": _identity_digest(identity),
        "artifacts": artifact_entries,
        "record_refs": record_refs or {},
        "status": "success",
    }
    path = generated_state_manifest_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def require_recorded_artifact(
    *,
    repo_root: Path | str,
    scope: str,
    artifact_path: Path | str,
) -> dict[str, Any]:
    root = Path(repo_root)
    manifest_path = generated_state_manifest_path(root, scope)
    manifest = _read_manifest(manifest_path)
    if manifest is None or manifest.get("status") != "success":
        raise GeneratedStateError(f"No successful generated-state record exists for scope: {scope}")
    path = Path(artifact_path)
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise GeneratedStateError(f"Recorded artifact is missing: {path}")
    try:
        display = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    current_sha = file_sha256(path)
    for artifact in manifest.get("artifacts", []):
        if artifact.get("path") == display and artifact.get("sha256") == current_sha:
            return manifest
    raise GeneratedStateError(f"Artifact does not match successful provenance record: {path}")


def key_tuple_fingerprint(
    *,
    private_key: Path | str | None,
    public_key: Path | str | None,
    keystore: Path | str | None,
) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for name, raw_path in (("private_key", private_key), ("public_key", public_key), ("keystore", keystore)):
        if raw_path is None:
            entries[name] = {"path": None, "exists": False, "sha256": None}
            continue
        path = Path(raw_path)
        entries[name] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": file_sha256(path) if path.is_file() else None,
        }
    present = [entry["exists"] for entry in entries.values()]
    return {
        "status": "complete" if all(present) else "absent" if not any(present) else "incomplete",
        "entries": entries,
        "tuple_sha256": _sha256_bytes(json.dumps(entries, sort_keys=True).encode("utf-8")),
    }


def require_any_recorded_artifact(
    *,
    repo_root: Path | str,
    artifact_path: Path | str,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Require an artifact to match one successful project-owned scope record."""

    root = Path(repo_root)
    scopes_dir = generated_state_root(root) / "scopes"
    if not scopes_dir.is_dir():
        raise GeneratedStateError("No generated-state scope records exist")
    path = Path(artifact_path)
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise GeneratedStateError(f"Artifact is missing: {path}")
    try:
        display = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    current_sha = file_sha256(path)
    for manifest_path in sorted(scopes_dir.glob("*.json")):
        manifest = _read_manifest(manifest_path)
        if manifest is None or manifest.get("status") != "success":
            continue
        identity = manifest.get("identity", {})
        if workflow is not None and identity.get("workflow") != workflow:
            continue
        for artifact in manifest.get("artifacts", []):
            if artifact.get("path") == display and artifact.get("sha256") == current_sha:
                return manifest
    raise GeneratedStateError(f"Artifact is not backed by a successful compatible provenance record: {path}")
