import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UTILITY = ROOT / "experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py"


@pytest.mark.integration
def test_host_wolfmqtt_client_builds(tmp_path):
    required = (
        ROOT / "Middlewares/Third_Party/wolfMQTT/src/mqtt_client.c",
        ROOT / "tools/wolfboot/lib/wolfssl/CMakeLists.txt",
    )
    if shutil.which("cmake") is None or shutil.which("ninja") is None:
        pytest.skip("cmake and ninja are required for the host wolfMQTT build")
    if not all(path.is_file() for path in required):
        pytest.skip("wolfMQTT and wolfSSL submodules are required")

    relative_build = tmp_path.relative_to(ROOT) if tmp_path.is_relative_to(ROOT) else None
    build_dir = relative_build.as_posix() if relative_build else str(tmp_path)
    completed = subprocess.run(
        ["python", str(UTILITY), "build", "--build-dir", build_dir],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "evidence_class=host_side" in completed.stdout
    assert "claims_stm32_success=false" in completed.stdout
