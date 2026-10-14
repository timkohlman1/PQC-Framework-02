"""Observed regional demand estimate, excluding identified experiment storage.

This is neither a configured budget nor a simultaneous whole-device watermark.
Unmeasured application/network arrays remain at compiled size. Each run combines
its regional peaks once; the condition summary selects the largest run estimate.
"""
from pathlib import Path
import json
from statistics import median
from framework.chapter5_review import Inputs, NULL, write_csv, table
from framework.resource_analysis import elf_resources, _union
from framework.analysis_paths import result_path
from framework.run_evidence import sha256_file

PEAKS=('freertos_heap_peak_used_bytes','mldsa_workspace_peak_used_bytes','sbrk_peak_used_bytes','msp_peak_used_bytes')


def experiment_object(obj):
    owner,name=obj['owner'],obj['name']
    return (owner in ('pqc_tls_instrumentation.c','pqc_result_buffer.c','pqc_timebase.c')
        or owner=='pqc_wolfmqtt_build_only.c' and name=='s_ready_metrics_2_snapshot'
        or owner=='main.c' and (name.startswith(('app_uart_line_','smoke_line.','status_line.'))))


def components(values,objects):
    if values['freertos_heap_reserved_bytes'] is None:raise ValueError('heap backing symbol required')
    removed=[o for o in objects if experiment_object(o) and 0x20000000<=o['start']<o['end']<=0x20030000]
    overhead=_union([(o['start'],o['end']) for o in removed])
    static=(values['ram_static_base_bytes']-values['freertos_heap_reserved_bytes']-overhead+
        values['ram2_section_bytes']+values['ram3_section_bytes']-values['result_buffer_reserved_bytes']-values['workspace_reserved_bytes'])
    if static<0:raise ValueError('negative disjoint static demand')
    return dict(application_static_bytes=static,excluded_experiment_bytes=overhead+values['result_buffer_reserved_bytes']+values['mailbox_reserved_bytes'],
        primary_instrumentation_bytes=overhead,removed_objects=removed)


def run_estimate(static,peaks):
    if any(type(peaks.get(k)) is not int or peaks[k]<0 for k in PEAKS):raise ValueError('valid unsaturated regional peaks required')
    return static+sum(peaks[k] for k in PEAKS)


def analyse(inputs,report,selections):
    result=[];run_rows=[];excluded=[]
    for selection in selections:
        inv=inputs.rows(report,f'data-{selection}-inventory.csv')
        builds=inputs.rows(report,f'data-{selection}-resource_builds.csv')
        obs=inputs.rows(report,f'data-{selection}-resource_observations.csv')
        byrun={}
        for r in obs:
            if r['metric'] in PEAKS and r['scope']=='run_lifetime':
                values=byrun.setdefault(r['run_key'],{})
                if r['metric'] in values:raise ValueError('multiple lifetime observations require explicit reduction')
                values[r['metric']]=int(r['value_bytes']) if r['validity']=='valid' and r['value_bytes'] not in NULL else None
        for condition in sorted({r['condition'] for r in inv}):
            runs=[r for r in inv if r['condition']==condition and r['exclusion_reason'] in NULL and r['execution_outcome']=='completed' and r['selected_input_status']=='verified']
            keys={r['run_key'] for r in runs}
            ids={r['build_id'] for r in builds if r['validity']=='valid' and keys.intersection(json.loads(r['run_keys']))}
            if len(ids)!=1:raise ValueError('demand estimate requires one verified build per condition')
            ident=next(iter(ids));refs={x['path']:x for r in builds if r['build_id']==ident for x in json.loads(r['source_inputs']) if x['path'].endswith('/firmware.elf')}
            if not refs:raise ValueError('verified ELF missing')
            decoded=[]
            for ref in refs.values():
                path=inputs.pin(result_path(ref['path']),ident)
                if ref['sha256']!=ident:raise ValueError('ELF lineage mismatch')
                objects=[];values=elf_resources(path.read_bytes(),objects_out=objects)
                decoded.append((values,components(values,objects)))
            if any(x!=decoded[0] for x in decoded):raise ValueError('inconsistent retained ELF')
            values,comp=decoded[0];eligible=[]
            for r in runs:
                try:
                    peaks=byrun.get(r['run_key'],{});estimate=run_estimate(comp['application_static_bytes'],peaks)
                    row=dict(selection=selection,condition=condition,run_key=r['run_key'],estimate_bytes=estimate,
                        application_static_bytes=comp['application_static_bytes'],**peaks)
                    run_rows.append(row);eligible.append(row)
                except ValueError as exc:excluded.append(dict(selection=selection,condition=condition,run_key=r['run_key'],reason=str(exc)))
            if not eligible:raise ValueError('no eligible demand observations')
            maximum=max(eligible,key=lambda r:r['estimate_bytes'])
            result.append(dict(selection=selection,condition=condition,build_id=ident,runs=len(eligible),excluded_runs=len(runs)-len(eligible),
                maximum_estimate_bytes=maximum['estimate_bytes'],median_estimate_bytes=median(r['estimate_bytes'] for r in eligible),
                maximum_run_key=maximum['run_key'],application_static_bytes=comp['application_static_bytes'],
                excluded_experiment_bytes=comp['excluded_experiment_bytes'],flash_bytes=values['flash_section_bytes'],
                **{k:max(r[k] for r in eligible) for k in PEAKS}))
            excluded.extend(dict(selection=selection,condition=condition,run_key='ELF:'+ident,reason='excluded static object '+str(x)) for x in comp['removed_objects'])
    return result,run_rows,excluded


def publish(report,selections,output):
    report,out=Path(report),Path(output)
    if out.exists():raise ValueError('choose fresh observed-RAM output')
    inputs=Inputs();rows,runs,exclusions=analyse(inputs,report,selections)
    inputs.verify();out.mkdir(parents=True)
    write_csv(out/'observed-ram.csv',rows);write_csv(out/'observed-ram-runs.csv',runs)
    if exclusions:write_csv(out/'observed-ram-audit.csv',exclusions)
    table(out/'observed-ram.tex','RAM demand derived from observed regional peaks.','tab:observed-ram',
        ['Selection / condition','Peak-based estimate (KiB)'],
        [[r['selection']+' / '+r['condition'].replace('_',r'\_'),f"{r['maximum_estimate_bytes']/1024:.2f}"] for r in rows],
        r'Maximum per-run estimate; identified experiment storage excluded. See Section~\ref{subsec:memory-firmware-footprint}.',first=.78)
    meta=dict(schema='pqc-observed-regional-ram',version=1,report=str(report),inputs=inputs.hashes,
        sources={p.name:sha256_file(p) for p in (Path(__file__),Path(__file__).with_name('resource_analysis.py'))},
        formula='max_run(application_static_minus_identified_experiment_storage + heap_peak + scratch_peak + sbrk_peak + MSP_peak)',
        limits='Independent within-run region maxima; MSP starts at main; unmeasured buffers retained at compiled size; not simultaneous or validated uninstrumented minimum.',
        files={p.name:sha256_file(p) for p in out.iterdir()})
    (out/'observed-ram-provenance.json').write_text(json.dumps(meta,indent=2)+'\n');return meta
