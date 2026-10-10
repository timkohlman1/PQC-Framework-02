"""A8 frozen offline research reports. Raw inputs and paths stay in a private lock.

Only explicit scalar projections reach report/. No raw manifests, key logs,
notebook source output, dictionaries, traces or payloads are copied there.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from framework.analysis_paths import result_path
from framework.timing_dataset import _has_symlink, read_json
from framework.timing_dataset_loader import load_dataset
from framework.timing_summary import digest, summarise

VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parents[2]
DATASET_FILES = ('dataset.json','dataset.sha256','runs.csv','timings.csv','issues.csv')
DOMAINS = ('timing','resources','tls','network','energy','secure_boot','baremetal','ota')
SECURITY_DOMAINS = ('key_establishment','endpoint_authentication','firmware_authentication')
# Chapter labels from the supplied draft; each metric is a separately assessed requirement.
# None is deliberately unsupported, not an invitation to estimate a missing value.
SECTIONS = {
 'dataset-summary': ('5.1', 'RQ1,RQ2,RQ3,RQ4,RQ5', [('completeness','*')]),
 'classical-tls-baseline': ('5.2.1','RQ1,RQ4',[('distributions','tls_handshake'),('distributions','ttlb'),('resource_distributions','simultaneous_system_peak_bytes')]),
 'classical-secureboot-baseline': ('5.2.2','RQ5',[('secure_boot_distributions','image_verification'),('secure_boot_distributions','bootloader_flash_bytes')]),
 'baremetal-reference': ('5.2.3','RQ1,RQ2,RQ5',[('baremetal_distributions','*'),(None,'primitive_peak_ram')]),
 'kex-timing': ('5.3.1.1','RQ1,RQ2',[('tls_run_distributions','tls_handshake'),('tls_operation_distributions','*'),(None,'disjoint_total_crypto')]),
 'kex-resources': ('5.3.1.2','RQ1,RQ2',[('resource_distributions','flash_section_bytes'),('resource_distributions','simultaneous_system_peak_bytes')]),
 'kex-network-application': ('5.3.1.3','RQ1,RQ2,RQ4',[('distributions','mqtt_readiness'),('network_transport_distributions','*'),(None,'tls_handshake_only_bytes')]),
 'cert-family': ('5.3.2.1','RQ2',[('tls_run_distributions','tls_handshake'),('tls_operation_distributions','*')]),
 'auth-mode': ('5.3.2.2','RQ2',[('tls_run_distributions','tls_handshake'),('tls_operation_distributions','*'),('completeness','tls_handshake')]),
 'ready-metrics2': ('5.3.3.1','RQ4',[('distributions',m) for m in ('rtfb','rtlb','ttfb','ttlb','req_tfb','req_tlb','mqtt_readiness')]+[('application_distributions','payload_throughput')]),
 'repeated-tls': ('5.3.3.2','RQ1,RQ2',[('tls_run_distributions','tls_handshake'),('tls_operation_distributions','*')]),
 'network-impairment-summary': ('5.4','RQ3,RQ4',[('distributions','ttlb'),('network_comparisons','*')]),
 'packet-analysis': ('5.4.5','RQ3',[('network_transport_distributions','*'),(None,'cross_clock_recovery_delay')]),
 'secureboot-auth': ('5.5.1','RQ5',[('secure_boot_distributions','image_verification'),('secure_boot_distributions','boot_stack_high_water_bytes'),('secure_boot_distributions','bootloader_flash_bytes')]),
 'ota-capability': ('5.5.2','RQ5',[('resource_distributions','flash_section_bytes'),('secure_boot_distributions','bootloader_flash_bytes'),(None,'available_firmware_capacity')]),
 'application-update': ('5.5.3','RQ5',[('ota_outcomes','*'),(None,'authenticated_candidate_to_final_image'),(None,'stage_elapsed_across_resets')]),
 'bootloader-recovery': ('5.5.4','RQ5',[('ota_outcomes','*'),(None,'authenticated_trust_transition')]),
 'energy-tls-mqtt': ('5.6.1','RQ4',[('energy_distributions','*')]),
 'energy-secureboot-ota': ('5.6.2','RQ5',[(None,'boot_or_ota_energy_interval')]),
 'cross-domain-summary': ('5.7 / 6.2.5-6.2.7','RQ6',[('cross_domain','*')]),
}
SUMMARY_TABLES = {
 'distributions':('median','timing'), 'resource_distributions':('median_bytes','resources'),
 'tls_run_distributions':('median','tls'), 'tls_operation_distributions':('median','tls'),
 'network_transport_distributions':('median','network'), 'energy_distributions':('median','energy'),
 'secure_boot_distributions':('median','secure_boot'), 'baremetal_distributions':('median','baremetal'),
 'application_distributions':('median','timing'),
}
DIFFERENCE_TABLES = {name.replace('distributions','differences'):domain for name,(_,domain) in SUMMARY_TABLES.items()}
DIFFERENCE_TABLES['network_comparisons'] = 'network'
SUMMARY_COLUMNS = ['analysis','security_domain','table','condition','capture_class','evidence_class','metric','unit',
    'value','q1','q3','iqr','p95','median_ci_low','median_ci_high','median_ci_reason','n_runs','n_observations','sample_unit','region','accounting','estimand','reason']
DIFFERENCE_COLUMNS = ['analysis','security_domain','table','condition','baseline','metric','unit','delta',
    'percent_difference','baseline_runs','treatment_runs','reason','percent_reason']


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n'


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def environment():
    return {'python':platform.python_version(), **{p:importlib.metadata.version(p) for p in
        ('numpy','pandas','matplotlib','nbformat','nbclient','nbconvert')}}


def scalar(value):
    """No nested data or arbitrary raw text may become a table cell."""
    if value is None or isinstance(value,float) and math.isnan(value):
        return None
    if hasattr(value,'item'):
        value = value.item()
    if type(value) in (int,float,bool):
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError('non-finite report scalar')
        return value
    if not isinstance(value,str):
        raise ValueError('non-scalar report cell')
    if len(value)>4096 or re.search(r'PRIVATE KEY|CLIENT_RANDOM|TRAFFIC_SECRET|(?:password|token|psk)\s*[=:]',value,re.I):
        raise ValueError('unsafe report text; keep secret material outside selections')
    # Library error messages can contain a raw input path; paths belong in local/.
    return re.sub(r'(?<![A-Za-z0-9])/(?:[^\s;]+)', '[local-path]', value)


def write_csv(path, rows, columns):
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for row in rows:
            projected={}
            for key in columns:
                value=scalar(row.get(key))
                projected[key] = r'\N' if value is None else ('\\'+value if isinstance(value,str) and value.startswith('\\') else value)
            writer.writerow(projected)


def dependency(path):
    recorded=Path(path).absolute()
    path=result_path(recorded)
    if _has_symlink(path):
        raise ValueError('symlink dependency refused')
    if not path.exists():
        return {'path':str(recorded),'sha256':None,'size_bytes':None}
    if not path.is_file():
        raise ValueError('dependency must be a file')
    return {'path':str(recorded),'sha256':digest(path),'size_bytes':path.stat().st_size}


def verify_dependencies(items):
    for item in items:
        if dependency(item['path']) != item:
            raise ValueError('frozen dependency changed: '+item['path'])


def specification(path):
    path=Path(path).absolute()
    value=read_json(path.read_bytes())
    if set(value)-{'version','analyses','budgets','notebooks'} or value.get('version')!=1:
        raise ValueError('unsupported report specification')
    if not isinstance(value.get('analyses'),list) or not value['analyses']:
        raise ValueError('select at least one analysis')
    if value.get('notebooks',['research_report']) != ['research_report']:
        raise ValueError('only the scalar research_report notebook is supported')
    source_paths=[path]
    seen=set()
    for item in value['analyses']:
        if set(item)-{'id','dataset','spec','domains','security_domain','sections','network','energy'}:
            raise ValueError('unknown report analysis key')
        name=item.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name) or name in seen:
            raise ValueError('analysis IDs must be unique safe identifiers')
        seen.add(name)
        if item.get('security_domain') not in SECURITY_DOMAINS:
            raise ValueError('select a security_domain')
        if not isinstance(item.get('domains'),list) or set(item['domains'])-set(DOMAINS):
            raise ValueError('unsupported analysis domains')
        if not isinstance(item.get('sections'),list) or set(item['sections'])-set(SECTIONS):
            raise ValueError('explicit known thesis sections required')
        dataset=Path(item['dataset'])
        item['dataset']=str((path.parent/dataset).absolute() if not dataset.is_absolute() else dataset)
        for key in ('spec','network','energy'):
            if isinstance(item.get(key),str):
                ref=path.parent/item[key]
                source_paths.append(ref)
                item[key]=read_json(ref.read_bytes())
        if not isinstance(item.get('spec'),dict):
            raise ValueError('analysis spec must be an A2 object or JSON path')
        if 'network' in item['domains'] and not isinstance(item.get('network'),dict):
            raise ValueError('network analysis needs an explicit flow selection')
    for budget in value.get('budgets',[]):
        if set(budget)!={'analysis','condition','table','metric','unit','limit'} or budget['analysis'] not in seen:
            raise ValueError('budget must name one observed analysis/condition/table/metric/unit')
        if type(budget['limit']) not in (int,float) or not math.isfinite(budget['limit']) or budget['limit']<0:
            raise ValueError('budget limit must be finite and nonnegative')
    return value,source_paths


def analyse(item):
    return analyse_dataset(load_dataset(item['dataset'],verify_inputs=True), item)


def analyse_dataset(dataset, item):
    """Shared domain dispatch for frozen reports and the interactive workspace."""
    frames,spec=summarise(dataset,item['spec'])
    provenance={}
    for domain in item['domains']:
        if domain=='timing':
            continue
        if domain=='resources':
            from framework.resource_analysis import summarise_resources as func
        elif domain=='tls':
            from framework.tls_analysis import summarise_tls as func
        elif domain=='network':
            from framework.network_analysis import summarise_network as func
        elif domain=='energy':
            from framework.energy_analysis import summarise_energy as func
        elif domain=='secure_boot':
            from framework.secure_boot_analysis import summarise_secure_boot as func
        elif domain=='baremetal':
            from framework.research_extensions import summarise_baremetal as func
        elif domain=='ota':
            from framework.research_extensions import summarise_ota as func
        extra=[item.get(domain,{})] if domain in ('network','energy') else []
        derived,lineage=func(dataset,spec,*extra)
        frames.update(derived);provenance[domain]=lineage
    # Throughput uses the two validated connection-relative payload checkpoints
    # from the SAME run/epoch/iteration. No host duration or MQTT readiness proxy.
    from dataclasses import replace
    observed=[]
    for row in dataset.timing_view():
        run=next(r for r in dataset.runs if r['run_key']==row['run_key'])
        first,last=row.get('ttfb_us'),row.get('ttlb_us')
        payload=run.get('payload_bytes')
        valid=(run.get('application')=='mqtt_ready_metrics_2' and first is not None and last is not None
               and last>first and type(payload) is int and payload>0)
        observed.append(dict(run_key=row['run_key'],run_id=row['run_id'],epoch_index=row['epoch_index'],
            iteration_id=row['iteration_id'],metric='payload_throughput',value_us=payload*1e6/(last-first) if valid else None,
            validity='valid' if valid else 'unavailable',reason=None if valid else 'payload_or_transfer_interval_unavailable',
            timing_policy_exclusion=row['timing_policy_exclusion']))
    throughput,_=summarise(replace(dataset,timings=tuple(observed)),spec,metrics={'payload_throughput':{'unit':'bytes/s'}})
    for name in ('distributions','differences'):
        frames['application_'+name]=throughput[name]
    return dataset,frames,spec,provenance


def project(item,frames):
    summaries,differences,inventory,outcomes=[],[],[],[]
    common={'analysis':item['id'],'security_domain':item['security_domain']}
    for name,(value_col,domain) in SUMMARY_TABLES.items():
        if name not in frames:
            continue
        for row in frames[name].to_dict('records'):
            record={k:row.get(k) for k in SUMMARY_COLUMNS if k not in common}
            record.update(common,table=name,value=row.get(value_col))
            record['n_runs']=row.get('n_runs')
            if record['n_runs'] is None:
                if row.get('sample_unit') in ('run','run_lifetime'):
                    record['n_runs']=row.get('n_observations')
                elif name=='resource_distributions':
                    record['n_runs']=len(row.get('run_keys',[]))
            record['sample_unit']=row.get('sample_unit','run' if name.startswith(('tls_run','tls_operation','baremetal')) else 'observation')
            if record['value'] is None and not record['reason']:
                record['reason']='no_eligible_measurements'
            summaries.append(record)
    for name in DIFFERENCE_TABLES:
        if name not in frames:
            continue
        for row in frames[name].to_dict('records'):
            record={k:row.get(k) for k in DIFFERENCE_COLUMNS if k not in common}
            record.update(common,table=name,delta=row.get('delta_median',row.get('delta_median_bytes')))
            differences.append(record)
    for run in frames['inventory'].to_dict('records'):
        inventory.append({**common, **{k:run.get(k) for k in INVENTORY_COLUMNS if k not in common}})
    for row in frames['completeness'].to_dict('records'):
        outcomes.append({**common, **{k:row.get(k) for k in OUTCOME_COLUMNS if k not in common}})
    return summaries,differences,inventory,outcomes


INVENTORY_COLUMNS=['analysis','security_domain','run_key','run_id','condition','exclusion_reason',
    'case_id','repetition_index','attempt_index','retry_of_run_id','workload','application','tls_kex','tls_auth','auth_mode',
    'secure_boot','firmware_mode','payload_bytes','chunk_bytes','network_condition','source_commit','firmware_sha256',
    'configuration_identity','capture_class','evidence_class','execution_outcome','capture_acceptance','selected_input_status']
OUTCOME_COLUMNS=['analysis','security_domain','condition','capture_class','evidence_class','metric','inventory_runs','included_runs',
    'excluded_runs','completed_runs','failed_runs','unknown_runs','known_outcome_denominator','completion_fraction',
    'completion_ci_low','completion_ci_high','completion_ci_reason','capture_accepted_runs','contributing_runs','contributing_observations']


def coverage(analyses,summaries,differences,outcomes,extensions):
    rows=[]
    for section,(chapter,rqs,requirements) in SECTIONS.items():
        selected=[a['id'] for a in analyses if section in a['sections']]
        for table,metric in requirements:
            values=[r for r in summaries if r['analysis'] in selected and r['table']==table and
                    (metric=='*' or r['metric']==metric) and r['value'] is not None]
            deltas=[r for r in differences if r['analysis'] in selected and
                    r['table']==(table or '').replace('distributions','differences') and
                    (metric=='*' or r['metric']==metric) and r['delta'] is not None and not r['reason']]
            implemented=table is not None
            count=len(values)
            if table=='completeness':
                count=sum(r['included_runs']>0 for r in outcomes if r['analysis'] in selected and (metric=='*' or r['metric']==metric))
            if table=='ota_outcomes':
                count=sum(r['analysis'] in selected for r in extensions.get('ota_outcomes',[]))
            if table=='network_comparisons':
                count=sum(r['analysis'] in selected and r['table']==table and r['delta'] is not None and not r['reason'] for r in differences)
            if table=='cross_domain':
                count=len({r['security_domain'] for r in summaries if r['value'] is not None})
            rows.append(dict(section=section,chapter=chapter,rqs=rqs,metric=metric,table=table,
                implemented_analysis=implemented,selected_analyses=','.join(selected),available_summary_rows=count,
                supported_comparison_rows=len(deltas),status='available_partial' if count else 'incomplete',
                limitation='draft_column_requires_evidence_or_revised_boundary' if table is None else
                    'not_selected' if not selected and table!='cross_domain' else 'no_eligible_evidence' if not count else
                    'descriptive_evidence_is_not_RQ_completion'))
    return rows


def budget_checks(budgets,summaries):
    rows=[]
    for budget in budgets:
        matches=[r for r in summaries if all(r.get(k)==budget[k] for k in ('analysis','condition','table','metric','unit'))]
        row=dict(budget,observed_value=None,headroom=None,status='not_assessed',reason='missing_or_ambiguous_observed_configuration')
        # This is a check of the reported statistic, NOT a worst-case feasibility claim.
        if len(matches)==1 and matches[0]['value'] is not None:
            value=matches[0]['value']
            row.update(observed_value=value,headroom=budget['limit']-value,status='within_budget' if value<=budget['limit'] else 'exceeds_budget',reason='reported_statistic_only_not_worst_case_or_combined_feasibility')
        rows.append(row)
    return rows


def latex(path,rows):
    def esc(value):
        value=scalar(value)
        if value is None:return '--'
        if isinstance(value,float):return format(value,'.6g')
        mapping={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
        return ''.join(mapping.get(c,c) for c in str(value))
    lines=[r'% Generated scalar fragment. Units and sample boundaries are per row.',r'\begin{longtable}{p{.16\textwidth}p{.25\textwidth}rrrr}',r'Condition & Metric & Value & Unit & Runs & Obs. \\',r'\hline']
    lines += [' & '.join(esc(r.get(k)) for k in ('condition','metric','value','unit','n_runs','n_observations'))+r' \\' for r in rows]
    lines.append(r'\end{longtable}')
    path.write_text('\n'.join(lines)+'\n')


def figures(directory,summaries):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[r for r in summaries if r['value'] is not None]
    groups=sorted({(r['analysis'],r['table'],r['unit']) for r in selected})
    index=[]
    for number,group in enumerate(groups):
        rows=[r for r in selected if (r['analysis'],r['table'],r['unit'])==group]
        # Page long operation families so all labels remain readable.
        for offset in range(0,len(rows),24):
            page=rows[offset:offset+24]
            name=f'figure-{number:03d}-{offset//24:02d}.png'
            fig,ax=plt.subplots(figsize=(11,max(3,len(page)*.36)),layout='constrained')
            ax.barh(range(len(page)),[r['value'] for r in page])
            ax.set_yticks(range(len(page)),[r['condition']+' / '+r['metric'] for r in page],fontsize=8)
            ax.set_xlabel(group[2]);ax.set_title(group[0]+' / '+group[1])
            fig.savefig(directory/name,dpi=120);plt.close(fig)
            for r in page:index.append(dict(figure=name,**r))
    write_csv(directory/'figure-data.csv',index,['figure',*SUMMARY_COLUMNS])


def render_notebook(report,notebook_path):
    import nbformat
    from nbclient import NotebookClient
    from nbconvert import HTMLExporter
    notebook=nbformat.read(notebook_path,as_version=4)
    for cell in notebook.cells:
        if cell.cell_type=='code':cell.outputs=[];cell.execution_count=None
    NotebookClient(notebook,timeout=180,kernel_name='python3',allow_errors=False,
                   resources={'metadata':{'path':str(report)}}).execute()
    exporter=HTMLExporter()
    exporter.exclude_input=True;exporter.exclude_input_prompt=True;exporter.exclude_output_prompt=True
    body,_=exporter.from_notebook_node(notebook)
    (report/'notebook.html').write_text(body,encoding='utf-8')
    # Executed cells contain scalar projections only. Source never parses raw data.
    nbformat.write(notebook,report/'executed.ipynb')


def build(value,source_paths,output,*,expected=None):
    # The persisted lock uses canonical JSON. Use the same key order on the
    # initial build so conditions and derived table rows cannot change on replay.
    value=json.loads(canonical(value))
    output=Path(output).absolute()
    if output.exists() or _has_symlink(output):raise ValueError('choose a new non-symlink output directory')
    datasets=[];summaries=[];differences=[];inventory=[];outcomes=[];extensions={};deps={}
    def add(path):
        item=dependency(path)
        if item['path'] in deps and deps[item['path']]!=item:raise ValueError('input changed during report build')
        deps[item['path']]=item
    sources=[*sorted((ROOT/'scripts/framework').glob('*.py')),ROOT/'scripts/benchmark_summary.py',
             ROOT/'scripts/build_research_report.py',ROOT/'scripts/experiment.py',ROOT/'scripts/framework/templates/research_report.ipynb',ROOT/'requirements-dev.txt']
    for path in [*sources,*source_paths]:add(path)
    analysis_metadata=[]
    for item in value['analyses']:
        dataset_path=result_path(item['dataset'])
        if output==dataset_path or output in dataset_path.parents or dataset_path in output.parents:
            raise ValueError('report must be separate from datasets')
        for name in DATASET_FILES:add(dataset_path/name)
        dataset,frames,spec,provenance=analyse(item)
        datasets.append(dataset)
        for run in dataset.runs:
            root=result_path(run['input_path'])
            if output==root or output in root.parents or root in output.parents:
                raise ValueError('report must be separate from raw runs')
        for source in dataset.metadata['inputs']:
            for artifact in source['artifacts']:
                # Record absence too: filling in a formerly missing selected file
                # changes a frozen report dependency, not its original selection.
                if artifact.get('path'):add(artifact['path'])
        for lineage in provenance.values():
            for artifact in lineage.get('inputs',[]):
                if artifact.get('path'):add(artifact['path'])
        parts=project(item,frames)
        for destination,rows in zip((summaries,differences,inventory,outcomes),parts):destination.extend(rows)
        for table,columns in EXTENSION_COLUMNS.items():
            if table in frames:
                extensions.setdefault(table,[]).extend(dict(analysis=item['id'],**{k:r.get(k) for k in columns if k!='analysis'}) for r in frames[table].to_dict('records'))
        # Public specification contains approved scalar controls only. Full resolved
        # selectors and input paths stay in local/lock.json for exact rebuilding.
        analysis_metadata.append(dict(id=item['id'],dataset_id=dataset.metadata['dataset_id'],
            specification_sha256=identity(spec),baseline=scalar(spec['baseline']),conditions=[scalar(k) for k in spec['conditions']],
            sections=item['sections'],domains=item['domains'],security_domain=item['security_domain'],
            seed=spec['seed'],resamples=spec['resamples'],confidence=spec['confidence'],percentiles=spec['percentiles'],
            independent_runs=spec['independent_runs'],evidence_policy=spec.get('evidence_policy','exact'),
            parser_version=dataset.metadata['parser']['version'],schema=dataset.metadata['schema'],
            domain_versions={k:v.get('version') for k,v in provenance.items()}))
    verify_dependencies(list(deps.values()))
    if expected:
        if expected['environment']!=environment():raise ValueError('frozen software environment changed')
        if list(sorted(deps.values(),key=lambda x:x['path']))!=expected['dependencies']:
            raise ValueError('frozen dependency set changed')
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.research-report-',dir=output.parent))
    try:
        report=staging/'report';report.mkdir();local=staging/'local';local.mkdir(mode=0o700)
        write_csv(report/'summaries.csv',summaries,SUMMARY_COLUMNS)
        write_csv(report/'differences.csv',differences,DIFFERENCE_COLUMNS)
        write_csv(report/'run-inventory.csv',inventory,INVENTORY_COLUMNS)
        dataset_counts=[]
        for dataset_id,dataset in {d.metadata['dataset_id']:d for d in datasets}.items():
            dataset_counts.append(dict(dataset_id=dataset_id,unique_captures=len(dataset.runs),
                completed=sum(r['execution_outcome']=='completed' for r in dataset.runs),
                failed=sum(r['execution_outcome']=='failed' for r in dataset.runs),
                unknown=sum(r['execution_outcome'] not in ('completed','failed') for r in dataset.runs),
                accepted=sum(r['capture_acceptance']=='accepted' for r in dataset.runs),
                valid_timing_observations=sum(t['validity']=='valid' for t in dataset.timings)))
        write_csv(report/'dataset-counts.csv',dataset_counts,list(dataset_counts[0]))
        write_csv(report/'outcomes.csv',outcomes,OUTCOME_COLUMNS)
        cov=coverage(value['analyses'],summaries,differences,outcomes,extensions)
        write_csv(report/'coverage.csv',cov,list(cov[0]))
        for table,columns in EXTENSION_COLUMNS.items():write_csv(report/(table+'.csv'),extensions.get(table,[]),columns)
        budgets=budget_checks(value.get('budgets',[]),summaries)
        write_csv(report/'budgets.csv',budgets,['analysis','condition','table','metric','unit','limit','observed_value','headroom','status','reason'])
        # Cross-domain costs retain the observed combined configuration identity via
        # analysis+condition and run-inventory, without adding isolated resource deltas.
        write_csv(report/'cross-domain.csv',summaries,SUMMARY_COLUMNS)
        domain_status=[]
        for domain in SECURITY_DOMAINS:
            measured=[r for r in summaries if r['security_domain']==domain and r['value'] is not None]
            compared=[r for r in differences if r['security_domain']==domain and r['delta'] is not None and not r['reason']]
            domain_status.append(dict(security_domain=domain,measured_rows=len(measured),matched_rows=len(compared),
                status='partial_evidence' if measured else 'not_assessed',
                limitation='no_security_strength_migration_ranking_or_unobserved_combined_feasibility'))
        write_csv(report/'cross-domain-status.csv',domain_status,list(domain_status[0]))
        for item in value['analyses']:
            latex(report/(item['id']+'.tex'),[r for r in summaries if r['analysis']==item['id']])
        # Long-form Chapter 5 fragments preserve units/accounting instead of
        # populating unsupported draft columns with estimates.
        for section,(_,_,requirements) in SECTIONS.items():
            selected={a['id'] for a in value['analyses'] if section in a['sections']}
            rows=[r for r in summaries if r['analysis'] in selected and any(
                table==r['table'] and (metric=='*' or metric==r['metric']) for table,metric in requirements)]
            if section=='dataset-summary':
                rows=[dict(condition=d['dataset_id'][:12],metric=metric,value=d[metric],unit='runs' if metric!='valid_timing_observations' else 'observations',
                    n_runs=d['unique_captures'],n_observations=None) for d in dataset_counts
                    for metric in ('unique_captures','completed','failed','unknown','accepted','valid_timing_observations')]
            elif section=='cross-domain-summary':
                rows=list(summaries)
            elif section in ('application-update','bootloader-recovery'):
                rows=[dict(condition=r['condition'],metric='delivery_'+r['delivery_outcome'],value=1,unit='observed_run',n_runs=1,n_observations=1)
                      for r in extensions.get('ota_outcomes',[]) if r['analysis'] in selected]
            for table,metric in requirements:
                if table is None:
                    rows.append(dict(condition='unavailable',metric=metric,value=None,unit=None,n_runs=0,n_observations=0))
            if not rows:
                rows=[dict(condition='unavailable',metric='no_selected_eligible_evidence',value=None,unit=None,n_runs=0,n_observations=0)]
            latex(report/('results-'+section+'.tex'),rows)
        figures(report,summaries)
        public=dict(schema='pqc-research-report',version=VERSION,analyses=analysis_metadata,
            estimands={'timing':'success-conditional medians; repeated samples descriptive unless per-run',
                'completion':'completed/(completed+failed); unknown/excluded separate; Wilson if declared independent',
                'intervals':'run-level percentile bootstrap where supported; seed in analysis specification',
                'resources':'unique-build or scoped run observations; no sum of independently measured peaks',
                'budgets':'check of reported statistic for observed configuration; not worst-case feasibility'},
            unique_selected_captures=len({r['run_key'] for d in datasets for r in d.runs}),
            timing_metric_definitions=datasets[0].metadata['metric_definitions'],
            null_encoding=r'\N',limitations=['No security strength or migration ranking inferred from performance.',
                'Coverage is a research-gap view, not a completed-RQ verdict.',
                'Inclusive TLS timings overlap; Total Crypto is not summed.',
                'Whole TCP-flow bytes are not TLS-handshake-only bytes.',
                'No boot/OTA energy or cross-reset time inferred from application captures.'],
            input_inventory=[{'input_id':identity(d),'sha256':d['sha256'],'size_bytes':d['size_bytes']} for d in sorted(deps.values(),key=lambda x:x['path'])],
            environment=environment(),determinism='CSV selections/scientific tables must reproduce. Notebook execution IDs/timestamps, HTML rendering IDs and environment identity are not promised bit-identical.')
        (report/'report.json').write_text(canonical(public))
        render_notebook(report,ROOT/'scripts/framework/templates/research_report.ipynb')
        output_hashes={str(p.relative_to(staging)):digest(p) for p in sorted(report.iterdir())}
        if expected:
            for name,sha in output_hashes.items():
                if name.endswith(('.csv','.tex')) and expected['outputs'].get(name)!=sha:
                    raise ValueError('scientific output changed during frozen rebuild: '+name)
        verify_dependencies(list(deps.values()))
        lock=dict(schema='pqc-research-snapshot',version=VERSION,specification=value,
            specification_sources=[str(Path(p).absolute()) for p in source_paths],
            dependencies=sorted(deps.values(),key=lambda x:x['path']),environment=environment(),outputs=output_hashes)
        (local/'lock.json').write_text(canonical(lock));(local/'lock.sha256').write_text(digest(local/'lock.json')+'\n')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging);raise
    return output


EXTENSION_COLUMNS={
 'baremetal_samples':['analysis','run_key','operation','parameter','iteration_id','epoch_index','source_record','cycles','hclk_hz','validity','reason'],
 'baremetal_availability':['analysis','run_key','status','reason','iterations'],
 'ota_stages':['analysis','run_key','condition','source_line','owner','stage','active_bank','target_bank','from_bank','to_bank','duration_ms','duration_reason'],
 'ota_images':['analysis','run_key','condition','epoch_index','image_content_sha256','image_part','image_payload_bytes','handoff','reason','identity_kind'],
 'ota_outcomes':['analysis','run_key','condition','scenario','delivery_outcome','transfer_observed','activation_observed',
    'manifest_authentication_observed','application_authentication_observed','confirmation_observed','rollback_observed',
    'transition_outcome','final_identity_reason','duration_ms','duration_reason','copy_swap_reason','exclusion_reason'],
 'secure_boot_outcome_counts':['analysis','condition','observed_outcome','n_runs','n_epochs'],
 'tls_per_run':['analysis','run_key','observed_iterations','observed_handshakes','successful_iterations','failed_iterations',
    'unknown_iterations','valid_handshakes','within_run_median_us'],
}


def verify(snapshot):
    snapshot=Path(snapshot).absolute()
    if _has_symlink(snapshot):raise ValueError('symlink snapshot refused')
    path=snapshot/'local/lock.json'
    if _has_symlink(path) or (snapshot/'local/lock.sha256').is_symlink():raise ValueError('symlink lock refused')
    if (snapshot/'local/lock.sha256').read_text()!=digest(path)+'\n':raise ValueError('snapshot lock hash mismatch')
    lock=read_json(path.read_bytes())
    if lock.get('schema')!='pqc-research-snapshot' or lock.get('version')!=VERSION:raise ValueError('unsupported snapshot')
    verify_dependencies(lock['dependencies'])
    files={str(p.relative_to(snapshot)) for p in (snapshot/'report').iterdir()}
    if files!=set(lock['outputs']):raise ValueError('snapshot output inventory changed')
    for name,sha in lock['outputs'].items():
        path=snapshot/name
        if Path(name).is_absolute() or '..' in Path(name).parts or _has_symlink(path) or not path.is_file() or digest(path)!=sha:
            raise ValueError('snapshot output changed')
    return lock
