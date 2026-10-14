from pathlib import Path
import sys
import yaml
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework.config_resolver import ConfigResolver, ResolutionError
from framework.build import _write_tls_algorithm_selection


@pytest.mark.parametrize('role,count',[('server',2),('mutual',4)])
def test_memory_options_have_distinct_firmware_and_explicit_build_settings(tmp_path,role,count):
    resolver=ConfigResolver(ROOT)
    cases=resolver.expand_campaign('mldsa_memory_'+role)
    assert len(cases)==count
    assert len({c['provenance']['firmware_identity'] for c in cases})==count
    for c in cases:
        bundle=resolver.to_legacy_bundle(c,resolve_secrets=False)
        mode=c['choices']['mldsa_memory_mode']
        assert bundle['experiment']['mqtt']['tls']['mldsa_memory_mode']==mode
        path,selected=_write_tls_algorithm_selection(bundle,tmp_path/role/mode)
        assert selected['mldsa_verify_small_mem']==(mode in ('verify_small','both_small'))
        assert selected['mldsa_sign_small_mem']==(mode in ('sign_small','both_small'))
        assert 'set(PQC_MLDSA_VERIFY_SMALL_MEM '+('ON' if selected['mldsa_verify_small_mem'] else 'OFF')+')' in path.read_text()


@pytest.mark.parametrize('auth,role,mode',[('ecdsa-p256','server','verify_small'),('mldsa65','server','sign_small'),('mldsa65','mutual','unknown')])
def test_invalid_options_cannot_be_silently_ignored(tmp_path,auth,role,mode):
    d=yaml.safe_load((ROOT/'configs/campaigns/mldsa_memory_mutual.yaml').read_text())
    d['fixed'].update(tls_auth=auth,auth_mode=role);d['matrix']['mldsa_memory_mode']=[mode]
    p=tmp_path/'invalid.yaml';p.write_text(yaml.safe_dump(d))
    with pytest.raises(ResolutionError):
        ConfigResolver(ROOT).expand_campaign(p)


def test_existing_campaign_does_not_acquire_a_new_choice():
    assert all('mldsa_memory_mode' not in c['choices'] for c in ConfigResolver(ROOT).expand_campaign('tls_authentication'))
