"""Certificate provisioning crosses a host Docker boundary; no lab is needed."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest

pytestmark=[pytest.mark.integration,pytest.mark.docker_runtime]


def test_pinned_provisioner_creates_host_owned_private_certificates():
    if sys.platform!='linux' or os.getuid()==0 or shutil.which('docker') is None:
        pytest.skip('requires non-root Linux host with Docker; run python3 scripts/check_certificate_ownership.py')
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,str(root/'scripts/check_certificate_ownership.py')],
                          cwd=root,text=True,capture_output=True,timeout=660)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"status": "verified"' in result.stdout
