"""Selectable wolfSSL TLS controls, identities and rejecting inert settings."""
from pathlib import Path
import sys
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from framework import tls_optimizations as options
from framework.config_resolver import ConfigResolver, ResolutionError
from framework.build import _write_tls_algorithm_selection


def resolve(tmp_path, **settings):
    data = yaml.safe_load((ROOT/'configs/campaigns/mldsa_memory_mutual.yaml').read_text())
    data['matrix'].pop('mldsa_memory_mode')
    data['fixed'].update(tls_kex='ML_KEM_768', **settings)
    path = tmp_path/'profile.yaml'; path.write_text(yaml.safe_dump(data))
    resolver = ConfigResolver(ROOT)
    case, = resolver.expand_campaign(path)
    return case, resolver.to_legacy_bundle(case, resolve_secrets=False)


@pytest.mark.parametrize('key,value', [(k,v) for k,vs in options.OPTIONS.items() for v in vs])
def test_every_control_reaches_identity_bundle_and_compiler(tmp_path,key,value):
    settings = {key:value}
    if key == 'tls_small_stack' and not value: settings['tls_task_stack_bytes'] = 49152
    if settings.get('tls_task_stack_bytes',8192) >= 49152: settings['tls_heap_bytes']=131072
    case,bundle = resolve(tmp_path,**settings)
    path,selected = _write_tls_algorithm_selection(bundle,tmp_path/'build')
    assert case['choices'][key] == bundle['experiment']['mqtt']['tls'][key] == selected[key] == value
    assert options.cmake({key:value}).strip() in path.read_text()
    original,_ = resolve(tmp_path)
    assert original['provenance']['firmware_identity'] != case['provenance']['firmware_identity']


@pytest.mark.parametrize('settings', [dict(mlkem_small_code='true'), dict(tls_small_stack=0),
    dict(tls_task_stack_bytes=12288), dict(tls_task_stack_bytes=49152), dict(tls_heap_bytes=140000), dict(tls_small_stack=False),
    dict(tls_auth='ecdsa-p256',mldsa_small_code=True)])
def test_invalid_or_inert_controls_fail_closed(tmp_path,settings):
    with pytest.raises(ResolutionError): resolve(tmp_path,**settings)


def test_small_code_and_small_memory_are_independent_and_defaults_do_not_migrate(tmp_path):
    case,bundle = resolve(tmp_path)
    assert not set(options.DEFAULTS).intersection(case['choices'])
    _, selected = _write_tls_algorithm_selection(bundle,tmp_path/'build')
    assert {k:selected[k] for k in options.DEFAULTS} == options.DEFAULTS
    assert options.resolve({'mlkem_small_code':True},mlkem=True)['mlkem_encapsulate_small_mem'] is False
    for args in [dict(transport='plaintext'),dict(application=False),dict(mlkem=False)]:
        with pytest.raises(ValueError): options.resolve({'mlkem_small_code':True},**args)


def test_app_and_boot_dependency_settings_are_separate():
    # The opt-in macros are confined to application targets; no boot build input.
    source=(ROOT/'scripts/framework/build.py').read_text()
    boot=(ROOT/'scripts/framework/wolfboot.py').read_text() if (ROOT/'scripts/framework/wolfboot.py').exists() else ''
    assert 'tls_optimizations.cmake(options)' in source
    assert 'tls_optimizations' not in boot
