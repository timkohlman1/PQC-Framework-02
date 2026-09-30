"""Docker-side planning and offline reporting for the thesis collection driver."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path

import yaml

from framework.config_resolver import ConfigResolver
from framework.source import capture_git_provenance, capture_submodule_provenance
from framework.timing_dataset import _has_symlink, discover_inputs, export_dataset
from framework.timing_dataset_loader import load_dataset
from framework.timing_summary import leaves

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGNS = (
    'thesis_kex', 'thesis_authentication', 'thesis_repeated_tls',
    'thesis_application', 'thesis_network_rate', 'thesis_network_rtt',
    'thesis_network_loss', 'thesis_network_mtu', 'thesis_energy',
    'secure_boot', 'secure_boot_stack', 'baremetal_benchmark', 'thesis_ota_overhead',
)
GAPS = [
    'Boot/OTA energy and cross-reset stage durations have no supported acquisition boundary.',
    'OTA final candidate-to-image binding remains unconfirmed by the current importer.',
    'Simultaneous whole-system RAM, disjoint Total Crypto and handshake-only bytes are not inferred.',
    'Ten reset-separated attempts are pilot defaults, not a power calculation or an independence claim.',
]


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collection_path(value):
    path = Path(os.path.abspath(ROOT / value))
    if not path.is_relative_to(ROOT / 'results') or path == ROOT / 'results' or _has_symlink(path):
        raise ValueError('collection must be a non-symlink directory below results/')
    return path


def source_identity():
    source = capture_git_provenance(ROOT)
    if not source['git_status_available'] or not source['git_commit'] or (source['git_dirty'] and not source['source_state_sha256']):
        raise ValueError('source identity unavailable')
    source.pop('git_branch', None)
    modules = capture_submodule_provenance(ROOT)
    if not modules['available']:
        raise ValueError('submodule identity unavailable')
    # Hash dirty submodule content as well as its HEAD; a dirty flag is insufficient.
    for entry in modules['entries']:
        if entry['checkout_state'] == 'uninitialized':
            raise ValueError('required submodule is uninitialized: ' + entry['path'])
        entry['source'] = capture_git_provenance(ROOT / entry['path'])
        entry['source'].pop('git_branch', None)
        if not entry['source']['git_status_available'] or (entry['source']['git_dirty'] and not entry['source']['source_state_sha256']):
            raise ValueError('submodule content identity unavailable')
    return {'repository': source, 'submodules': modules}


def annotations(value):
    if not isinstance(value, dict) or set(value) - {'energy', 'network'}:
        raise ValueError('annotations support only energy and network')
    for key, fields in [('energy', {'electrical_boundary', 'evidence_reference'}),
                        ('network', {'client_ip', 'evidence_reference'})]:
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, dict) or set(item) != fields or any(not isinstance(v, str) or not v.strip() for v in item.values()):
            raise ValueError(key + ' annotation requires all nonempty fields')
        if key == 'network' and ipaddress.ip_address(item['client_ip']).version != 4:
            raise ValueError('network client must be IPv4')
    return value


def plan(output, repetitions=10, only=None, include_ota=True):
    if type(repetitions) is not int or not 1 <= repetitions <= 1000:
        raise ValueError('repetitions must be 1..1000')
    names = list(only or CAMPAIGNS)
    if not names or len(set(names)) != len(names) or set(names) - set(CAMPAIGNS):
        raise ValueError('select unique supported campaign names')
    output = collection_path(output)
    if output.exists():
        raise ValueError('plan requires a new collection directory')
    output.mkdir(parents=True, mode=0o700)
    (output / 'profiles').mkdir()
    resolver = ConfigResolver(ROOT)
    steps, hashes = [], {}
    from framework.campaign_executor import ExecutionPolicy, validate_policy_against_case
    for name in names:
        original, data = resolver.load_campaign(name)
        data['execution']['repetitions'] = repetitions
        # Explicitly preserve instrumented stack runs separately from normal timing.
        source = output / 'profiles' / (name + '.yaml')
        source.write_text(yaml.safe_dump(data, sort_keys=False))
        cases = resolver.expand_campaign(source)
        policy = ExecutionPolicy.from_mapping(data['execution'])
        for case in cases:
            validate_policy_against_case(policy=policy, case=case, resolver=resolver)
        relative = source.relative_to(ROOT).as_posix()
        hashes[relative] = sha(source)
        steps.append({'id': name, 'kind': 'campaign', 'source': relative,
                      'conditions': len(cases), 'repetitions': repetitions,
                      'attempts': len(cases) * repetitions})
    if include_ota:
        steps.append({'id': 'ota_lifecycle', 'kind': 'ota', 'scenario_tests': 8,
                      'scope': 'application update, rollback, migration and negative/recovery checks; diagnostic build excluded'})
    value = {'schema': 'pqc-thesis-collection', 'version': 1,
             'steps': steps, 'source': source_identity(), 'profile_hashes': hashes,
             'planned_campaign_attempts': sum(s.get('attempts', 0) for s in steps),
             'limitations': GAPS, 'independent_runs': False}
    write(output / 'plan.json', value)
    (output / 'plan.sha256').write_text(sha(output / 'plan.json') + '\n')
    write(output / 'annotations.json', annotations(read(ROOT / 'configs/analysis/thesis_collection_annotations.json')))
    print(json.dumps({'collection': str(output), 'planned_campaign_attempts': value['planned_campaign_attempts'],
                      'ota_scenario_tests': 8 if include_ota else 0, 'hardware_executed': False}))
    return value


def check(output):
    output = collection_path(output)
    annotations(read(output / 'annotations.json'))
    if (output / 'plan.sha256').read_text().strip() != sha(output / 'plan.json'):
        raise ValueError('collection plan hash changed')
    value = read(output / 'plan.json')
    if value.get('schema') != 'pqc-thesis-collection' or value.get('version') != 1:
        raise ValueError('unsupported collection plan')
    for name, digest in value['profile_hashes'].items():
        path = ROOT / name
        if not path.is_relative_to(output / 'profiles') or _has_symlink(path) or sha(path) != digest:
            raise ValueError('frozen campaign profile changed')
    if source_identity() != value['source']:
        raise ValueError('source/submodule state changed; keep the collection checkout unchanged or start a new collection')
    return value


def analysis_specs(name, profile):
    """Predeclared one-factor strata; never choose conditions from observed success."""
    matrix = profile.get('matrix', {})
    kex = matrix.get('tls_kex', [profile['fixed'].get('tls_kex', 'secp256r1')])
    auth = matrix.get('tls_auth', [profile['fixed'].get('tls_auth', 'rsa3072')])
    modes = matrix.get('auth_mode', [profile['fixed'].get('auth_mode', 'server')])
    result = []
    def add(label, field, values, baseline, filters, domains, sections, security='key_establishment'):
        result.append(dict(id=label, field=field, values=values, baseline=baseline, filters=filters,
                           domains=domains, sections=sections, security_domain=security))
    if name == 'thesis_kex':
        add(name, 'tls_kex', kex, 'secp256r1', {}, ['timing','resources','tls'],
            ['dataset-summary','classical-tls-baseline','kex-timing','kex-resources','kex-network-application'])
    elif name in ('thesis_authentication', 'thesis_repeated_tls', 'thesis_energy'):
        domains = ['timing','resources','tls'] + (['energy'] if name == 'thesis_energy' else [])
        sections = ['energy-tls-mqtt'] if name == 'thesis_energy' else ['repeated-tls'] if name == 'thesis_repeated_tls' else ['cert-family']
        for group in kex:
            for mode in modes:
                add(f'{name}_cert_{group}_{mode}', 'tls_auth', auth, 'rsa3072',
                    {'tls_kex':group,'auth_mode':mode}, domains, sections, 'endpoint_authentication')
        if len(modes) > 1:
            for group in kex:
                for cert in auth:
                    add(f'{name}_mode_{group}_{cert}', 'auth_mode', modes, 'server',
                        {'tls_kex':group,'tls_auth':cert}, domains, ['auth-mode'] if name == 'thesis_authentication' else ['repeated-tls'], 'endpoint_authentication')
        if len(kex) > 1:
            for cert in auth:
                for mode in modes:
                    add(f'{name}_kex_{cert}_{mode}', 'tls_kex', kex, 'secp256r1',
                        {'tls_auth':cert,'auth_mode':mode}, domains, sections)
    elif name == 'thesis_application':
        for group in kex:
            for chunk in matrix['workload.transfer.chunk_bytes']:
                add(f'application_payload_{group}_{chunk}', 'payload_bytes', matrix['workload.transfer.payload_bytes'], 4096,
                    {'tls_kex':group,'chunk_bytes':chunk}, ['timing','resources'], ['ready-metrics2'])
            for size in matrix['workload.transfer.payload_bytes']:
                add(f'application_chunk_{group}_{size}', 'chunk_bytes', matrix['workload.transfer.chunk_bytes'], 128,
                    {'tls_kex':group,'payload_bytes':size}, ['timing','resources'], ['ready-metrics2'])
    elif name.startswith('thesis_network_'):
        for group in kex:
            add(name+'_'+group, 'network_condition', matrix['network_condition'], 'trial_reference',
                {'tls_kex':group}, ['timing','network'], ['network-impairment-summary','packet-analysis'])
    elif name in ('secure_boot', 'secure_boot_stack'):
        add(name, 'secure_boot', matrix['secure_boot'], 'ecdsa_p256', {}, ['resources','secure_boot'],
            ['classical-secureboot-baseline','secureboot-auth'], 'firmware_authentication')
    elif name == 'baremetal_benchmark':
        add(name, 'tls_kex', kex, 'ML_KEM_512', {}, ['baremetal','resources'], ['baremetal-reference'])
    elif name == 'thesis_ota_overhead':
        for algorithm in matrix['secure_boot']:
            add(name+'_'+algorithm, 'firmware_mode', matrix['firmware_mode'], 'dual_bank_no_ota',
                {'secure_boot':algorithm}, ['resources','secure_boot'], ['ota-capability'], 'firmware_authentication')
    return result


def make_spec(design, dataset):
    field = design['field']
    declared = {
        'tls_kex': ['controls.tls.mode','controls.tls.key_exchange_group'],
        'tls_auth': ['controls.tls.certificate_profile','controls.tls.server_signature_algorithm'],
        'auth_mode': ['controls.tls.mode','controls.tls.authentication'],
        'secure_boot': ['controls.choices.secure_boot'],
        'firmware_mode': ['controls.firmware.firmware_mode','controls.firmware.ota_enabled'],
        'network_condition': ['controls.network_configured.' + axis for axis in ('rate_kbit','rtt_ms','loss_percent','mtu')],
    }
    known = set().union(*(leaves(r.get('controls', {})) for r in dataset.runs))
    prefix = 'controls.profile_hashes.' + field + ':'
    treatment = [field] + [v for v in declared.get(field, []) if v in known]
    treatment += sorted(k for k in known if k.startswith(prefix))
    if field == 'network_condition':
        # Only the named axis is a treatment; other network axes remain controls.
        axis = next(a for a in ('rate','rtt','loss','mtu') if 'network_'+a in design['id'])
        key = {'rate':'rate_kbit','rtt':'rtt_ms','loss':'loss_percent','mtu':'mtu'}[axis]
        treatment = [v for v in treatment if not v.startswith('controls.network_configured.') or v.endswith('.'+key)]
    # Boot-only and primitive reference workloads have no payload transfer.
    not_applicable = {}
    if design['id'].startswith(('secure_boot','baremetal_benchmark','thesis_ota_overhead')):
        not_applicable = {k:'This workload has no application payload-transfer measurement.' for k in ('payload_bytes','chunk_bytes')}
    return {'conditions': {str(v):{field:v} for v in design['values']}, 'baseline':str(design['baseline']),
            'filters':design['filters'], 'treatment':treatment, 'not_applicable':not_applicable,
            'independent_runs':False, 'seed':20260930, 'resamples':2000,
            'evidence_policy':'stm32_st67_tls'}


def network_selection(dataset, annotation):
    if not annotation:
        return {}
    from framework.timing_dataset import _artifact, read_json
    selected = {}
    for run in dataset.runs:
        if run['selected_input_status'] != 'verified':
            continue
        root = Path(run['input_path'])
        manifest = read(root / 'manifest.json')
        raw, _ = _artifact(root, manifest, 'resolved_case_snapshot', [])
        if raw is None:
            continue
        mqtt = read_json(raw).get('effective_non_secret_parameters', {}).get('mqtt', {})
        selected[run['run_key']] = {'client_ip':annotation['client_ip'],
            'server_ip':mqtt.get('orchestration', {}).get('host'), 'server_port':mqtt.get('broker', {}).get('port'),
            'window':{'kind':'retained_flow'}, 'evidence_reference':annotation['evidence_reference']}
    return selected


def report(output):
    output = collection_path(output)
    value = check(output)
    notes = annotations(read(output / 'annotations.json'))
    reports = output / 'reports'
    reports.mkdir(exist_ok=True)
    index = 1
    while (reports / f'{index:04d}').exists():
        index += 1
    destination = reports / f'{index:04d}'
    destination.mkdir(mode=0o700)
    (destination / 'datasets').mkdir()
    write(destination / 'annotations.json', notes)
    specification = {'version':1, 'analyses':[]}
    gaps = list(GAPS)
    if not notes.get('energy'):
        gaps.append('Electrical boundary/reference unspecified; energy comparisons remain unavailable.')
    if not notes.get('network'):
        gaps.append('Device IPv4 attribution unspecified; packet comparisons remain unavailable.')
    for step in value['steps']:
        name = step['id']
        raw = output / ('campaigns' if step['kind'] == 'campaign' else 'ota') / name
        if not raw.exists():
            gaps.append(name+': no collected evidence')
            continue
        try:
            paths, _ = discover_inputs(results_root=raw)
        except ValueError as exc:
            gaps.append(name+': '+str(exc))
            continue
        dataset_path = destination / 'datasets' / name
        export_dataset(output=dataset_path, run_dirs=paths)
        data = load_dataset(dataset_path, verify_inputs=True)
        if step['kind'] == 'ota':
            # Keep scenario families distinct; do not promote delivery into transition success.
            for family, sections in [('application',['application-update']), ('migration',['bootloader-recovery']), ('negative',['application-update'])]:
                runs = []
                for run in data.runs:
                    path = run['input_path']
                    actual = 'migration' if 'migration' in path else 'negative' if any(k in path for k in ('invalid_candidate','rollback','unconfirmed')) else 'application'
                    if actual == family:
                        runs.append(run)
                if runs:
                    conditions = {r['run_key'][:16]:{'run_key':r['run_key']} for r in runs}
                    specification['analyses'].append({'id':'ota_'+family, 'dataset':str(dataset_path),
                        'spec':{'conditions':conditions,'baseline':next(iter(conditions)), 'independent_runs':False},
                        'domains':['ota'], 'sections':sections, 'security_domain':'firmware_authentication'})
            continue
        profile = yaml.safe_load((ROOT / step['source']).read_text())
        for design in analysis_specs(name, profile):
            item = {k:design[k] for k in ('id','domains','sections','security_domain')}
            item.update(dataset=str(dataset_path), spec=make_spec(design, data))
            if 'network' in design['domains']:
                item['network'] = network_selection(data, notes.get('network'))
            if 'energy' in design['domains']:
                item['energy'] = {'boundaries':{r['run_key']:notes['energy'] for r in data.runs}} if notes.get('energy') else {}
            specification['analyses'].append(item)
    write(destination / 'collection-gaps.json', {'limitations':gaps, 'collection_state':read(output/'state.json') if (output/'state.json').exists() else None})
    if not specification['analyses']:
        raise ValueError('no captured runs to report; see '+str(destination/'collection-gaps.json'))
    selection_path = destination / 'selection.json'
    write(selection_path, specification)
    from framework.research_report import specification as parse, build, verify
    selected, sources = parse(selection_path)
    snapshot = build(selected, [*sources, destination/'annotations.json', output/'plan.json', destination/'collection-gaps.json'], destination/'snapshot')
    verify(snapshot)
    write(output/'latest-report.json', {'snapshot':str(snapshot), 'limitations':gaps})
    print('Verified report: '+str(snapshot/'report/notebook.html'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','check','report'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--repetitions', type=int, default=10)
    parser.add_argument('--only', nargs='+', choices=CAMPAIGNS)
    parser.add_argument('--skip-ota', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'plan':
            plan(args.output, args.repetitions, args.only, not args.skip_ota)
        elif args.action == 'check':
            check(args.output)
            print('Frozen collection plan and source verified.')
        else:
            report(args.output)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print('Thesis collection: '+str(exc))
        return 2
