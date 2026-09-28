#!/usr/bin/env python3
"""Host-side real-Docker gate for disposable certificate ownership and modes.

Generates RSA-3072 and ML-DSA-65 fixtures in an automatically removed temporary
folder. Never reads, replaces or changes the canonical secrets/certificates tree.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


def run_checks(root: Path) -> dict:
    if sys.platform != 'linux' or os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError('Run this check from your normal non-root Linux host shell')
    if shutil.which('docker') is None:
        raise RuntimeError('Docker CLI unavailable; run on the host, not inside the development image')
    with tempfile.TemporaryDirectory(prefix='pqc-certificate-ownership-') as temporary:
        output=Path(temporary)/'certificates'
        result=subprocess.run([sys.executable, str(root/'scripts/provision_certificates.py'),
            '--output', str(output), '--profile', 'rsa3072', '--profile', 'mldsa65'],
            cwd=root, text=True, capture_output=True, timeout=600)
        if result.returncode:
            raise RuntimeError(f'Provisioning check failed ({result.returncode}): {result.stderr}')
        entries=[output, *output.rglob('*')]
        for path in entries:
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RuntimeError('Unexpected symlink in disposable certificate output')
            if (info.st_uid,info.st_gid)!=(os.getuid(),os.getgid()):
                raise RuntimeError(f'Incorrect owner for {path.relative_to(output)}: {info.st_uid}:{info.st_gid}')
            if path.is_dir():
                assert stat.S_IMODE(info.st_mode) == 0o700, 'Certificate directories must be owner-only'
            else:
                assert os.access(path,os.R_OK|os.W_OK), 'Certificate output must be owner-readable/writable'
                if path.suffix == '.key' or path.name == 'private-key.pem':
                    assert stat.S_IMODE(info.st_mode) == 0o600, 'Private keys must remain 0600'
        for profile in ('rsa3072','mldsa65'):
            assert (output/profile/'manifest.json').is_file()
        return {'status':'verified','uid':os.getuid(),'gid':os.getgid(),
                'profiles':['rsa3072','mldsa65'],'entries_checked':len(entries),
                'canonical_material':'untouched','temporary_material':'removed on exit'}


def main() -> int:
    try:
        print(json.dumps(run_checks(Path(__file__).resolve().parents[1]),indent=2))
        return 0
    except (OSError,RuntimeError,AssertionError,subprocess.TimeoutExpired) as exc:
        print(f'Certificate ownership check failed: {exc}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
