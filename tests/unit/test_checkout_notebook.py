"""Run-All command selection and inline output without Docker or hardware."""
import io
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('failure', [None, 'exit', 'missing'])
def test_notebook_run_all_streams_output_and_continues(monkeypatch, capsys, failure):
    commands = []

    class Process:
        def __init__(self, args, **kwargs):
            commands.append(args)
            assert kwargs['cwd'] == ROOT
            assert kwargs['stderr'] == subprocess.STDOUT
            if failure == 'missing' and len(commands) == 1:
                raise FileNotFoundError('simulated missing Git')
            self.stdout = io.StringIO('simulated command output\n')
            self.code = 1 if failure == 'exit' and len(commands) == 1 else 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def wait(self):
            return self.code

    monkeypatch.setattr(subprocess, 'Popen', Process)
    notebook = json.loads((ROOT / 'notebooks/00_checkout.ipynb').read_text())
    namespace = {}
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            exec(compile(''.join(cell['source']), '<checkout-notebook>', 'exec'), namespace)
    output = capsys.readouterr().out
    assert 'simulated command output' in output
    assert 'Exit status:' in output
    assert commands[-1] == ('./scripts/dev.sh', 'pytest', 'tests/unit', '-ra')
    assert len(namespace['outcomes']) == len(commands)
    if failure:
        assert ('UNAVAILABLE' if failure == 'missing' else 'FAILED (1)') in output
    assert not any('gateway' in arg or 'hardware' in arg for args in commands for arg in args)
    assert 'report_dir' not in namespace
