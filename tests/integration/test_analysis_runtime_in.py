"""Real plotting and authenticated Jupyter runtime checks, no lab access."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration


def test_plotting_import_and_math_render_without_deprecations(tmp_path):
    # A fresh interpreter catches import-time warnings even when other tests have
    # already loaded pyplot. Exercise mathtext as well as fontconfig parsing.
    output = tmp_path / "plot.png"
    script = r"""
import sys
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties

fig, ax = plt.subplots()
ax.plot([0, 1, 2], [0, 1, 4])
ax.set_title(r"$x^2 + \frac{1}{2}$", fontproperties=FontProperties("DejaVu Sans:bold"))
fig.savefig(sys.argv[1])
plt.close(fig)
"""
    result = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", script, str(output)],
        cwd=tmp_path, text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    png = output.read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000



def test_notebook_server_requires_authentication(tmp_path):
    """Bounded loopback server with a synthetic token, no external network."""
    import socket
    import time
    import urllib.error
    import urllib.request
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    env = dict(os.environ, JUPYTER_RUNTIME_DIR=str(tmp_path / "runtime"), JUPYTER_TOKEN="synthetic-a2-test-token")
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "jupyterlab", "--ip=127.0.0.1", f"--port={port}",
            "--ServerApp.port_retries=0", "--no-browser"], cwd=tmp_path, env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions", timeout=1)
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403
                    break
                except OSError:
                    time.sleep(.1)
                else:
                    pytest.fail("unauthenticated API unexpectedly accessible")
            else:
                pytest.fail("local notebook server did not start")
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions?token=synthetic-a2-test-token", timeout=2)
            assert response.status == 200
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
