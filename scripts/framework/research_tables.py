"""Research-style TLS tables from pinned selections and decoded handshake windows.

Packet phases use the capture clock only. Firmware elapsed times remain separate.
No TLS secrets, decrypted payloads or raw packet fields are exported.
"""
import csv
import io
import json
import math
import re
import shutil
import statistics
import subprocess
from pathlib import Path

FIELDS = ('frame.number', 'frame.time_epoch', 'ip.src', 'tcp.srcport', 'tcp.stream',
          'tcp.len', 'tls.handshake.type', 'mqtt.msgtype', 'tcp.analysis.retransmission')
VERSION = '4'


class Unavailable(ValueError):
    """Missing scientific coverage, distinct from damaged retained evidence."""



def validate(items):
    if not isinstance(items, list):
        raise ValueError('research_tables must be a list')
    ids = set()
    for item in items:
        if set(item) - {'id','kind','caption','entries','scenarios','metric'} or not {'id','kind','caption','entries'} <= set(item):
            raise ValueError('invalid research table fields')
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,65}', item['id']) or item['id'] in ids:
            raise ValueError('invalid or duplicate research table ID')
        ids.add(item['id'])
        if item['kind'] not in ('summary','ranking','network') or not isinstance(item['caption'],str) or not item['caption'].strip():
            raise ValueError('invalid research table kind/caption')
        if item['kind']=='ranking' and item.get('metric') not in ('total_ms','traffic_bytes'):
            raise ValueError('ranking requires total_ms or traffic_bytes')
        scenarios = item.get('scenarios', [])
        if not isinstance(scenarios,list) or len(set(scenarios))!=len(scenarios) or any(not isinstance(s,str) or not s for s in scenarios):
            raise ValueError('invalid research scenarios')
        if item['kind']=='network' and not scenarios:
            raise ValueError('network table requires ordered scenarios')
        if not isinstance(item['entries'],list) or not item['entries']:
            raise ValueError('research table requires explicit entries')
        seen=set()
        for e in item['entries']:
            if set(e)-{'label','selection','condition','scenario','reason','algorithm'} or not isinstance(e.get('label'),str) or not e['label']:
                raise ValueError('invalid research entry')
            if ('selection' in e) != ('condition' in e) or (not e.get('selection') and not e.get('reason')):
                raise ValueError('entry requires exact selection/condition or missing-evidence reason')
            if item['kind']=='network' and e.get('scenario') not in scenarios:
                raise ValueError('unknown research scenario')
            if 'algorithm' in e and e['algorithm'] not in ALGORITHMS:
                raise ValueError('unknown research algorithm')
            identity=(e['label'],e.get('scenario'))
            if identity in seen: raise ValueError('duplicate research cell')
            seen.add(identity)
        if item['kind']=='network' and seen != {(e['label'],s) for e in item['entries'] for s in scenarios}:
            raise ValueError('every network cell must be explicitly selected or marked unavailable')


def handshake_window(rows, client, server_port):
    """Exactly one decoded TLS handshake in one explicitly selected connection.

    Count transmitted TCP payload (including repeated payload) in the inclusive
    first-client-payload .. client-Finished packet window. Fail closed when MQTT
    shares that window. This is a packet-window metric, not TLS message size.
    """
    streams={r['tcp.stream'] for r in rows}
    if len(streams)!=1: raise ValueError('ambiguous_or_missing_tcp_stream')
    def types(r): return set(r['tls.handshake.type'].split(','))
    ch=[r for r in rows if r['ip.src']==client and '1' in types(r)]
    sh=[r for r in rows if r['tcp.srcport']==str(server_port) and '2' in types(r)]
    fin=[r for r in rows if r['ip.src']==client and '20' in types(r)]
    if len(ch)!=1 or len(sh)!=1 or len(fin)!=1:
        raise ValueError('requires_one_decoded_clienthello_serverhello_client_finished')
    first=min(int(r['frame.number']) for r in rows if r['ip.src']==client and int(r['tcp.len'])>0)
    end=int(fin[0]['frame.number']); middle=int(sh[0]['frame.number'])
    if not first<=int(ch[0]['frame.number'])<middle<end:
        raise ValueError('invalid_handshake_packet_order')
    window=[r for r in rows if first<=int(r['frame.number'])<=end]
    if any(r['mqtt.msgtype'] for r in window): raise ValueError('application_data_overlaps_handshake_window')
    t0=float(next(r['frame.time_epoch'] for r in window if int(r['frame.number'])==first))
    t1=float(sh[0]['frame.time_epoch']);t2=float(fin[0]['frame.time_epoch'])
    if not t0<=t1<=t2: raise ValueError('nonmonotonic_capture_clock')
    c=sum(int(r['tcp.len']) for r in window if r['ip.src']==client)
    s=sum(int(r['tcp.len']) for r in window if r['tcp.srcport']==str(server_port))
    return dict(packet_ms=(t2-t0)*1000,a_ms=(t1-t0)*1000,b_ms=(t2-t1)*1000,cbytes=c,sbytes=s,traffic_bytes=c+s,
                first_packet=first,server_hello_packet=middle,client_finished_packet=end)


def decode(run, endpoint):
    from framework.analysis_paths import result_path
    from framework.packet_analysis import _artifact_path, _validate_artifact_hash
    from framework.timing_summary import digest
    root=result_path(run['input_path']); manifest=json.loads((root/'manifest.json').read_text())
    paths=[]
    for role in ('packet_capture','tls_key_log'):
        p=_artifact_path(root,manifest,role)
        if p is None: raise Unavailable('missing_'+role)
        entries=[a for a in manifest['artifacts'] if a.get('role')==role]
        if len(entries)!=1 or not entries[0].get('sha256') or p.is_symlink():
            raise ValueError('unverified_'+role)
        _validate_artifact_hash(manifest,role,p);paths.append(p)
    if not shutil.which('tshark'): raise Unavailable('tshark_unavailable')
    from framework.network_analysis import validate_selection
    validate_selection(endpoint)
    if endpoint['window']['kind']!='retained_flow': raise Unavailable('requires_complete_retained_flow')
    client,server,port=endpoint['client_ip'],endpoint['server_ip'],endpoint['server_port']
    display=f'ip.addr=={client} && ip.addr=={server} && tcp.port=={port} && tcp.len>0'
    command=['tshark','-2','-r',str(paths[0]),'-o','tls.keylog_file:'+str(paths[1]),'-d',f'tcp.port=={port},tls',
             '-Y',display,'-T','fields','-E','separator=\t','-E','quote=d']
    for field in FIELDS: command+=['-e',field]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode: raise Unavailable('tshark_decode_failed')
    rows=list(csv.DictReader(io.StringIO(result.stdout),fieldnames=FIELDS,delimiter='\t',quotechar='"'))
    try:
        values=handshake_window(rows,client,port)
    except ValueError as exc:
        raise Unavailable(str(exc)) from exc
    return dict(values,pcap_sha256=digest(paths[0]),keylog_sha256=digest(paths[1]))


def collect(prepared, items):
    validate(items)
    cache={}; observations=[]; output={}
    selections={s['id']:s for s in prepared['specification']['selections']}
    for item in items:
        cells=[]
        for e in item['entries']:
            row=dict(e,total_ms=None,packet_ms=None,a_ms=None,b_ms=None,cbytes=None,sbytes=None,traffic_bytes=None,n_runs=0,n_packets_runs=0)
            if not e.get('selection'): cells.append(row);continue
            name=e['selection'];condition=e['condition']
            if name not in prepared['analyses']: raise ValueError('unknown research selection: '+name)
            analysis=prepared['analyses'][name]
            if condition not in analysis['normalized_comparison']['conditions']: raise ValueError('unknown research condition: '+condition)
            if e.get('algorithm'):
                values=analysis['normalized_comparison']['conditions'][condition]
                axis='tls_kex' if ALGORITHMS[e['algorithm']][2]=='kex' else 'tls_auth'
                if values.get(axis)!=e['algorithm']:
                    raise ValueError('research algorithm does not match selected condition')
            frames=analysis['frames']
            inventory=[r for r in frames.get('inventory',{}).get('rows',[]) if r['condition']==condition]
            row.update(captured_attempts=len(inventory),
                completed_attempts=sum(r.get('execution_outcome')=='completed' for r in inventory),
                failed_attempts=sum(r.get('execution_outcome')=='failed' for r in inventory),
                unknown_attempts=sum(r.get('execution_outcome') not in ('completed','failed') for r in inventory),
                accepted_captures=sum(r.get('capture_acceptance')=='accepted' for r in inventory))
            current = prepared.get('selected', {}).get(name)
            # Missing captures cannot supply latency, but still count as planned
            # attempts of the exact cases represented in this condition.
            case_ids = {r.get('case_id') for r in inventory} - {None}
            attempts = current[1][current[1].case_id.isin(case_ids)].drop_duplicates('run_key') if current is not None else None
            row['current_attempts'] = len(attempts) if attempts is not None else len(inventory)
            row['no_capture_attempts'] = int(attempts.row_kind.eq('campaign_attempt_without_capture').sum()) if attempts is not None else 0
            summaries=[r for r in frames.get('tls_run_distributions',{}).get('rows',[]) if r['condition']==condition and r['metric']=='tls_handshake']
            if len(summaries)>1: raise ValueError('research cell mixes evidence strata')
            if summaries:
                s=summaries[0];row.update(total_ms=s['median']/1000 if s['median'] is not None else None,n_runs=s.get('n_runs',0))
                for quantile in ('q1','q3','p95'):
                    row[quantile+'_ms'] = s.get(quantile)/1000 if s.get(quantile) is not None else None
            if item['kind']!='network' and (item['kind']=='summary' or item.get('metric')=='traffic_bytes'):
                samples=[]
                for run in frames.get('inventory',{}).get('rows',[]):
                    if run['condition']!=condition or run.get('exclusion_reason'):continue
                    endpoint=selections[name].get('network',{}).get(run['run_key'])
                    identity=(name,run['run_key'])
                    if identity not in cache:
                        obs=dict(selection=name,condition=condition,run_key=run['run_key'])
                        try:
                            if endpoint is None: raise Unavailable('explicit_endpoint_not_selected')
                            obs.update(decode(run,endpoint),reason=None)
                        except (Unavailable,subprocess.TimeoutExpired) as exc:
                            obs['reason']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                        cache[identity]=obs;observations.append(obs)
                    if cache[identity]['reason'] is None:samples.append(cache[identity])
                row['n_packets_runs']=len(samples)
                for metric in ('packet_ms','a_ms','b_ms','cbytes','sbytes','traffic_bytes'):
                    row[metric]=statistics.median(r[metric] for r in samples) if samples else None
                row['packet_reason']=None if samples else 'no_valid_decoded_handshake_windows; see observations'
            if row['total_ms'] is None:row['reason']='no_valid_successful_handshake_measurements'
            cells.append(row)
        output[item['id']]=cells
    return output,observations


# Security categories apply to the varied primitive, not to the TLS connection.
# Hybrids are grouped by their PQ component; classical component bits are retained.
ALGORITHMS = {
    'x25519': (1, 'classical', 'kex', 128),
    'secp256r1': (1, 'classical', 'kex', 128),
    'secp384r1': (3, 'classical', 'kex', 192),
    'secp521r1': (5, 'classical', 'kex', 256),
    'ML_KEM_512': (1, 'pqc', 'kex', None),
    'ML_KEM_768': (3, 'pqc', 'kex', None),
    'ML_KEM_1024': (5, 'pqc', 'kex', None),
    'X25519MLKEM768': (3, 'hybrid', 'kex', 128),
    'SecP256r1MLKEM768': (3, 'hybrid', 'kex', 128),
    'SecP384r1MLKEM1024': (5, 'hybrid', 'kex', 192),
    'rsa3072': (1, 'classical', 'sig', 128),
    'ecdsa-p256': (1, 'classical', 'sig', 128),
    'ecdsa-p384': (3, 'classical', 'sig', 192),
    'mldsa65': (3, 'pqc', 'sig', None),
}
COLOURS = r'''\definecolor{researchBlue}{RGB}{192,218,234}
\definecolor{researchOrange}{RGB}{250,166,108}
\definecolor{researchPQC}{RGB}{205,217,235}
\definecolor{researchClassical}{RGB}{249,215,191}
\definecolor{researchHybrid}{RGB}{203,226,209}'''
FAMILY_COLOUR = {'classical': 'researchClassical', 'pqc': 'researchPQC', 'hybrid': 'researchHybrid', 'unknown': 'white'}


def classification(row):
    return ALGORITHMS.get(row.get('algorithm'), (None, 'unknown', None, None))


def metric_value(value):
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError('invalid research metric')
    return value


def bar(value, maximum, width=24):
    """Fixed-width, zero-origin bar; its number is on the bar's centre line."""
    metric_value(value); metric_value(maximum)
    if value is None: return r'\textemdash{}'
    if maximum < value: raise ValueError('bar maximum below value')
    length = width * value / maximum if maximum else 0
    # Number overlaps the coloured area as in the reference; short bars put it
    # immediately after their endpoint. The cell width/origin never moves.
    return (r'\begin{tikzpicture}[x=1mm,y=1mm,baseline=-0.6ex]'
            rf'\path[use as bounding box] (0,-1.5) rectangle ({width+12},1.5);'
            rf'\draw[fill=researchBlue,draw=black!55,line width=0.2pt] (0,-1.3) rectangle ({length:.3f},1.3);'
            rf'\node[anchor=west,inner sep=0pt,font=\scriptsize] at ({max(.5,length-11):.3f},0) {{{value:,.2f}}};'
            r'\end{tikzpicture}')


def swatch(colour):
    return r'\tikz[baseline=-0.5ex]\draw[fill='+colour+r',draw=black!50,line width=0.2pt] (0,0) rectangle (0.22,0.18);'


def algorithm_label(row):
    from framework.thesis_tables import escape_tex as esc
    family = classification(row)[1]
    label = esc(row['label'])
    if family == 'classical': return r'\textbf{'+label+'}'
    if family == 'hybrid': return label+r'\textsuperscript{\ensuremath{\dagger}}'
    return label


def level_note(rows):
    note = ('Lvl: PQ security category; classical rows use 128/192/256-bit strength groups 1/3/5 '
            '(not quantum resistance). Levels describe the varied primitive, not overall TLS security.')
    if any(classification(r)[1]=='hybrid' for r in rows):
        note += (' Hybrid rows (dagger) use the PQ component category: P-256/X25519 + ML-KEM-768 '
                 'combine 128-bit classical strength with category 3; P-384 + ML-KEM-1024 combines 192-bit with category 5.')
    return note


def ranking_positions(rows, metric):
    """Five equal bins on each panel's own metric range, as a ranked axis diagram."""
    valid = sorted((r for r in rows if metric_value(r.get(metric)) is not None), key=lambda r:(r[metric],r['label']))
    if metric=='total_ms' and any(r[metric] <= 0 for r in valid):
        raise ValueError('logarithmic latency ranking requires positive measurements')
    values = [math.log(r[metric]) if metric=='total_ms' else r[metric] for r in valid]
    if not values: return []
    low, high = min(values), max(values)
    return [(r, min(4,int((v-low)/(high-low)*5)) if high>low else 0) for r,v in zip(valid,values)]


def render_ranking(item, rows):
    from framework.thesis_tables import escape_tex as esc
    metric=item['metric']
    lines=[r'\begin{figure}[htbp]\centering\begingroup\scriptsize', COLOURS,
           r'\noindent '+swatch('researchPQC')+r' Post-quantum\qquad '+swatch('researchClassical')+r' Pre-quantum\qquad '+swatch('researchHybrid')+r' Hybrid\par\medskip',
           r'\resizebox{\linewidth}{!}{%',
           r'\begin{tikzpicture}[x=1mm,y=1mm,font=\scriptsize]',
           r'\draw[line width=0.6pt] (0,0) -- (148,0);']
    groups={}
    for row in rows:
        panel=classification(row)[2] or 'kex'
        groups.setdefault(panel,[]).append(row)
    for panel,panel_rows in groups.items():
        bins={n:[] for n in range(5)}
        for row,n in ranking_positions(panel_rows,metric):bins[n].append(row)
        sign=1 if panel=='kex' else -1
        for n,group in bins.items():
            x=29.5*n
            for lane,row in enumerate(group):
                y=sign*(4+lane*4.4)
                colour=FAMILY_COLOUR[classification(row)[1]]
                lines.append(rf'\node[anchor=west,fill={colour},inner sep=1pt,font=\fontsize{{6}}{{7}}\selectfont] at ({x:.1f},{y:.1f}) {{{esc(row["label"])}}};')
    for n in range(6):lines.append(rf'\draw[fill=white,line width=0.4pt] ({29.5*n:.1f},0) circle (0.7);')
    left,right=('fast','slow') if metric=='total_ms' else ('low','high')
    lines += [rf'\node[anchor=east] at (-1,0) {{{left}}};',rf'\node[anchor=west] at (149,0) {{{right}}};',r'\end{tikzpicture}}\par\smallskip',
              r'\noindent KA above; SIG below. Each is ranked separately. '+ ('Five logarithmic latency bins' if metric=='total_ms' else 'Five linear traffic-volume bins')+r'; within a bin, values increase away from the axis.\par',r'\endgroup',
              r'\caption{'+esc(item['caption'])+r'}\label{fig:'+item['id']+'}']
    missing=[r['label'] for r in rows if r.get(metric) is None]
    if missing:lines.append(r'\par\scriptsize Unavailable (not ranked): '+esc(', '.join(missing))+'.')
    lines.append(r'\end{figure}')
    return '\n'.join(lines)+'\n'


def render(item, rows):
    from framework.thesis_tables import escape_tex as esc
    if item['kind']=='ranking': return render_ranking(item,rows)
    network=item['kind']=='network'
    lines=([r'\begin{landscape}'] if network else [])+[r'\begingroup\scriptsize',COLOURS,
           (r'\setlength{\tabcolsep}{1pt}' if network else r'\setlength{\tabcolsep}{3pt}')+r'\renewcommand{\arraystretch}{1.12}']
    if network:
        scenarios=item['scenarios'];spec='@{}cl'+'l'*len(scenarios)+'@{}'
        by={(r['label'],r['scenario']):r for r in rows}
        representatives=list({r['label']:r for r in rows}.values())
        maxima={s:max((metric_value(r.get('total_ms')) or 0 for r in rows if r['scenario']==s),default=0) for s in scenarios}
        headers=r'Lvl & Algorithm & '+' & '.join(r'\shortstack[l]{'+esc(s).replace(' / ',r'\\')+r'\ (ms)}' for s in scenarios)+r'\\\midrule'
    else:
        spec='@{}cllrr@{}';representatives=rows
        maximum=max((metric_value(r['packet_ms']) or 0 for r in rows),default=0)
        headers=(r'Lvl & Algorithm & Latency median (ms) & \multicolumn{2}{c}{Data sent (B)}\\'
                 r'\cmidrule(l){4-5}'
                 r' & & & Client & Server\\\midrule')
    lines += [r'\begin{longtable}{'+spec+'}',r'\caption{'+esc(item['caption'])+r'}\label{tab:'+item['id']+r'}\\',
              r'\toprule',headers,r'\endfirsthead',r'\toprule',headers,r'\endhead',r'\bottomrule\endfoot']
    representatives=sorted(representatives,key=lambda r:(classification(r)[0] or 99, r['label']))
    previous=object()
    for row in representatives:
        level=classification(row)[0]
        if level!=previous and lines[-1]!=r'\bottomrule\endfoot': lines.append(r'\midrule')
        cells=[str(level) if level is not None and level!=previous else (r'\textemdash{}' if level is None else ''),algorithm_label(row)]
        previous=level
        if network:cells += [bar(by[row['label'],s].get('total_ms'),maxima[s],18) for s in scenarios]
        else:
            cells += [bar(row['packet_ms'],maximum,34)]
            cells += [r'\textemdash{}' if row[k] is None else f'{metric_value(row[k]):,.0f}' for k in ('cbytes','sbytes')]
        lines.append(' & '.join(cells)+r'\\')
    lines += [r'\end{longtable}',r'\noindent Legend: \textbf{Pre-quantum}\quad '+(swatch('researchBlue')+r' Successful TLS handshake' if network else swatch('researchBlue')+r' ClientHello $\rightarrow$ client Finished')+r'\par\smallskip']
    note=('Successful-handshake medians; each scenario column has its own linear bar scale. Compare lengths within columns. A dash is unavailable, not zero. Failures and exclusions are retained in the companion CSV.' if network else
          'Median packet-clock latency from ClientHello to client Finished, calculated per capture before aggregation. Bars share one linear scale. Bytes count transmitted TCP payload through decoded client Finished, including retransmissions; subsequent MQTT and network headers are excluded.')
    lines += [r'\noindent '+esc(note)+r'\par',r'\noindent '+esc(level_note(rows))+r'\par']
    metric, count = ('total_ms','n_runs') if network else ('packet_ms','n_packets_runs')
    counts=sorted({r.get(count,0) for r in rows if r.get(metric) is not None})
    if counts:lines.append(r'\noindent '+esc(('Timing runs' if network else 'Packet captures')+' per measured cell: '+', '.join(str(n) for n in counts)+'. Exact timing/packet counts and outcomes are in the companion CSV.')+r'\par')
    if any(r.get('reason') for r in rows):lines.append(r'\noindent Unavailable cells retain their specific reasons in the companion CSV.\par')
    lines += [r'\endgroup']+([r'\end{landscape}'] if network else [])
    return '\n'.join(lines)+'\n'



def render_coverage(item, rows):
    """Publish the denominator beside conditional latency, from the same cells."""
    from framework.thesis_tables import escape_tex as esc
    scenarios = item['scenarios']
    by = {(r['label'],r['scenario']):r for r in rows}
    representatives = sorted({r['label']:r for r in rows}.values(),
        key=lambda r:(classification(r)[0] or 99,r['label']))
    lines = [r'\begin{landscape}\begingroup\scriptsize',
        r'\setlength{\tabcolsep}{4pt}\renewcommand{\arraystretch}{1.12}',
        r'\begin{longtable}{@{}cl'+'c'*len(scenarios)+r'@{}}',
        r'\caption{Capture coverage for '+esc(item['caption'].rstrip('.'))+r'.}\label{tab:'+item['id']+r'-coverage}\\',
        r'\toprule Lvl & Algorithm & '+' & '.join(r'\shortstack{'+esc(s).replace(' / ',r'\\')+'}' for s in scenarios)+r'\\\midrule\endhead',
        r'\bottomrule\endfoot']
    previous = object()
    for row in representatives:
        level = classification(row)[0]
        if level != previous and lines[-1] != r'\bottomrule\endfoot': lines.append(r'\midrule')
        cells = [str(level) if level is not None and level != previous else '',algorithm_label(row)]
        previous = level
        for scenario in scenarios:
            cell = by[row['label'],scenario]
            cells.append(f"{cell['completed_attempts']}/{cell['current_attempts']} [{cell['n_runs']}]" if 'current_attempts' in cell else r'\textemdash{}')
        lines.append(' & '.join(cells)+r'\\')
    lines += [r'\end{longtable}',
        r'\noindent Cells: completed/current attempts [eligible timing runs]. Completion is the execution outcome; accepted captures and exclusions are separate fields in the companion CSV. Missing captures remain in the denominator. A dash means no selected batch, not zero attempts.\par',
        r'\noindent Each cell retains its exact selection and condition in the CSV. Original and continuation batches are not pooled; unequal counts reflect the selected batch.\par',
        r'\endgroup\end{landscape}']
    return '\n'.join(lines)+'\n'


def publish(directory,prepared):
    from framework.thesis_tables import write_csv
    items=prepared['specification'].get('presentation',{}).get('research_tables',[])
    if not items:return []
    tables,observations=collect(prepared,items);directory=Path(directory)
    write_csv(directory/'research-handshake-observations.csv',observations)
    version=subprocess.run(['tshark','--version'],capture_output=True,text=True).stdout.splitlines()[0] if shutil.which('tshark') else None
    (directory/'research-method.json').write_text(json.dumps(dict(version=VERSION,tshark=version,bytes='transmitted TCP payload including retransmissions; first client payload through decoded client Finished',clock='pcap clock for CH-SH-CF, firmware clock for target total'),indent=2)+'\n')
    result=[]
    for item in items:
        name=item['id'];write_csv(directory/(name+'.csv'),tables[name]);(directory/(name+'.tex')).write_text(render(item,tables[name]))
        result.append(dict(section=name,tex=name+'.tex',csv=name+'.csv'))
        if item['kind']=='network':
            coverage=name+'-coverage'
            (directory/(coverage+'.tex')).write_text(render_coverage(item,tables[name]))
            result.append(dict(section=coverage,tex=coverage+'.tex',csv=name+'.csv'))
    return result
