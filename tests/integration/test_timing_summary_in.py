"""Synthetic A1 -> A2 command, plotting and clean-kernel execution boundary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "scripts", ROOT / "tests"):
    sys.path.insert(0, str(directory))
from timing_dataset_support import make_run
from timing_notebook_support import isolated_notebook
from framework.timing_dataset import export_dataset

pytestmark = pytest.mark.integration


def prepare(tmp_path):
    run = make_run(tmp_path / "run")
    failed = make_run(tmp_path / "failed", failed=True, run_id="synthetic-failed")
    dataset = tmp_path / "dataset"
    export_dataset(run_dirs=[run, failed], output=dataset)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"conditions": {"baseline": {}}, "baseline": "baseline"}))
    return dataset, spec


def invoke(dataset, spec, output, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/summarise_timing_dataset.py"),
        "--dataset", str(dataset), "--spec", str(spec), "--output", str(output), *map(str,args)],
        cwd=ROOT, text=True, capture_output=True, timeout=240)


def test_batch_and_clean_kernel_agree_and_preserve_inputs(tmp_path):
    dataset, spec = prepare(tmp_path)
    source = ROOT / "notebooks/timing_comparison.ipynb"
    original = source.read_bytes()
    test_notebook = isolated_notebook(source, tmp_path / "analysis.ipynb")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    batch, notebook = tmp_path / "batch", tmp_path / "notebook"
    for output, args in ((batch, []), (notebook, ["--execute-notebook", "--notebook", test_notebook])):
        result = invoke(dataset, spec, output, *args)
        assert result.returncode == 0, result.stderr
        assert (output / "timing-distributions.png").stat().st_size > 1000
        assert (output / "matched-differences.png").stat().st_size > 1000
        assert json.loads((output / "summary.json").read_text())["inputs"]["runs.csv"]
    for name in ("completeness", "distributions", "differences", "inventory", "observations"):
        assert (batch / (name+".csv")).read_bytes() == (notebook / (name+".csv")).read_bytes()
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == v for p,v in before.items())
    assert source.read_bytes() == original
    assert invoke(dataset, spec, batch).returncode != 0


def test_failed_notebook_cell_fails_execution(tmp_path):
    import nbformat
    dataset, spec = prepare(tmp_path)
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("raise RuntimeError('deliberate A2 test failure')")])
    path = tmp_path / "bad.ipynb"; nbformat.write(nb, path)
    result = invoke(dataset, spec, tmp_path / "out", "--execute-notebook", "--notebook", path)
    assert result.returncode != 0 and "deliberate A2 test failure" in result.stderr


def test_tampering_and_raw_output_refused(tmp_path):
    dataset, spec = prepare(tmp_path)
    assert invoke(dataset, spec, tmp_path / "run" / "summary").returncode != 0
    with (dataset / "timings.csv").open("a") as handle: handle.write("tamper")
    assert invoke(dataset, spec, tmp_path / "out").returncode != 0


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
