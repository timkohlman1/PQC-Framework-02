"""Real local-Docker ownership boundary; the image does not contain Docker."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.docker_runtime]


def test_real_host_container_identity_and_private_outputs():
    if sys.platform != 'linux' or os.getuid() == 0 or shutil.which('docker') is None:
        pytest.skip('requires a non-root Linux host with local Docker; run ./scripts/dev.sh check-host-user')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / 'scripts/check_container_host_user.py')],
                            cwd=root, text=True, capture_output=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "verified"' in result.stdout
