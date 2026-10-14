"""Reanalyse verified retained ELFs without rewriting a published report.

A RAM budget is configured application storage, not a simultaneous watermark or
validated minimum. The 1 KiB RAM2 handoff reservation follows the maintained L4R5
layout; boot execution and production headroom need separate qualification.
"""
import csv
import json
from pathlib import Path

from framework.analysis_paths import result_path
from framework.resource_analysis import elf_resources, VERSION
from framework.run_evidence import sha256_file
from framework.timing_dataset import _has_symlink


def publish(report, selections, output):
    report, output = Path(report), Path(output)
    checksums = json.loads((report/'checksums.json').read_text())
    inputs, outputs, all_rows = {}, {}, []
    def read(name):
        path = report/name
        digest = sha256_file(path)
        if digest != checksums.get(name):
            raise ValueError('published input checksum mismatch: ' + name)
        inputs[str(path)] = digest
        return list(csv.DictReader(path.open()))
    if output.exists():
        raise ValueError('choose a fresh RAM report directory')
    for selection in selections:
        if not selection or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in selection):
            raise ValueError('invalid selection identifier')
        distributions = read(f'data-{selection}-resource_distributions.csv')
        builds = read(f'data-{selection}-resource_builds.csv')
        for condition in sorted({r['condition'] for r in distributions}):
            references = [r for r in distributions if r['condition']==condition and r['metric']=='ram_static_base_bytes']
            if len(references)!=1:
                raise ValueError('ambiguous static condition')
            ids = json.loads(references[0]['observation_ids'])
            # Capacity selection must not take a median across distinct builds.
            if len(ids)!=1:
                raise ValueError('RAM budget needs exactly one verified build per condition')
            candidates=[r for r in builds if r['build_id']==ids[0]]
            refs={i['path']: i for r in candidates for i in json.loads(r['source_inputs']) if i['path'].endswith('/firmware.elf')}
            if not refs:
                raise ValueError('retained ELF reference unavailable')
            decoded=[]
            for ref in refs.values():
                path=result_path(ref['path'])
                if _has_symlink(path) or sha256_file(path)!=ids[0] or ref['sha256']!=ids[0]:
                    raise ValueError('retained ELF identity changed')
                inputs[str(path)]=ids[0]
                decoded.append(elf_resources(path.read_bytes()))
            if any(x!=decoded[0] for x in decoded):
                raise ValueError('conflicting retained builds')
            for metric,value in decoded[0].items():
                all_rows.append(dict(selection=selection,condition=condition,metric=metric,value_bytes=value,
                    build_id=ids[0],reason='' if value is not None else 'symbol_evidence_unavailable'))
    output.mkdir(parents=True)
    path=output/'ram-budget.csv'
    with path.open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(all_rows[0]));writer.writeheader();writer.writerows(all_rows)
    outputs[path.name]=sha256_file(path)
    def tex(text):
        return str(text).replace('_',r'\_').replace('&',r'\&').replace('%',r'\%')
    body=[]
    for r in all_rows:
        if r['metric']=='configured_application_ram_bytes':
            body.append(tex(r['selection']+' / '+r['condition'])+' & '+f"{r['value_bytes']/1024:.3f}"+r' \\')
    path=output/'ram-budget.tex'
    path.write_text(r'\begin{longtable}{p{.75\linewidth}r}'+'\n'+
        r'\toprule Condition & Configured RAM (KiB) \\ \midrule'+'\n'+ '\n'.join(body)+'\n'+
        r'\bottomrule\end{longtable}'+'\n'+
        'Configured application reservations, including the maintained 1 KiB handoff region. '+
        'Pool peaks are not added to their backing storage. Boot execution and production headroom are separate.\n')
    outputs[path.name]=sha256_file(path)
    metadata=dict(schema='pqc-ram-budget',version=1,metric_version=VERSION,source_report=str(report),inputs=inputs,
        layout_policy='STM32L4R5 maintained relocated application: RAM2 handoff reserve 1024 bytes',
        sources={p.name:sha256_file(p) for p in (Path(__file__),Path(__file__).with_name('resource_analysis.py'))},files=outputs)
    (output/'ram-budget-provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata
