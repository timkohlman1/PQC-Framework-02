"""Firmware artifact provenance helpers.

This module contains small file-artifact helpers shared by build and flash
automation. It performs no hardware, network, UART, SSH, or toolchain actions.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


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
