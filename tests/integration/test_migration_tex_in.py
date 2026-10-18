"""Compile representative generated table inputs when a TeX engine is available."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework import migration, migration_report as report
pytestmark=pytest.mark.integration


def test_generated_inputs_compile_without_overfull_boxes(tmp_path):
    engine=shutil.which('pdflatex')
    if not engine:pytest.skip('pdflatex unavailable; source projection covered by unit tests')
    state=dict(choices={'from':dict(migration.DEFAULTS),'to':{**migration.DEFAULTS,
               'tls_auth':'mldsa65','auth_mode':'mutual','mldsa_memory_mode':'both_small',
               'network_condition':'research_combined_loss_delay_rate'},'repetitions':10})
    rows=[]
    for label,domain,metric,scale,unit in report.METRICS:
        rows.append(dict(label=label,metric=metric,unit=unit,divisor=scale,
            values={'from':12345*scale,'to':16789*scale},delta=4444*scale,percent=36.0,
            samples={'from':10,'to':10},reason=None,percent_reason=None))
    counts={s:dict(completed=10,failed=0,blocked=0,without_capture=0,planned=10) for s in migration.SIDES}
    for name,text in report.render(rows,state,counts).items():(tmp_path/name).write_text(text)
    (tmp_path/'check.tex').write_text(r'''\documentclass{article}
\usepackage[a4paper,margin=25mm]{geometry}
\usepackage{booktabs,tabularx}
\begin{document}
\input{comparison.tex}
\newpage\input{selections.tex}
\end{document}
''')
    result=subprocess.run([engine,'-halt-on-error','-interaction=nonstopmode','check.tex'],cwd=tmp_path,
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout[-5000:]
    assert 'Overfull' not in (tmp_path/'check.log').read_text()
