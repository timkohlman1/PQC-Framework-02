"""Firmware artifact provenance helpers.

This module contains small file-artifact helpers shared by build and flash
automation. It performs no hardware, network, UART, SSH, or toolchain actions.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

CANONICAL_FIRMWARE_ARTIFACTS = {
    ".elf": "firmware.elf",
    ".hex": "firmware.hex",
    ".bin": "firmware.bin",
}


def calculate_file_sha256(path: Path | str) -> str:
    """Return the SHA-256 hex digest for a file.

    The file is streamed in chunks so the helper remains safe for larger
    firmware artifacts.
    """

    digest = hashlib.sha256()
    artifact_path = Path(path)

    with artifact_path.open("rb") as file_object:
        for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def copy_artifact_to_result(
    artifact_path: Path | str,
    result_dir: Path | str,
    destination_name: str | None = None,
) -> Path:
    """Copy one built firmware artifact into its run result directory.

    When ``destination_name`` is omitted, the original filename is preserved.
    Callers that need stable result-folder names can pass a canonical filename
    such as ``firmware.elf``.
    """

    source = Path(artifact_path)
    destination = Path(result_dir) / (destination_name if destination_name is not None else source.name)

    if not source.is_file():
        raise FileNotFoundError(f"Firmware artifact not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _artifact_manifest_entry(source: Path, destination: Path | None, copied: bool) -> dict[str, Any]:
    return {
        "source_path": str(source),
        "path": None if destination is None else destination.name,
        "artifact_path": None if destination is None else str(destination),
        "sha256": calculate_file_sha256(destination) if copied and destination is not None else None,
        "copied": copied,
        "missing_reason": None if copied else "source artifact not generated",
    }


def copy_firmware_artifacts_to_result(elf_path: Path | str, result_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Copy available firmware artifacts into a result directory.

    The ELF artifact is required and is copied as ``firmware.elf``. Optional
    sibling ``.hex`` and ``.bin`` artifacts are copied as ``firmware.hex`` and
    ``firmware.bin`` when present. Missing optional artifacts are recorded in
    the returned manifest metadata without failing the build.
    """

    elf_source = Path(elf_path)
    result_dir_path = Path(result_dir)

    if not elf_source.is_file():
        raise FileNotFoundError(f"Firmware ELF artifact not found: {elf_source}")

    copied_artifacts: dict[str, dict[str, Any]] = {}

    for suffix, destination_name in CANONICAL_FIRMWARE_ARTIFACTS.items():
        artifact_type = suffix.lstrip(".")
        source = elf_source.with_suffix(suffix)

        if source.is_file():
            destination = copy_artifact_to_result(source, result_dir_path, destination_name)
            copied_artifacts[artifact_type] = _artifact_manifest_entry(source, destination, True)
        else:
            copied_artifacts[artifact_type] = _artifact_manifest_entry(source, None, False)

    return copied_artifacts


MATERIAL_INVENTORY_NAME = "material-inventory.json"


def copy_material_to_result(
    source_path: Path | str,
    result_dir: Path | str,
    destination_relative_path: Path | str,
    *,
    role: str,
    classification: str = "disposable_experiment_material",
    private: bool = False,
    required_for: list[str] | None = None,
) -> dict[str, Any]:
    """Copy one explicitly selected build/experiment input and describe it.

    This helper intentionally accepts only an individual file selected by the
    owning workflow. It never scans credential roots or copies host access
    material implicitly.
    """

    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Result material not found: {source}")
    relative = Path(destination_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Result material destination must be result-relative: {relative}")
    destination = Path(result_dir) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "path": relative.as_posix(),
        "source_path": str(source),
        "sha256": calculate_file_sha256(destination),
        "size_bytes": destination.stat().st_size,
        "role": role,
        "classification": classification,
        "private": private,
        "required_for": list(required_for or []),
    }


def copy_material_directory_to_result(
    source_dir: Path | str,
    result_dir: Path | str,
    destination_relative_dir: Path | str,
    *,
    role_prefix: str,
    private_names: set[str] | None = None,
    required_for: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Copy all files from one explicitly selected experiment-material directory."""

    source_root = Path(source_dir)
    if not source_root.is_dir():
        raise FileNotFoundError(f"Result material directory not found: {source_root}")
    private_names = private_names or set()
    entries: list[dict[str, Any]] = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative_source = source.relative_to(source_root)
        entries.append(copy_material_to_result(
            source, result_dir, Path(destination_relative_dir) / relative_source,
            role=f"{role_prefix}:{relative_source.as_posix()}",
            private=source.name in private_names or source.suffix.lower() in {".key", ".p12", ".pfx"},
            required_for=required_for,
        ))
    return entries


def write_material_inventory(result_dir: Path | str, entries: list[dict[str, Any]]) -> Path:
    """Write a deterministic inventory for copied build and crypto material."""

    import json
    destination = Path(result_dir) / MATERIAL_INVENTORY_NAME
    destination.write_text(
        json.dumps({"schema_version": 1, "materials": sorted(entries, key=lambda item: item["path"])}, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
