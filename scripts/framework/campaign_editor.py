"""Validated campaign CRUD for the Docker helper; component profiles stay read-only."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile

import yaml
from framework.config_resolver import ConfigResolver, PROFILE_DIRS
from framework.campaign_executor import ExecutionPolicy, validate_policy_against_case

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')
from framework.tls_optimizations import OPTIONS as TLS_OPTIONS
FACTOR_CHOICES = {
    **TLS_OPTIONS,
    'mldsa_memory_mode': ['default', 'verify_small', 'sign_small', 'both_small'],
    'auth_mode': ['server', 'mutual'],
    'mqtt_transport': ['tls', 'plaintext'],
    'firmware_mode': ['single_bank', 'dual_bank_no_ota', 'dual_bank_ota'],
    'standby_signing_keys': [0, 1, 2],
    'boot_stack_profiling': [False, True],
    'boot_uart_diagnostics': [False, True],
}

PROFILE_DIRECTORY = 'results/profiles'
TEMPLATE_DIRECTORY = 'configs/campaigns'


def path_for(root, name, *, template=False):
    directory = TEMPLATE_DIRECTORY if template else PROFILE_DIRECTORY
    base = Path(root) / directory
    relative = Path(name)
    if not relative.suffix:
        relative = relative.with_suffix('.yaml')
    if relative.is_absolute() or relative.suffix not in {'.yaml', '.yml'} or any(
            not NAME.fullmatch(part) for part in (*relative.parts[:-1], relative.stem)):
        raise ValueError(f'use a profile filename within {directory} (letters, numbers, _ or -)')
    path = base / relative
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('symlink campaign paths are not supported')
    return path


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@contextmanager
def editor_lock(root):
    from framework.run_queue import owned_path
    folder = owned_path(Path(root).resolve(), 'results/campaign-editor')
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = owned_path(Path(root).resolve(), folder / 'editor.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield folder


def options(root):
    resolver = ConfigResolver(root)
    result = {}
    for domain, directory in PROFILE_DIRS.items():
        result[domain] = []
        for path in sorted((Path(root) / 'configs' / directory).glob('*.yaml')):
            if path.is_symlink():
                continue
            try:
                profile = resolver.load_profile(domain, path.stem)
                result[domain].append(profile.profile_id)
            except ValueError:
                continue
    for name, directory, loader in (
        ('broker', 'services/mqtt_broker', lambda name: resolver.load_service('mqtt_broker', name)),
        ('energy', 'instruments/energy', lambda name: resolver.load_instrument('energy', name)),
    ):
        result[name] = []
        for path in sorted((Path(root) / 'configs' / directory).glob('*.yaml')):
            if path.is_symlink():
                continue
            try:
                loader(path.stem)
                result[name].append(path.stem)
            except ValueError:
                continue
    return {**result, **FACTOR_CHOICES}


def templates(root):
    result = []
    for path in sorted((Path(root) / TEMPLATE_DIRECTORY).rglob('*')):
        if path.suffix not in {'.yaml', '.yml'} or not path.is_file():
            continue
        name = path.relative_to(Path(root) / TEMPLATE_DIRECTORY).as_posix()
        try:
            path_for(root, name, template=True)
            _, data = ConfigResolver(root).load_campaign(path)
            result.append({'template': name, 'description': data.get('description', '')})
        except (ValueError, OSError, yaml.YAMLError):
            continue
    return {'templates': result}


def load(root, profile=None, *, template=None, name=None):
    available = options(root)
    if profile and template:
        raise ValueError('choose a profile or a template, not both')
    if profile or template:
        path = path_for(root, profile or template, template=bool(template))
        text = path.read_bytes().decode('utf-8')
        data = yaml.safe_load(text)
    else:
        # A blank profile has the required execution scaffold and one case;
        # it never inherits a campaign template or its matrix/analysis settings.
        def choose(key, preferred):
            return preferred if preferred in available[key] else next(iter(available[key]), '')
        data = {
            'schema_version': 1, 'profile_type': 'campaign', 'id': 'new_profile',
            'target': choose('target', 'stm32l4r5_st67'), 'gateway': choose('gateway', 'pqc_gateway1'),
            'workload': choose('workload', 'ready_metrics'),
            'services': {'experiment_broker': choose('broker', 'experiment_gateway1'),
                         'reporting_broker': choose('broker', 'reporting_gateway1')},
            'fixed': {**{key: choose(key, value) for key, value in {
                'tls_kex': 'secp256r1', 'tls_auth': 'ecdsa-p256', 'secure_boot': 'integrity_sha256',
                'network_condition': 'baseline'}.items()}, 'auth_mode': 'server'},
            'matrix': {}, 'execution': {'repetitions': 1, 'reset_between_runs': 'hardware_reset',
                'build': 'once_per_firmware_identity', 'flash': 'once_per_firmware_identity',
                'experiment_broker': 'reuse_if_compatible', 'reporting_broker': 'always_available',
                'condition': 'retain_within_condition', 'evidence': 'per_run'},
        }
        text = yaml.safe_dump(data, sort_keys=False)
    if not isinstance(data, dict) or data.get('profile_type') != 'campaign':
        raise ValueError('the selected file is not a campaign mapping')
    for section in ('fixed', 'matrix', 'execution', 'services', 'instruments', 'analysis_baselines', 'queue_profile'):
        if section in data and not isinstance(data[section], dict):
            raise ValueError(f'campaign {section} must be a mapping')
    if profile is None:
        if name is not None and (not isinstance(name, str) or not NAME.fullmatch(name)):
            raise ValueError('profile name must use letters, numbers, _ or -')
        data['id'] = name or 'new_profile'
        data['queue_profile'] = {'template': template, 'template_sha256': sha(text) if template else None}
    return {'profile': profile, 'data': data, 'sha256': sha(text) if profile else None,
            'yaml': text if profile else yaml.safe_dump(data, sort_keys=False), 'options': available}


def validate(root, data, directory):
    if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not NAME.fullmatch(data['id']):
        raise ValueError('campaign ID must use letters, numbers, _ or -')
    if not isinstance(data.get('execution'), dict):
        raise ValueError('execution must be a mapping')
    repetitions = data['execution'].get('repetitions')
    if type(repetitions) is not int or not 1 <= repetitions <= 1000:
        raise ValueError('repetitions must be an integer from 1 to 1000')
    matrix = data.get('matrix', {})
    if not isinstance(matrix, dict) or any(not isinstance(v, list) or not v for v in matrix.values()):
        raise ValueError('each matrix factor must contain at least one value')
    count = math.prod(len(v) for v in matrix.values())
    if count > 10000:
        raise ValueError('campaign editor supports at most 10000 expanded conditions')
    resolver = ConfigResolver(root)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        path = Path(temporary) / 'campaign.yaml'
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        _, checked = resolver.load_campaign(path)
        policy = ExecutionPolicy.from_mapping(checked['execution'])
        cases = resolver.expand_campaign(path)
        for case in cases:
            validate_policy_against_case(policy=policy, case=case, resolver=resolver)
    return {'conditions': len(cases), 'repetitions': repetitions, 'attempts': len(cases) * repetitions}


def render_changes(original, before, after):
    """Retain untouched top-level YAML sections verbatim, including their comments."""
    if before == after:
        return original
    node = yaml.compose(original)
    edits = []
    found = set()
    for key, value in node.value:
        name = key.value
        found.add(name)
        if name in after and before.get(name) == after[name]:
            continue
        start, end = key.start_mark.index, value.end_mark.index
        replacement = yaml.safe_dump({name: after[name]}, sort_keys=False) if name in after else ''
        if isinstance(value, yaml.ScalarNode) or (end < len(original) and original[end] == '\n'):
            replacement = replacement.rstrip('\n')
        # Keep full-line explanatory comments within sections that are rewritten.
        comments = [line for line in original[start:end].splitlines() if line.lstrip().startswith('#')]
        if comments:
            replacement = '\n'.join(comments) + '\n' + replacement
        edits.append((start, end, replacement))
    result = original
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    for name in after:
        if name in found:
            continue
        result = result.rstrip() + '\n' + yaml.safe_dump({name: after[name]}, sort_keys=False)
    # Exotic aliases/merge syntax must not silently produce different semantics.
    if yaml.safe_load(result) != after:
        raise ValueError('cannot preserve this YAML layout safely; simplify aliases/merge syntax before editing')
    return result


def operate(root, request):
    action = request['action']
    if action == 'preview':
        return {'yaml': yaml.safe_dump(request['data'], sort_keys=False)}
    if action == 'templates':
        return templates(root)
    if action == 'load':
        return load(root, request.get('profile'), template=request.get('template'), name=request.get('name'))
    with editor_lock(root) as directory:
        if action == 'validate':
            return validate(root, request['data'], directory)
        path = path_for(root, request['profile'])
        expected = request.get('sha256')
        original = path.read_bytes().decode('utf-8') if path.exists() else None
        if expected is None:
            if original is not None:
                raise ValueError('profile already exists; choose another filename')
        elif original is None or sha(original) != expected:
            raise ValueError('profile changed on disk; reopen it before editing or deleting')
        if action == 'delete':
            if expected is None or request.get('confirm') != request['profile']:
                raise ValueError('profile deletion requires its exact filename')
            path.unlink()
            return {'profile': request['profile'], 'deleted': True}
        if action != 'save':
            raise ValueError('unknown campaign editor action')
        data = request['data']
        result = validate(root, data, directory)
        for other in (Path(root) / PROFILE_DIRECTORY).rglob('*'):
            if other == path or other.suffix not in {'.yaml', '.yml'} or not other.is_file() or other.is_symlink():
                continue
            try:
                existing = yaml.safe_load(other.read_text())
                if isinstance(existing, dict) and existing.get('id') == data['id']:
                    raise ValueError('profile ID already belongs to ' + other.name)
            except yaml.YAMLError:
                continue
        text = render_changes(original, yaml.safe_load(original), data) if original else yaml.safe_dump(data, sort_keys=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, path.stat().st_mode & 0o777 if original is not None else 0o644)
            current = path.read_bytes().decode('utf-8') if path.exists() else None
            if (expected is None and current is not None) or (expected is not None and (current is None or sha(current) != expected)):
                raise ValueError('profile changed during validation; reopen it before saving')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {**result, 'profile': request['profile'], 'saved': True, 'sha256': sha(text)}
