"""Publish compact tables and domain comparisons from pinned verified archives.

This presentation layer uses the maintained archive decoder. It neither executes
experiments nor changes exported notebooks/captures. No inference is performed.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from framework.analysis_paths import result_path
from framework.archive_table import load_archive
from framework.timing_dataset import _has_symlink

from framework import analysis_comparison as comparison

VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
KINDS = {'secure_boot', 'secure_boot_stack', 'tls_auth', 'tls_kex', 'tls_auth_followup', 'network_loss'} | set(comparison.RECIPES)
LOSS_COLUMN = 'control__network_configured__loss_percent'
KEYS = {'network_loss': ['transport_mode','tls_auth','auth_mode','tls_kex',LOSS_COLUMN], 'secure_boot': ['secure_boot'], 'secure_boot_stack': ['secure_boot'],
        'tls_auth': ['tls_auth', 'auth_mode'], 'tls_kex': ['tls_kex'],
        'tls_auth_followup': ['tls_auth', 'auth_mode']}
LABELS = {
    'integrity_sha256': 'SHA-256 integrity only', 'ecdsa_p256': 'ECDSA P-256',
    'ecdsa_p384': 'ECDSA P-384', 'ecdsa_p521': 'ECDSA P-521',
    'ecdsa-p256': 'ECDSA P-256', 'ecdsa-p384': 'ECDSA P-384',
    'ed25519': 'Ed25519', 'ed448': 'Ed448', 'rsa2048': 'RSA-2048',
    'rsa3072': 'RSA-3072', 'rsa4096': 'RSA-4096',
    'mldsa44': 'ML-DSA-44', 'mldsa65': 'ML-DSA-65', 'mldsa87': 'ML-DSA-87',
    'secp256r1': 'P-256', 'secp384r1': 'P-384', 'secp521r1': 'P-521',
    'x25519': 'X25519', 'ML_KEM_512': 'ML-KEM-512',
    'ML_KEM_768': 'ML-KEM-768', 'ML_KEM_1024': 'ML-KEM-1024',
    'SecP256r1MLKEM768': 'P-256 + ML-KEM-768',
    'SecP384r1MLKEM1024': 'P-384 + ML-KEM-1024',
    'X25519MLKEM768': 'X25519 + ML-KEM-768',
}
ORDER = {name: i for i, name in enumerate([
    'integrity_sha256','rsa2048','rsa3072','rsa4096','ecdsa_p256','ecdsa_p384',
    'ecdsa_p521','ed25519','ed448','mldsa44','mldsa65','mldsa87',
    'ecdsa-p256','ecdsa-p384','secp256r1','secp384r1','secp521r1','x25519',
    'SecP256r1MLKEM768','X25519MLKEM768','SecP384r1MLKEM1024',
    'ML_KEM_512','ML_KEM_768','ML_KEM_1024'])}

# key: (archive column, conversion divisor, unit, observation scope)
METRICS = {
    'integrity': ('boot__integrity_ms',1,'ms','timing'),
    'auth': ('boot__authenticity_ms', 1, 'ms', 'timing'),
    'image_verify': ('boot__image_verification_ms', 1, 'ms', 'timing'),
    'boot_flash': ('boot__bootloader_flash_bytes', 1, 'B', 'static'),
    'boot_ram': ('boot__bootloader_static_ram_bytes', 1, 'B', 'static'),
    'signature': ('boot__image_signature_used_bytes', 1, 'B', 'static'),
    'boot_stack': ('boot__boot_stack_high_water_bytes', 1, 'B', 'stack'),
    'completion': ('timing__ttlb_us', 1000000, 's', 'timing'),
    'loss_handshake': ('timing__tls_handshake_us', 1000000, 's', 'timing'),
    'handshake': ('timing__tls_handshake_us', 1000, 'ms', 'timing'),
    'sign': ('tls__aggregate__signature_sign__elapsed_us', 1000, 'ms', 'timing'),
    'verify': ('tls__aggregate__signature_verify__elapsed_us', 1000, 'ms', 'timing'),
    'app_flash': ('resource__flash_section_bytes', 1024, 'KiB', 'static'),
    'app_ram': ('resource__ram_static_base_bytes', 1024, 'KiB', 'static'),
    'heap': ('resource__freertos_heap_peak_used_bytes', 1024, 'KiB', 'runtime'),
    'workspace': ('resource__workspace_peak_used_bytes', 1024, 'KiB', 'runtime'),
}
METHOD = ('Current attempt per campaign slot; successful execution, valid capture and verified selected inputs. '
          'One observation per retained capture. Timings: mean (sample SD, n-1). '
          'No outlier removal, zero filling, confidence intervals or independence claim. '
          'Static sizes require a single observed value within each case; regional runtime peaks use the observed maximum. '
          'Missing or inapplicable measurements are shown as an em dash.')


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value) is not None


def read_spec(path):
    if isinstance(path, dict):
        value = json.loads(canonical(path))
        path = ROOT / 'analysis-selection.json'
    else:
        path = result_path(path).resolve()
        value = json.loads(path.read_text())
    from framework.analysis_presentation import validate
    validate(value.get('presentation', {}))
    if set(value) - {'version', 'exports', 'selections', 'presentation'} or value.get('version') != VERSION:
        raise ValueError('unsupported thesis-table specification')
    if not isinstance(value.get('exports'), list) or not value['exports']:
        raise ValueError('select at least one explicit export')
    for export in value['exports']:
        if set(export) != {'path', 'archive_sha256'} or not re.fullmatch(r'[0-9a-f]{64}', export['archive_sha256']):
            raise ValueError('each export requires its path and exact archive_sha256')
        export['path'] = str(result_path(path.parent / export['path']).absolute())
    selections = value.get('selections')
    if not isinstance(selections, list) or not selections:
        raise ValueError('select at least one campaign')
    ids = set()
    for item in selections:
        required = {'id', 'kind', 'filters', 'source_commit', 'expected_current_runs'}
        if set(item) - (required | {'stack_selection', 'baseline_selection'} | comparison.FIELDS) or not required <= set(item):
            raise ValueError('invalid selection fields')
        if not _identifier(item['id']) or item['id'] in ids or item['kind'] not in KINDS:
            raise ValueError('invalid/duplicate selection id or unsupported kind')
        ids.add(item['id'])
        if not isinstance(item['filters'], dict) or not item['filters']:
            raise ValueError('explicit non-empty equality filters are required')
        if any(not isinstance(k, str) or (type(v) not in (str, bool, int, float) or isinstance(v, float) and not math.isfinite(v)) for k, v in item['filters'].items()):
            raise ValueError('filters must be scalar equality selectors')
        general = item['kind'] in comparison.RECIPES
        if general:
            comparison.validate(item)
        elif set(item) & comparison.FIELDS:
            raise ValueError('domain options require a domain recipe')
        if not (general and item['source_commit'] is None) and not re.fullmatch(r'[0-9a-f]{40}', item['source_commit'] or ''):
            raise ValueError('selection requires a full captured source commit')
        if type(item['expected_current_runs']) is not int or item['expected_current_runs'] < 1:
            raise ValueError('expected_current_runs must be positive')
    by_id = {x['id']: x for x in selections}
    for item in selections:
        for field, kind in [('stack_selection', 'secure_boot_stack'), ('baseline_selection', 'tls_auth')]:
            if field in item and (item[field] not in by_id or by_id[item[field]]['kind'] != kind):
                raise ValueError('invalid ' + field)
        if item['kind'] == 'tls_auth_followup' and 'baseline_selection' not in item:
            raise ValueError('follow-up must name its original authentication selection')
    return value


def load_inputs(spec):
    frames, provenance = [], []
    for export in spec['exports']:
        path = result_path(export['path'])
        if digest(path/'archive.json') != export['archive_sha256']:
            raise ValueError('selected archive identity changed: ' + str(path))
        frame = load_archive(path, verify_sources=True)
        frame['_export'] = str(path)
        frames.append(frame)
        provenance.append(dict(path=str(path), archive_sha256=export['archive_sha256'],
            runs_sha256=digest(path/'runs.csv'), rows=len(frame)))
    frame = pd.concat(frames, ignore_index=True)
    if frame.row_id.duplicated().any():
        raise ValueError('overlapping exports would double-count observations; select disjoint exports')
    return frame, provenance


def select(frame, item):
    if item['kind'] in comparison.RECIPES:
        return comparison.select(frame, item)
    mask = pd.Series(True, index=frame.index)
    for key, value in item['filters'].items():
        if key not in frame:
            raise ValueError('unknown filter column: ' + key)
        mask &= frame[key].eq(value).fillna(False)
    selected = frame.loc[mask].copy()
    current = selected.loc[selected.attempt_current.eq(True)].copy()
    if current.run_key.nunique() != item['expected_current_runs']:
        raise ValueError('unexpected current capture count for ' + item['id'])
    if current.row_kind.eq('campaign_attempt_without_capture').any():
        raise ValueError('selection includes attempts without captures; retain them in the attempt audit and establish their controls before producing a comparison or reliability denominator')
    if current.run_key.duplicated().any() or not current.row_kind.eq('retained_capture').all():
        raise ValueError('this table requires one retained capture row per run; repeated TLS needs per-run aggregation')
    if not current.source_commit.eq(item['source_commit']).fillna(False).all() or not current.git_dirty.eq(False).fillna(False).all():
        raise ValueError('source identity is missing, dirty or conflicts with selection')
    kind = item['kind']
    expected_stack = kind == 'secure_boot_stack'
    if not current.boot_stack_profiling.eq(expected_stack).fillna(False).all():
        raise ValueError('stack profiling must remain a separate selection')
    if current.boot_uart_diagnostics.fillna(True).any():
        raise ValueError('diagnostic boot timings are not normal table observations')
    fixed_controls=['target','gateway','workload','energy_enabled']
    if kind.startswith('tls_'):
        fixed_controls += ['payload_bytes','chunk_bytes','control__mqtt__qos',
                           'control__network_configured__enabled']
    if kind == 'network_loss':
        fixed_controls += ['payload_bytes','chunk_bytes','control__mqtt__qos','secure_boot',
            'control__network_configured__enabled','control__network_configured__rtt_ms',
            'control__network_configured__rate_kbit','control__network_configured__mtu']
        if not current.control__network_configured__enabled.eq(True).fillna(False).all():
            raise ValueError('loss grid requires enabled impairment, including its zero-loss control')
        if current[LOSS_COLUMN].isna().any() or not current[LOSS_COLUMN].between(0,100).all():
            raise ValueError('loss grid requires configured loss percentages in [0,100]')
        if not current.transport_mode.isin(['tls','plaintext']).all():
            raise ValueError('unsupported loss-grid transport')
        tls=current[current.transport_mode.eq('tls')]
        if len(tls) and (tls.auth_mode.isna().any() or tls.auth_mode.nunique() != 1):
            raise ValueError('loss grid requires one TLS authentication mode')
    for col in fixed_controls:
        if current[col].isna().any() or current[col].nunique() != 1:
            raise ValueError('conflicting or missing selection control: ' + col)
    if kind.startswith('tls_'):
        if not current.transport_mode.eq('tls').fillna(False).all():
            raise ValueError('TLS table contains non-TLS captures')
        if not current.control__network_configured__enabled.eq(False).fillna(False).all():
            raise ValueError('baseline TLS tables require impairment disabled; keep loss controls separate')
        fixed = ['tls_kex'] if kind != 'tls_kex' else ['tls_auth','auth_mode']
        for col in fixed:
            if current[col].isna().any() or current[col].nunique() != 1:
                raise ValueError('conflicting fixed TLS control: ' + col)
    # Preserve separate cases; never average different configurations under one label.
    for _, group in current.groupby(KEYS[kind], dropna=False):
        for col in ['configuration_identity','firmware_identity','git_state_identity']:
            if group[col].isna().any() or group[col].nunique() != 1:
                raise ValueError('conflicting or missing case control: ' + col)
    return selected, current


def eligible(group):
    return group.loc[(group.run_success.eq(True) & group.capture_valid.eq(True)
                      & group.selected_inputs_valid.eq(True)).fillna(False)]


def statistics(values):
    a = values.dropna().to_numpy(dtype=float)
    if not len(a):
        return dict(n=0, mean=None, sd=None, median=None, q1=None, q3=None, cv_pct=None, maximum=None)
    if not np.isfinite(a).all():
        raise ValueError('non-finite measurement')
    mean = float(a.mean())
    sd = (0.0 if np.all(a == a[0]) else float(a.std(ddof=1))) if len(a) > 1 else None
    return dict(n=len(a), mean=mean, sd=sd, median=float(np.median(a)),
        q1=float(np.quantile(a,.25)), q3=float(np.quantile(a,.75)),
        cv_pct=100*sd/mean if mean and sd is not None else None, maximum=float(a.max()))


def metric(group, name):
    col, divisor, unit, scope = METRICS[name]
    g = eligible(group)
    if scope == 'timing':
        g = g[g.timing_policy_exclusion.isna()]
    values = g[col] / divisor if col in g else pd.Series(dtype=float)
    result = statistics(values)
    if name in ('auth','signature') and group.secure_boot.eq('integrity_sha256').all():
        result = statistics(pd.Series(dtype=float))
        reason = 'not_applicable_integrity_only'
    elif not result['n']:
        reason = 'no_eligible_measurement'
    elif scope == 'static' and values.dropna().nunique() != 1:
        reason = 'conflicting_static_sizes'
    else:
        reason = None
    if scope == 'static':
        # Static values are build facts; their repeated capture count is not an n
        # for statistical inference. Never average distinct observed sizes.
        result['value'] = float(values.dropna().iloc[0]) if not reason else None
        for key in ['mean','sd','median','q1','q3','cv_pct','maximum']:
            result[key]=None
    result.update(metric=name, column=col, unit=unit, scope=scope, reason=reason)
    return result


def number(value, digits=2):
    return '—' if value is None else f'{value:,.{digits}f}'


def display_metric(result, total, mode='mean_sd'):
    if result['reason']:
        return '—'
    if mode == 'mean_sd':
        text = number(result['mean']) + ' (' + number(result['sd']) + ')'
    elif mode == 'static':
        text = number(result['value'], 0 if result['unit'] == 'B' else 2)
    else:
        text = number(result[mode], 0 if result['unit'] == 'B' else 2)
    if result['scope'] != 'static' and result['n'] != total:
        text += f" [n={result['n']}]"
    return text


def condition(key):
    return ' / '.join(LABELS.get(x, x) for x in key)


def grouped(frame, kind):
    groups = list(frame.groupby(KEYS[kind], dropna=False))
    order = dict(ORDER)
    if kind in ('tls_auth','tls_auth_followup'):
        order.update({name:i for i,name in enumerate(['ecdsa-p256','ecdsa-p384','rsa3072','mldsa65'])})
        order.update(server=0,mutual=1)
    return sorted(groups, key=lambda pair: tuple((order.get(x,999),str(x)) for x in (pair[0] if isinstance(pair[0],tuple) else (pair[0],))))


def loss_tables(item, current):
    """Loss grid: all-attempt outcomes and success-conditioned timing, never imputed."""
    name=item['id']; tables=[]; detail=[]
    losses=sorted(current[LOSS_COLUMN].unique())
    keys=KEYS['network_loss'][:-1]
    groups=list(current.groupby(keys,dropna=False))
    groups.sort(key=lambda pair: (pair[0][0]!='plaintext',
        {'ecdsa-p256':0,'mldsa65':1}.get(pair[0][1],999),
        ORDER.get(pair[0][3],999),str(pair[0])))
    common=('Columns are configured packet loss percentages; 0% is an enabled-impairment reference. '
        'TLS row labels are authentication / key exchange. '
        'Application/verification failures and capture timeouts remain in the denominator; '
        'unsuccessful attempts are not all TLS failures. '
        'The export does not supply observed loss rates or verified-applied network controls. ')
    controls=current.iloc[0]
    common += ('Payload '+str(int(controls.payload_bytes))+' bytes; chunks '+str(int(controls.chunk_bytes))+
        ' bytes; MQTT QoS '+str(int(controls['control__mqtt__qos']))+'. ')
    tls=current.loc[current.transport_mode.eq('tls')]
    if len(tls):
        common += 'All TLS cases use '+str(tls.auth_mode.iloc[0])+' authentication. '
    for suffix,metric_name,caption in [
        ('success',None,'Initial network-loss grid: successful runs / attempted runs.'),
        ('completion','completion','Initial network-loss grid: median completion time of successful runs (s).'),
        ('handshake','loss_handshake','Initial network-loss grid: median TLS handshake time of successful runs (s).')]:
        if suffix=='handshake' and tls.empty:
            continue
        rows=[]
        for key,g in groups:
            if suffix=='handshake' and key[0]=='plaintext':continue
            label='Plaintext' if key[0]=='plaintext' else condition((key[1],key[3]))
            cells=[label]
            for loss in losses:
                cell=g[g[LOSS_COLUMN].eq(loss)]
                if cell.empty:
                    cells.append('—');continue
                n=len(cell);success=int(cell.run_success.eq(True).sum());good=len(eligible(cell))
                audit=dict(table=name+'_'+suffix,condition=label+'; loss='+str(loss),selection=name,
                    loss_percent=float(loss),attempts=n,successes=success,eligible_successes=good,
                    unsuccessful=int(cell.run_success.eq(False).sum()),unknown_outcomes=int(cell.run_success.isna().sum()),
                    invalid_captures=int((~cell.capture_valid.eq(True).fillna(False)).sum()))
                if metric_name is None:
                    cells.append(str(success)+'/'+str(n))
                    detail.append(dict(**audit,metric='success',unit='count',n=n))
                else:
                    r=metric(cell,metric_name)
                    cells.append(display_metric(r,success,'median'))
                    detail.append(dict(**audit,**r))
            rows.append(cells)
        notes=common
        if metric_name:
            notes += ('Medians condition on successful runs and therefore exclude unsuccessful or incomplete attempts. '
                'Read with the success grid; an em dash means no eligible timing. '
                'A bracketed n flags fewer timing observations than successes. '
                'Dispersion and per-cell counts are in metrics.csv. ')
            notes += ('Completion spans TCP-connect start to the application last byte, including TLS/MQTT setup and transfer.'
                if suffix=='completion' else 'Handshake is the device-recorded TLS interval; this is not handshake-success probability.')
        tables.append(dict(id=name+'_'+suffix,caption=caption,
            headers=['Configuration']+[f'{float(x):g}%' for x in losses],
            rows=rows,notes=notes,selections=[name]))
    return tables,detail


def make_tables(spec, selected):
    tables, detail = [], []
    items = {x['id']: x for x in spec['selections']}
    for item in spec['selections']:
        if item['kind'] == 'secure_boot_stack':
            continue
        current = selected[item['id']][1]
        rows = []
        name = item['id']
        kind = item['kind']
        if kind == 'network_loss':
            network_tables, network_details = loss_tables(item, current)
            tables.extend(network_tables); detail.extend(network_details)
            continue
        if kind == 'secure_boot':
            headers = ['Algorithm','Integrity verification ms','Auth. ms','Flash Bytes','Static RAM Bytes','Stack max Bytes','Signature Bytes']
            caption = 'Secure-boot authentication timing and bootloader resources.'
            notes = ('Sizes are in bytes; timings are in milliseconds. '
                     'Stack is the observed maximum during selected-image verification in separate profiling builds. '
                     'Static RAM is .data plus .bss, excluding stack and other reservations. '
                     'Integrity-only has no signature authentication. ')
            identical_ten = True
            stack_id = item.get('stack_selection')
            if stack_id and items[stack_id]['source_commit'] != item['source_commit']:
                raise ValueError('boot timing and stack selections must use the same captured source')
            stack = selected[stack_id][1] if stack_id else current.iloc[0:0]
            for key, group in grouped(current,kind):
                key = key if isinstance(key,tuple) else (key,)
                sg = stack[stack.secure_boot.eq(key[0])]
                n = len(eligible(group)); ns = len(eligible(sg))
                measurements = {m: metric(group,m) for m in ['integrity','auth','boot_flash','boot_ram','signature']}
                measurements['boot_stack'] = metric(sg,'boot_stack')
                identical_ten &= n == 10 and ns == 10 and all(
                    r['reason'] == 'not_applicable_integrity_only' or
                    (not r['reason'] and r['n'] == 10 and
                     (r['scope'] == 'static' or r['sd'] == 0))
                    for r in measurements.values())
                cells = [condition(key), display_metric(measurements['integrity'],n,'mean'),
                    display_metric(measurements['auth'],n,'mean'), display_metric(measurements['boot_flash'],n,'static'),
                    display_metric(measurements['boot_ram'],n,'static'), display_metric(measurements['boot_stack'],ns,'maximum'),
                    display_metric(measurements['signature'],n,'static')]
                rows.append(cells)
                for m,r in measurements.items():
                    detail.append(dict(table=name,condition=condition(key),selection=stack_id if m=='boot_stack' else name,**r))
            notes = (('All recorded values were identical across 10 executions per algorithm '
                      'in each timing and stack campaign. ' if identical_ten else
                      'Timing cells show means; counts and dispersion are retained in metrics.csv. '
                      'The captures do not satisfy the identical-values/10-executions condition. ')
                     + notes + 'Identical recorded values do not establish zero physical variation or independent mailbox freshness.')
        elif kind in ('tls_auth','tls_kex'):
            headers = ['Authentication / mode' if kind=='tls_auth' else 'Key exchange','n','Handshake ms',
                       'App. Flash KiB','Static RAM KiB','Heap max KiB','Workspace max KiB']
            caption = ('TLS authentication' if kind=='tls_auth' else 'TLS key exchange') + ': handshake timing and application resources.'
            notes = ('Handshake is mean (sample SD), measured on the device; n counts eligible current successful captures. '
                     '1 KiB = 1024 bytes. Flash/static RAM are observed application build sizes. '
                     'Heap is the maximum observed FreeRTOS heap usage (including dynamic task stacks); workspace is a separate regional peak. '
                     'Static RAM already contains reserved backing storage. These columns overlap and must not be summed into total RAM. '
                     'Runtime maxima are observed values, not worst-case guarantees.')
            notes += (' Fixed key exchange: '+condition((current.tls_kex.iloc[0],))+'.') if kind=='tls_auth' else (
                ' Fixed authentication: '+condition((current.tls_auth.iloc[0],current.auth_mode.iloc[0]))+'.')
            for key,group in grouped(current,kind):
                key=key if isinstance(key,tuple) else (key,)
                n=len(eligible(group))
                measurements={m:metric(group,m) for m in ['handshake','app_flash','app_ram','heap','workspace']}
                cells=[condition(key),str(n),display_metric(measurements['handshake'],n),
                    display_metric(measurements['app_flash'],n,'static'),display_metric(measurements['app_ram'],n,'static'),
                    display_metric(measurements['heap'],n,'maximum'),display_metric(measurements['workspace'],n,'maximum')]
                rows.append(cells)
                for r in measurements.values():detail.append(dict(table=name,condition=condition(key),selection=name,**r))
        else:
            baseline_id=item['baseline_selection']
            baseline=selected[baseline_id][1]
            if current[KEYS[kind]].drop_duplicates().shape[0] != 1:
                raise ValueError('follow-up table requires exactly one authentication case')
            for col in KEYS[kind]:baseline=baseline[baseline[col].eq(current[col].iloc[0])]
            if baseline.empty:
                raise ValueError('follow-up has no matching original case')
            for col in ['configuration_identity','firmware_identity','git_state_identity','source_commit']:
                if set(baseline[col]) != set(current[col]):
                    raise ValueError('follow-up control mismatch: '+col)
            headers=['Batch','n','Handshake ms','Handshake CV %','Signing ms','Signing CV %','Verify ms']
            caption=condition(tuple(current[c].iloc[0] for c in KEYS[kind])) + ': separate follow-up validation.'
            notes=('Timing cells are mean (sample SD); CV is 100 × SD / mean. Original and follow-up batches are separate. '
                   'Signing/verification aggregates are nested spans, not disjoint costs to add to handshake time. '
                   'The main authentication matrix retains its original per-case sample size.')
            for label,g,selection_id in [('Original',baseline,baseline_id),('Follow-up',current,name)]:
                n=len(eligible(g));measurements={m:metric(g,m) for m in ['handshake','sign','verify']}
                rows.append([label,str(n),display_metric(measurements['handshake'],n),number(measurements['handshake']['cv_pct']),
                    display_metric(measurements['sign'],n),number(measurements['sign']['cv_pct']),display_metric(measurements['verify'],n)])
                for r in measurements.values():detail.append(dict(table=name,condition=label,selection=selection_id,**r))
        used=[name] + ([item['stack_selection']] if item.get('stack_selection') else []) + ([item['baseline_selection']] if item.get('baseline_selection') else [])
        tables.append(dict(id=name,caption=caption,headers=headers,rows=rows,notes=notes,selections=used))
    return tables,detail


def escape_tex(text):
    chars={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_',
           '{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}',
           '—':r'\textemdash{}','×':r'\ensuremath{\times}'}
    return ''.join(chars.get(c,c) for c in str(text))


def latex(table, provenance):
    tid=table['id']
    lines=[r'% Generated by analyse_results.py. Requires booktabs and graphicx.',
           '% Data and selection are frozen in report.json; optional provenance is below.',
           r'\begin{table}[htbp]',r'\centering',r'\small',
           r'\caption{'+escape_tex(table['caption'])+'}',r'\label{tab:pqc-'+tid.replace('_','-')+'}',
           r'\begingroup',r'\setlength{\tabcolsep}{4pt}',
           r'\setbox0=\hbox{\begin{tabular}{l'+'r'*(len(table['headers'])-1)+'}',r'\toprule']
    headers=[]
    for header in table['headers']:
        # Keep units on their own line, avoiding wide single-line headings.
        parts=header.rsplit(' ',1) if header.endswith((' ms',' KiB',' B',' Bytes',' %')) else [header]
        headers.append(r'\shortstack{'+r'\\'.join(escape_tex(p) for p in parts)+'}')
    lines.append(' & '.join(headers)+r' \\')
    lines.append(r'\midrule')
    lines.extend(' & '.join(escape_tex(c) for c in row)+r' \\' for row in table['rows'])
    lines += [r'\bottomrule',r'\end{tabular}}',
        r'\ifdim\wd0>\linewidth\resizebox{\linewidth}{!}{\box0}\else\box0\fi',r'\endgroup',
        r'\par\smallskip',r'\begin{minipage}{\linewidth}\footnotesize',escape_tex(table['notes']),
        r'\end{minipage}',r'\end{table}',
        '% Optional draft provenance. Change the next line to \\iffalse to hide it.',
        r'\iftrue % PROVENANCE: true = draft visible; false = thesis hidden',
        r'\begingroup\footnotesize\par\noindent',r'\textbf{Provenance: '+escape_tex(tid)+r'.}\par']
    for paragraph in provenance:
        lines.append(escape_tex(paragraph)+r'\par')
    lines += [r'\endgroup',r'\fi % END PROVENANCE','']
    return '\n'.join(lines)


def write_csv(path, rows, columns=None):
    columns=columns or sorted({k for row in rows for k in row})
    with Path(path).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(rows)


def contribution_frames(table_item, selection_id, selected, table_id=None):
    """Scope follow-up provenance to its matched case, not the entire matrix."""
    all_rows,current=selected[selection_id]
    if table_item['kind']=='tls_auth_followup' and selection_id==table_item['baseline_selection']:
        focus=selected[table_item['id']][1]
        for col in KEYS['tls_auth_followup']:
            value=focus[col].iloc[0]
            all_rows=all_rows.loc[all_rows[col].eq(value)]
            current=current.loc[current[col].eq(value)]
    if table_item['kind']=='network_loss' and table_id==table_item['id']+'_handshake':
        all_rows=all_rows.loc[all_rows.transport_mode.eq('tls')]
        current=current.loc[current.transport_mode.eq('tls')]
    return all_rows,current


def prepare(spec_path):
    """Read-only preview; publication uses these same selections and statistics."""
    spec = read_spec(spec_path)
    frame,exports=load_inputs(spec)
    selected={item['id']:select(frame,item) for item in spec['selections']}
    used=pd.concat([v[0] for v in selected.values()])
    if used.row_id.duplicated().any():
        raise ValueError('selections overlap; keep each campaign in one selection')
    compact = dict(spec, selections=[i for i in spec['selections'] if i['kind'] not in comparison.RECIPES])
    tables,metrics=make_tables(compact,selected)
    analyses = {}
    for item in spec['selections']:
        if item['kind'] in comparison.RECIPES:
            extra, values, analyses[item['id']] = comparison.analyse(item, selected[item['id']][1], measurements=spec.get('presentation', {}).get('measurements'))
            tables.extend(extra); metrics.extend(values)
    patterns = spec.get('presentation', {}).get('measurements')
    if patterns is not None:
        from fnmatch import fnmatchcase
        available = {m for analysis in analyses.values() for m in analysis['available_measurements']}
        if any(not any(fnmatchcase(m,p) for m in available) for p in patterns):
            raise ValueError('measurement selector has no matching domain metric; inspect available_measurements')
    if any(i['kind'] in comparison.RECIPES for i in spec['selections']) and '*' in spec.get('presentation', {}).get('figures', []):
        spec['presentation']['figures'] = sorted(({r['metric'] for r in metrics if r.get('reported_value') is not None} | set(spec['presentation']['figures'])) - {'*'})
    if len({t['id'] for t in tables}) != len(tables):
        raise ValueError('generated table identifiers collide')
    from framework.analysis_presentation import prepare as prepare_presentation
    prepare_presentation(tables, metrics, spec)
    return dict(specification=spec, exports=exports, selected=selected, tables=tables, metrics=metrics, analyses=analyses)


def build(spec_path, output, *, expected_scientific=None):
    spec=read_spec(spec_path)
    output=Path(output).absolute()
    if _has_symlink(output) or output.exists():
        raise ValueError('choose a fresh non-symlink output directory; existing reports are never overwritten')
    for export in spec['exports']:
        source=result_path(export['path']).resolve()
        if output==source or source in output.parents or output in source.parents:
            raise ValueError('output must be outside source archives')
    prepared=prepare(spec)
    spec = prepared['specification']
    for all_rows, _ in prepared['selected'].values():
        if 'input_path' in all_rows:
            for value in all_rows.input_path.dropna().unique():
                source = result_path(value).resolve()
                if output==source or source in output.parents or output in source.parents:
                    raise ValueError('output must be outside retained capture folders')
    exports,selected,tables,metrics=(prepared[k] for k in ('exports','selected','tables','metrics'))
    report_method = (METHOD if not any(x['kind']=='network_loss' for x in spec['selections']) else
        'Each table defines its summary and eligibility policy. Network outcomes retain all current attempts; '
        'network timing medians condition on successful, valid captures. Full statistics and counts are in metrics.csv.')
    if prepared['analyses']:
        report_method = comparison.METHOD
    inventory=[];observations=[]
    for item in spec['selections']:
        all_rows,current=selected[item['id']]
        all_rows,current = all_rows.drop_duplicates('run_key'), current.drop_duplicates('run_key')
        good=eligible(current)
        record=dict(id=item['id'],kind=item['kind'],source_commit=item['source_commit'],
            all_attempts=len(all_rows),current_attempts=len(current),historical_attempts=len(all_rows)-len(current),
            current_success=int(current.run_success.eq(True).sum()),current_failures=int(current.run_success.eq(False).sum()),
            eligible_captures=len(good),replacement_successes=int(good.attempt_index.gt(1).sum()),
            filters=item['filters'],exports=sorted(current['_export'].unique()),
            cases=current.case_id.nunique(),configuration_identities=sorted(current.configuration_identity.dropna().unique()),
            firmware_identities=sorted(current.firmware_identity.dropna().unique()),
            firmware_sha256=sorted(current.firmware_sha256.dropna().unique()),
            source_state_identities=sorted(current.git_state_identity.dropna().unique()))
        timestamps=pd.to_datetime(current.created_at,utc=True,errors='raise')
        record['first_capture_utc']=timestamps.min().isoformat() if timestamps.notna().any() else None
        record['last_capture_utc']=timestamps.max().isoformat() if timestamps.notna().any() else None
        controls=['target','gateway','workload','payload_bytes','chunk_bytes','tls_kex','tls_auth','auth_mode',
            'secure_boot','energy_enabled','control__mqtt__qos','control__network_configured__enabled']
        if item['kind'] == 'network_loss':
            controls += [LOSS_COLUMN,'control__network_configured__rtt_ms',
                'control__network_configured__rate_kbit','control__network_configured__mtu']
        record['controls']={c:json.loads(current[c].drop_duplicates().to_json(orient='values')) for c in controls if c in current}
        inventory.append(record)
        obscols=['row_id','run_key','run_id','created_at','manifest_sha256','source_commit','case_id','campaign_id','campaign_slot_index',
            'secure_boot','tls_auth','auth_mode','tls_kex',
            'attempt_index','attempt_current','run_success','capture_valid','selected_inputs_valid','failure_stage',
            'configuration_identity','firmware_identity','firmware_sha256','timing_policy_exclusion']
        if item['kind'] == 'network_loss':
            obscols += ['transport_mode','network_condition',LOSS_COLUMN,'execution_outcome',
                'control__network_verified_applied','control__network_observed']
        obscols += ['row_kind', 'input_path', 'execution_outcome']
        obscols = list(dict.fromkeys(c for c in obscols if c in all_rows))
        for r in json.loads(all_rows[obscols].to_json(orient='records')):
            observations.append(dict(selection=item['id'],**r))
    provenance_by_id={}
    items={x['id']:x for x in spec['selections']}
    for table in tables:
        records=[r for r in inventory if r['id'] in table['selections']]
        paragraphs=[]
        table['contributions']=[]
        for r in records:
            all_rows,current=contribution_frames(items[table['selections'][0]],r['id'],selected,table['id'])
            all_rows,current = all_rows.drop_duplicates('run_key'), current.drop_duplicates('run_key')
            good=eligible(current)
            r=dict(r,current_attempts=len(current),eligible_captures=len(good),
                historical_attempts=len(all_rows)-len(current),replacement_successes=int(good.attempt_index.gt(1).sum()))
            table['contributions'].append(dict(selection=r['id'],row_ids=sorted(all_rows.row_id),
                current_captures=len(current),eligible_captures=len(good),historical_attempts=r['historical_attempts'],
                replacement_successes=r['replacement_successes']))
            controls=r['controls']
            paragraphs.append(f"Selection {r['id']}; captured source {(r['source_commit'] or 'multiple/unknown; see audit')[:40]}; "
                f"{r['current_attempts']} current attempts, {r['eligible_captures']} eligible captures, "
                f"{r['historical_attempts']} historical attempts retained in audit, "
                f"{r['replacement_successes']} current successes from replacement attempts.")
            selected_exports=[x for x in exports if x['path'] in r['exports']]
            for e in selected_exports:
                paragraphs.append('Export '+Path(e['path']).name+'; archive SHA-256 '+e['archive_sha256'][:16]+
                    '...; full hashes and capture identities: report.json and observations.csv.')
            visible_controls=['target','workload']
            if r['kind'].startswith('tls_') or r['kind'] == 'network_loss':
                visible_controls+=['payload_bytes','chunk_bytes','control__mqtt__qos','control__network_configured__enabled']
            labels={'target':'target','workload':'workload','payload_bytes':'payload (B)',
                    'chunk_bytes':'chunk (B)','control__mqtt__qos':'MQTT QoS',
                    'control__network_configured__enabled':'impairment'}
            paragraphs.append('Controls: '+ '; '.join(labels[c]+'='+','.join(
                ('enabled' if v else 'disabled') if type(v) is bool else str(v) for v in controls[c])
                for c in visible_controls)+'.')
            if r['kind'] == 'network_loss':
                failures=current.loc[current.run_success.eq(False),'failure_stage'].fillna('unknown').value_counts()
                paragraphs.append('Recorded unsuccessful-attempt stages: '+
                    ', '.join(str(k).replace('_',' ')+' = '+str(v) for k,v in failures.items())+
                    '. These are framework outcome categories, not established causes of packet-loss failure.')
        method = METHOD
        if items[table['selections'][0]]['kind'] == 'secure_boot':
            method = METHOD.replace('Timings: mean (sample SD, n-1).',
                'Timings: means; sample SD and counts are retained in metrics.csv.')
        elif items[table['selections'][0]]['kind'] == 'network_loss':
            method = ('All current attempts remain in success denominators, including capture failures. '
                'Latency medians use only successful, valid captures with verified inputs and valid timing. '
                'Counts, sample SD and quartiles are retained in metrics.csv; no causal or independence claim.')
        if items[table['selections'][0]]['kind'] in comparison.RECIPES:
            method = comparison.METHOD
        paragraphs.append(method)
        provenance_by_id[table['id']]=paragraphs
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.'+output.name+'-',dir=output.parent))
    try:
        (staging/'selection.json').write_text(canonical(spec))
        write_csv(staging/'metrics.csv',metrics)
        write_csv(staging/'observations.csv',observations)
        data_files = []
        for name, analysis in prepared['analyses'].items():
            for frame, data in analysis['frames'].items():
                filename = 'data-' + name + '-' + frame + '.csv'
                # JSON cells retain structured scientific provenance; \N is null.
                with (staging/filename).open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=data['columns'])
                    writer.writeheader()
                    for row in data['rows']:
                        writer.writerow({k: (r'\N' if value is None else json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else ('\\'+value if isinstance(value, str) and value.startswith('\\') else value)) for k, value in row.items()})
                data_files.append(filename)
        methods = {name: {k:v for k,v in analysis.items() if k!='frames'} for name, analysis in prepared['analyses'].items()}
        (staging/'methods.json').write_text(canonical(methods))
        tex_files=[]
        for table in tables:
            name=table['id']
            with (staging/(name+'.csv')).open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(table['headers']);writer.writerows(table['rows'])
            text=latex(table,provenance_by_id[name]);(staging/(name+'.tex')).write_text(text)
            tex_files.append(text)
        preamble=r'''\documentclass[a4paper,10pt]{article}
\usepackage[margin=18mm]{geometry}
\usepackage{booktabs,graphicx}
\begin{document}
'''
        (staging/'preview.tex').write_text(preamble+'\n\\clearpage\n'.join(tex_files)+'\n\\end{document}\n')
        from framework.analysis_presentation import render, html_figures
        figures=render(staging,tables,metrics,spec.get('presentation', {}))
        metadata=dict(schema='pqc-thesis-tables',version=VERSION,specification=spec,exports=exports,
            selections=inventory,method=report_method,tables=tables,provenance=provenance_by_id,figures=figures,
            presentation_sha256=digest(ROOT/'scripts/framework/analysis_presentation.py'),
            analyses=methods, data_files=data_files,
            analysis_sources={p.name:digest(p) for p in sorted((ROOT/'scripts/framework').glob('*.py'))},
            environment=analysis_environment(),
            generator_sha256=digest(__file__),loader_sha256=digest(ROOT/'scripts/framework/archive_table.py'))
        (staging/'report.json').write_text(canonical(metadata))
        body=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Thesis tables</title>',
            '<style>body{font:15px/1.55 system-ui;max-width:1250px;margin:35px auto;padding:0 24px;color:#203746}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#eaf2f3}.scroll{overflow:auto}details{background:#f2f6f7;padding:10px;margin:12px 0}h2{margin-top:35px}a{color:#086d82}</style>',
            '<h1>Experiment analysis</h1><p>'+html.escape(report_method)+'</p>',
            '<p>LaTeX fragments require <code>booktabs</code> and <code>graphicx</code>. Use <code>\\input{table-file.tex}</code>. '
            'Change the marked provenance <code>\\iftrue</code> to <code>\\iffalse</code> in each fragment to hide draft notes. '
            'Measurement definitions and limitations remain with the table.</p>']
        body.append('<nav><strong>Contents</strong><ul>' + ''.join('<li><a href="#'+t['id']+'">'+html.escape(t['caption'])+'</a></li>' for t in tables) + '</ul></nav>')
        for table in tables:
            body+=['<h2 id="'+table['id']+'">'+html.escape(table['caption'])+'</h2><p><a href="'+table['id']+'.tex">LaTeX</a> · <a href="'+table['id']+'.csv">CSV</a></p>',
                '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in table['headers'])+'</tr>',
                *['<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in row)+'</tr>' for row in table['rows']],
                '</table></div><p>'+html.escape(table['notes'])+'</p><details><summary>Draft provenance</summary>'+''.join('<p>'+html.escape(x)+'</p>' for x in provenance_by_id[table['id']])+'</details>']
            body.append(html_figures([f for f in figures if f['table']==table['id']]))
        if data_files:
            body.append('<details><summary>Detailed domain data (CSV; &#92;N means unavailable; nested provenance uses JSON)</summary><ul>' + ''.join('<li><a href="'+name+'">'+name+'</a></li>' for name in data_files) + '</ul></details>')
        body.append('<p><a href="metrics.csv">Full-precision statistics and per-metric counts</a> · <a href="observations.csv">Attempt audit</a> · <a href="report.json">Full provenance</a> · <a href="preview.tex">Standalone LaTeX preview</a></p></html>')
        (staging/'tables.html').write_text('\n'.join(body))
        outputs={p.name:digest(p) for p in sorted(staging.iterdir())}
        (staging/'checksums.json').write_text(canonical(outputs))
        # Recheck inputs after rendering, before publishing the new report.
        load_inputs(spec)
        verify_analysis_inputs(metadata)
        if expected_scientific is not None:
            actual = {p.name:digest(p) for p in staging.iterdir() if p.suffix in ('.csv', '.tex')}
            if actual != expected_scientific:
                raise ValueError('rebuilt scientific CSV/LaTeX differ from the original report')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return metadata


def verify(output, *, verify_sources=True):
    output=Path(output)
    if _has_symlink(output):raise ValueError('symlink report refused')
    hashes=json.loads((output/'checksums.json').read_text())
    if {p.name for p in output.iterdir()} != set(hashes) | {'checksums.json'}:
        raise ValueError('report output inventory changed')
    for name,expected in hashes.items():
        if Path(name).name!=name or _has_symlink(output/name) or digest(output/name)!=expected:
            raise ValueError('report output changed: '+name)
    metadata=json.loads((output/'report.json').read_text())
    if metadata.get('schema')!='pqc-thesis-tables' or metadata.get('version')!=VERSION:
        raise ValueError('unsupported report')
    if verify_sources:
        load_inputs(metadata['specification'])
        verify_analysis_inputs(metadata)
    return metadata


def verify_analysis_inputs(metadata):
    from framework.research_report import verify_dependencies
    for analysis in metadata.get('analyses', {}).values():
        if 'dependencies' in analysis:
            verify_dependencies(analysis['dependencies'])
        else:
            for lineage in analysis['provenance'].values():
                for item in lineage.get('inputs', []):
                    if not item.get('consumed', True):
                        continue
                    path = result_path(item['path'])
                    if _has_symlink(path) or digest(path) != item['sha256']:
                        raise ValueError('analysis evidence changed: ' + str(path))


def analysis_environment():
    import platform
    import matplotlib
    return {'python':platform.python_version(), 'numpy':np.__version__, 'pandas':pd.__version__, 'matplotlib':matplotlib.__version__}
