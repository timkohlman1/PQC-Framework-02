import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_direct_preflight_command_does_not_depend_on_pytest_startup_cleanup(tmp_path: Path):
    repo_root = tmp_path / "repo"
    artifact = repo_root / "build" / "Debug" / "app.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"stale")
    script = f"""
from pathlib import Path
from framework.generated_state import build_identity, preflight_generated_state
root = Path({str(repo_root)!r})
identity = build_identity(workflow='stm32_cmake', profile='Debug', input_fingerprint={{'fingerprint':'new'}}, toolchain={{'command':['cmake']}}, execution={{'host_system':'integration'}})
result = preflight_generated_state(repo_root=root, scope='cmake-Debug', expected_identity=identity, cleanup_paths=[Path('build/Debug')], final_artifact_paths=[Path('build/Debug/app.elf')])
assert not (root / 'build/Debug/app.elf').exists()
print(result.reason)
"""
    env = dict(os.environ)
    framework_parent = Path(__file__).resolve().parents[2] / "scripts"
    env["PYTHONPATH"] = str(framework_parent)
    completed = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, env=env, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "no_previous_state" in completed.stdout
