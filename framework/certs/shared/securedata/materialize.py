from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import CertificateIdentity


@dataclass(frozen=True)
class MaterializedIdentity:
    directory: Path
    certificate: Path
    private_key: Path
    chain: Path | None
    root_certificate: Path | None


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def materialize_identity(
    identity: CertificateIdentity,
    *,
    runtime_root: str | Path,
    run_id: str,
    identity_name: str,
) -> Iterator[MaterializedIdentity]:
    base = Path(runtime_root).resolve()
    directory = (base / run_id / identity_name).resolve()
    if base not in directory.parents:
        raise ValueError("Materialisation path escaped runtime root")
    if directory.exists():
        raise FileExistsError(f"Runtime identity directory already exists: {directory}")
    directory.mkdir(parents=True, mode=0o700)

    certificate = directory / "certificate.crt"
    suffix = "pem" if identity.private_key_encoding.lower() == "pem" else "der"
    private_key = directory / f"private-key.{suffix}"
    chain = directory / "chain.crt" if identity.chain_pem else None
    root = directory / "ca.crt" if identity.root_certificate_pem else None

    try:
        _atomic_write(certificate, identity.certificate_pem.encode("utf-8"), 0o644)
        _atomic_write(private_key, identity.private_key, 0o600)
        if chain:
            _atomic_write(chain, identity.chain_pem.encode("utf-8"), 0o644)
        if root:
            _atomic_write(root, identity.root_certificate_pem.encode("utf-8"), 0o644)
        yield MaterializedIdentity(directory, certificate, private_key, chain, root)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        parent = directory.parent
        while parent != base:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
