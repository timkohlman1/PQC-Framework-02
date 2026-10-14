"""Pinned, read-only Chapter 5 diagnostics: stages, outcomes and sampled power.

Scientific reductions live here; the thesis only selects these published rows.
Outputs are immutable and every consumed published/raw input is hashed again.
"""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
from statistics import mean, median
import numpy as np
from framework.analysis_paths import result_path
from framework.run_evidence import sha256_file
from framework.energy_analysis import acquisitions

NULL = ('', r'\N', None)
KEX = [('secp256r1','P-256'),('SecP256r1MLKEM768','P-256 + ML-KEM-768')]
STAGES = ['TCP/TLS setup','TLS handshake','TLS end to MQTT ready',
          'MQTT ready to request','Request to first payload','First to last payload']


def tex(value):
    return ''.join({'_':r'\_', '%':r'\%', '&':r'\&', '#':r'\#'}.get(c,c) for c in str(value))


def write_csv(path, rows):
    if not rows:
        raise ValueError('empty report: '+str(path))
    with path.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def table(path, caption, label, headings, rows, note, first=.36):
    n=len(headings);widths=[first]+[(1-first)/(n-1)]*(n-1)
    columns=''.join((r'>{\raggedright\arraybackslash}' if i==0 else r'>{\raggedleft\arraybackslash}')+
        r'p{\dimexpr'+f'{width:.5f}'+r'\linewidth-2\tabcolsep\relax}' for i,width in enumerate(widths))
    path.write_text(r'\begin{table}[!htbp]\centering\begingroup\renewcommand{\baselinestretch}{1}\footnotesize'+'\n'+
        r'\setlength{\tabcolsep}{4pt}\renewcommand{\arraystretch}{1.12}'+'\n'+
        r'\caption{'+caption+r'}\label{'+label+'}\n'+r'\begin{tabular}{'+columns+'}\n'+r'\toprule'+'\n'+
        ' & '.join(headings)+r' \\ \midrule'+'\n'+'\n'.join(' & '.join(map(str,r))+r' \\' for r in rows)+'\n'+
        r'\bottomrule\end{tabular}\par\smallskip\parbox{\linewidth}{\raggedright '+note+r'}\endgroup\end{table}'+'\n')


class Inputs:
    def __init__(self): self.hashes={}
    def pin(self,path,expected=None):
        path=Path(path)
        if path.is_symlink(): raise ValueError('symlink input')
        digest=sha256_file(path)
        if expected is not None and digest!=expected: raise ValueError('input hash mismatch: '+str(path))
        if str(path) in self.hashes and self.hashes[str(path)]!=digest: raise ValueError('input changed during analysis')
        self.hashes[str(path)]=digest
        return path
    def rows(self,report,name):
        checks=json.loads(self.pin(Path(report)/'checksums.json').read_text())
        return list(csv.DictReader(self.pin(Path(report)/name,checks[name]).open()))
    def raw(self,run,role):
        root=result_path(run['input_path'])
        path=self.pin(root/'manifest.json',run['manifest_sha256'])
        manifest=json.loads(path.read_text())
        found=[a for a in manifest['artifacts'] if a['role']==role and a.get('acquisition',{}).get('status')=='available']
        if len(found)!=1:raise ValueError('missing/ambiguous '+role)
        a=found[0];p=root/a['path']
        if not p.resolve().is_relative_to(root.resolve()):raise ValueError('artifact outside run')
        return self.pin(p,a['sha256'])
    def verify(self):
        for p,h in self.hashes.items():self.pin(p,h)


def elapsed_stages(observations):
    required={'tls_handshake','mqtt_readiness','ttfb','ttlb','req_tfb','req_tlb'}
    if not required<=observations.keys(): raise ValueError('incomplete timing boundaries')
    t=lambda m,f:int(observations[m][f])
    for m in required:
        r=observations[m]
        if r['validity']!='valid' or r['unit']!='us' or t(m,'end_us')-t(m,'start_us')!=t(m,'value_us'):
            raise ValueError('invalid timing observation')
    if (t('mqtt_readiness','start_us')!=t('ttlb','start_us') or t('ttfb','start_us')!=t('ttlb','start_us') or t('ttfb','end_us')!=t('req_tfb','end_us')
        or t('ttlb','end_us')!=t('req_tlb','end_us') or t('req_tfb','start_us')!=t('req_tlb','start_us')):
        raise ValueError('inconsistent common timing checkpoints')
    edges=[t('ttlb','start_us'),t('tls_handshake','start_us'),t('tls_handshake','end_us'),
           t('mqtt_readiness','end_us'),t('req_tfb','start_us'),t('ttfb','end_us'),t('ttlb','end_us')]
    if edges!=sorted(edges):raise ValueError('overlapping/out-of-order stages')
    values=[b-a for a,b in zip(edges,edges[1:])]
    if sum(values)!=t('ttlb','value_us'):raise ValueError('stage conservation failed')
    return dict(zip(STAGES,values))


def timing(inputs,report,out):
    inv={r['run_key']:r for r in inputs.rows(report,'data-kex-inventory.csv')
         if r['exclusion_reason'] in NULL and r['execution_outcome']=='completed' and r['selected_input_status']=='verified'}
    groups={};audit=[]
    for r in inputs.rows(report,'data-kex-observations.csv'):
        if r['run_key'] not in inv or r['condition'] not in dict(KEX):continue
        group=groups.setdefault(r['run_key'],{})
        if r['metric'] in group:raise ValueError('multiple observations per run need reduction')
        group[r['metric']]=r
    for key,obs in groups.items():
        stages=elapsed_stages(obs)
        for stage,value in stages.items():audit.append(dict(run_key=key,condition=inv[key]['condition'],stage=stage,value_us=value))
    write_csv(out/'delivery-stage-observations.csv',audit)
    summary=[]
    for condition,_ in KEX:
        for stage in STAGES:
            values=[r['value_us']/1000 for r in audit if r['condition']==condition and r['stage']==stage]
            summary.append(dict(condition=condition,stage=stage,n=len(values),median_ms=median(values),mean_ms=mean(values),minimum_ms=min(values),maximum_ms=max(values)))
    write_csv(out/'delivery-stages.csv',summary)
    rows=[]
    for stage in STAGES:
        a,b=[next(r for r in summary if r['condition']==c and r['stage']==stage) for c,_ in KEX]
        rows.append([stage,f"{a['median_ms']:,.2f}",f"{b['median_ms']:,.2f}",f"{b['median_ms']-a['median_ms']:+,.2f}"])
    table(out/'delivery-stages.tex','Where the hybrid application delay occurs (ms).','tab:delivery-stages',
          ['Elapsed stage','P-256','Hybrid',r'$\Delta$ median'],rows,
          '30 runs per condition. Stages are disjoint within each run; their condition medians need not add. Hybrid uses P-256 + ML-KEM-768.')
    ops=inputs.rows(report,'data-kex-tls_operation_distributions.csv');rows=[]
    for metric,label in [('p256_keygen','P-256 key generation'),('p256_shared_secret','P-256 shared secret'),
            ('mlkem768_keygen','ML-KEM-768 key generation'),('mlkem768_decapsulate','ML-KEM-768 decapsulation'),
            ('certificate','Certificate processing'),('certificate_verify','CertificateVerify processing'),('finished','Finished processing')]:
        vals=[]
        for c in ('secp256r1','ML_KEM_768','SecP256r1MLKEM768'):
            found=[r for r in ops if r['condition']==c and r['metric']=='aggregate:'+metric+':elapsed']
            if len(found)!=1:raise ValueError('ambiguous TLS operation')
            vals.append('---' if found[0]['median'] in NULL else f"{float(found[0]['median'])/1000:,.2f}")
        rows.append([label,*vals])
    table(out/'kex-phases.tex','TLS phase and primitive medians with ECDSA P-256 server authentication (ms).','tab:kex-phase-comparison',
          ['Measured operation','P-256','ML-KEM-768','Hybrid'],rows,
          '30 runs per condition. Inclusive regions can overlap; values are not additive. A dash denotes an inapplicable operation.')


def equal_run_distribution(runs,grid):
    """Average empirical CDFs: every run has equal total weight, not every sample."""
    if not runs or any(not len(r) for r in runs):raise ValueError('nonempty runs required')
    arrays=[np.sort(np.asarray(r,dtype=float)) for r in runs]
    if any(not np.isfinite(r).all() for r in arrays):raise ValueError('finite samples required')
    return np.mean([np.searchsorted(r,grid,side='right')/len(r) for r in arrays],axis=0)


def weighted_quantiles(runs,quantiles):
    values=np.concatenate(runs)
    weights=np.concatenate([np.full(len(r),1/(len(runs)*len(r))) for r in runs])
    order=np.argsort(values,kind='stable');cdf=np.cumsum(weights[order]);cdf[-1]=1
    return values[order][np.searchsorted(cdf,quantiles,side='left')]


def power(inputs,report,out):
    inventory=inputs.rows(report,'data-energy-inventory.csv')
    intervals=inputs.rows(report,'data-energy-energy_intervals.csv')
    groups={};audit=[];policies=set()
    for r in inventory:
        try:
            if r['exclusion_reason'] not in NULL or r['selected_input_status']!='verified' or r['execution_outcome']!='completed':raise ValueError('ineligible run')
            states=acquisitions(inputs.raw(r,'stm32_result_stream'))
            if len(states)!=1:raise ValueError('ambiguous/missing energy acquisition')
            cid,state=next(iter(states.items()));c=state['complete']
            if state['reason']:raise ValueError(state['reason'])
            boundary=[v for v in intervals if v['run_key']==r['run_key'] and v['capture_id']==cid and v['scope']=='recorded_interval']
            if len(boundary)!=1 or boundary[0]['electrical_boundary'] in NULL:raise ValueError('electrical boundary unavailable')
            policies.add((boundary[0]['electrical_boundary'],boundary[0]['calibration'],c['firmware_sha256']))
            # Use every valid acquired sample, including the recorded lead-in/tail.
            # No clock alignment or energy integration is needed for this estimand.
            values=np.array([x[3] for x in state['samples']],dtype=float)
            if not len(values) or not np.isfinite(values).all():raise ValueError('invalid sampled power')
            groups.setdefault(r['condition'],[]).append(values)
            audit.append(dict(run_key=r['run_key'],condition=r['condition'],samples=len(values),reason='',median_w=float(np.median(values)),minimum_w=float(min(values)),maximum_w=float(max(values))))
        except (ValueError,KeyError) as exc:
            audit.append(dict(run_key=r['run_key'],condition=r['condition'],samples=0,reason=str(exc),median_w=None,minimum_w=None,maximum_w=None))
    if len(policies)!=1:raise ValueError('do not pool instrument/boundary/calibration policies')
    write_csv(out/'power-run-audit.csv',audit)
    lo=min(min(x) for runs in groups.values() for x in runs);hi=max(max(x) for runs in groups.values() for x in runs)
    grid=np.linspace(lo,hi,501);rows=[];curves=[]
    styles=['blue,solid','orange!85!black,dashed','green!60!black,densely dotted','purple,dashdotted']
    code=r'\begin{figure}[!htbp]\centering\begin{tikzpicture}\begin{axis}[width=.92\linewidth,height=6cm,xlabel={Power (W)},ylabel={Cumulative fraction},ymin=0,ymax=1,grid=major,grid style={gray!20},legend style={font=\scriptsize,at={(.5,-.25)},anchor=north,legend columns=2},tick label style={font=\small}]'+'\n'
    for i,(condition,runs) in enumerate(sorted(groups.items())):
        q=weighted_quantiles(runs,[.05,.25,.5,.75,.95]);label=condition.replace('tls_kex=','').replace('tls_auth=','').replace('; auth_mode=server','').replace('; ',' / ').replace('SecP256r1MLKEM768','Hybrid').replace('secp256r1','P-256').replace('ecdsa-p256','ECDSA').replace('mldsa65','ML-DSA-65').replace('rsa3072','RSA-3072')
        rows.append(dict(condition=condition,label=label,runs=len(runs),samples=sum(len(v) for v in runs),p05_w=q[0],q1_w=q[1],median_w=q[2],q3_w=q[3],p95_w=q[4]))
        cdf=equal_run_distribution(runs,grid)
        curves.extend(dict(condition=condition,power_w=x,cumulative_fraction=y) for x,y in zip(grid,cdf))
        code+=r'\addplot[thick,'+styles[i]+',no marks] coordinates {'+' '.join(f'({x:.6f},{y:.6f})' for x,y in zip(grid,cdf))+'};\n'+r'\addlegendentry{'+tex(label)+'}\n'
    code+=r'\end{axis}\end{tikzpicture}\caption{Distributions of valid recorded E5V power samples, with equal total weight per run. Each curve averages run-level empirical cumulative distributions; longer captures do not receive more weight. The full acquired windows include lead-in and tail samples. Samples within a run are not independent repetitions.}\label{fig:power-distribution}\end{figure}'+'\n'
    (out/'power-distribution.tex').write_text(code)
    write_csv(out/'power-distribution.csv',curves);write_csv(out/'power-summary.csv',rows)
    table(out/'power-summary.tex','Sampled power with duration removed from the weighting (W).','tab:sampled-power',
          ['KEx / certificate','Q1','Median','Q3','p95'],[[r['label'],*[f"{r[k]:.3f}" for k in ('q1_w','median_w','q3_w','p95_w')]] for r in rows],
          'Equal weight per run; complete valid acquisitions. E5V excludes ST-Link. Distribution overlap is descriptive, not a test of equivalence.')


def loss_outcomes(inputs,report,out):
    rows=[]
    for selection in ('recent_7','recent_8'):
        inv=inputs.rows(report,f'data-{selection}-inventory.csv');obs=inputs.rows(report,f'data-{selection}-observations.csv')
        for condition in sorted({r['condition'] for r in inv}):
            runs={r['run_key']:r for r in inv if r['condition']==condition};status={}
            for r in obs:
                if r['run_key'] in runs and r['metric']=='tls_handshake':
                    if r['run_key'] in status:raise ValueError('duplicate handshake outcome')
                    status[r['run_key']]=r['operation_outcome'] if r['validity']=='valid' and r['exclusion_reason'] in (*NULL,'not_successful_execution') else 'unknown'
            first=next(iter(runs.values()));known=sum(v=='success' for v in status.values())
            loss={'trial_reference':0,'thesis_loss_10':10,'thesis_loss_15':15}[first['network_condition']]
            label=('P-256' if first['tls_kex']=='secp256r1' else 'Hybrid')+' / '+('ECDSA' if first['tls_auth']=='ecdsa-p256' else 'ML-DSA')
            rows.append(dict(selection=selection,condition=condition,label=label,loss_percent=loss,attempts=len(runs),
                handshake_success=known,handshake_failed=sum(v=='failed' for v in status.values()),
                handshake_unclassified=len(runs)-sum(v in ('success','failed') for v in status.values()),
                run_completed=sum(v['execution_outcome']=='completed' for v in runs.values()),
                run_failed=sum(v['execution_outcome']=='failed' for v in runs.values())))
    write_csv(out/'loss-outcomes.csv',rows)
    labels=['P-256 / ECDSA','Hybrid / ECDSA','Hybrid / ML-DSA']
    code=r'\begin{figure}[!htbp]\centering\begin{tikzpicture}[x=1.18cm,y=.7cm,font=\scriptsize]'+'\n'
    for panel,(metric,title) in enumerate([('handshake_success','Handshake completion observed'),('run_completed','Complete experiment')]):
        offset=panel*4.6
        code+=rf'\node at ({offset+1},.9) {{{title}}};'+'\n'
        for yi,label in enumerate(labels):
            for xi,loss in enumerate((0,10,15)):
                r=next(r for r in rows if r['label']==label and r['loss_percent']==loss);fraction=r[metric]/r['attempts']
                x=offset+xi;y=-yi
                code+=rf'\filldraw[draw=white,fill=green!{100*fraction:.1f}!red] ({x-.5},{y-.4}) rectangle ({x+.5},{y+.4});'+'\n'
                code+=rf'\node at ({x},{y}) {{{r[metric]}/{r["attempts"]}}};'+'\n'
            if panel==0:code+=rf'\node[anchor=east] at ({offset-.6},{-yi}) {{{label}}};'+'\n'
        for xi,loss in enumerate((0,10,15)):code+=rf'\node at ({offset+xi},-2.8) {{{loss}\% loss}};'+'\n'
    code+=r'\node[anchor=west] at (-.5,-3.6) {Colour: \textcolor{red}{0\%} to \textcolor{green!50!black}{100\%} observed completion.};'+'\n'+r'\end{tikzpicture}\caption{Handshake and whole-experiment outcomes under loss, in separate 40-attempt confirmation selections. Missing handshake evidence remains unclassified, not a measured TLS failure. Experiment failures can occur after a successful handshake.}\label{fig:loss-outcomes}\end{figure}'+'\n'
    (out/'loss-outcomes.tex').write_text(code)


def publish(report, output):
    report,out=Path(report),Path(output)
    if out.exists():raise ValueError('choose a fresh chapter review output')
    inputs=Inputs();out.mkdir(parents=True)
    try:
        timing(inputs,report,out);power(inputs,report,out);loss_outcomes(inputs,report,out)
        inputs.verify()
        meta=dict(schema='pqc-chapter5-review',version=1,report=str(report),inputs=inputs.hashes,
            sources={Path(__file__).name:sha256_file(Path(__file__))},files={p.name:sha256_file(p) for p in out.iterdir()})
        (out/'chapter5-review-provenance.json').write_text(json.dumps(meta,indent=2)+'\n')
        return meta
    except Exception:
        # Partial products are deliberately not published as verified reports.
        (out/'INCOMPLETE').write_text('Analysis failed; this directory is not a published report.\n')
        raise
