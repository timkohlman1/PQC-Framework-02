"""Campaign management uses disposable configs, never live laboratory files."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml
from framework import campaign_editor as editor
from framework.campaign_menu import apply_value, fields, value_for

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repository(tmp_path):
    shutil.copytree(ROOT / 'configs', tmp_path / 'configs')
    profiles = tmp_path / 'results/profiles'
    profiles.mkdir(parents=True)
    for name in ('baseline.yaml', 'thesis_authentication.yaml'):
        shutil.copy2(tmp_path / 'configs/campaigns' / name, profiles / name)
    return tmp_path


def test_read_view_and_noop_save_preserve_original_bytes(repository):
    path = repository / 'results/profiles/thesis_authentication.yaml'
    before = path.read_bytes()
    loaded = editor.operate(repository, {'action': 'load', 'profile': path.name})
    assert path.read_bytes() == before
    assert 'rsa3072' in loaded['options']['tls_auth']
    result = editor.operate(repository, {**loaded, 'action': 'save'})
    assert result['conditions'] == 10 and result['attempts'] == 300
    assert path.read_bytes() == before


def test_create_edit_validate_and_delete_without_editing_components(repository):
    component = repository / 'configs/tls_auth/rsa3072.yaml'
    before = component.read_bytes()
    loaded = editor.load(repository)
    data = loaded['data']
    data['id'] = 'custom_campaign'
    data['matrix'] = {'tls_auth': ['ecdsa-p256', 'rsa3072']}
    result = editor.operate(repository, {'action': 'save', 'profile': 'custom_campaign.yaml', 'data': data})
    path = repository / 'results/profiles/custom_campaign.yaml'
    assert result['conditions'] == 2
    old = path.read_bytes()
    data['execution']['repetitions'] = 3
    result = editor.operate(repository, {'action': 'save', 'profile': path.name, 'sha256': hashlib.sha256(old).hexdigest(), 'data': data})
    assert result['attempts'] == 6
    assert component.read_bytes() == before
    with pytest.raises(ValueError, match='exact filename'):
        editor.operate(repository, {'action': 'delete', 'profile': path.name, 'sha256': result['sha256'], 'confirm': 'yes'})
    editor.operate(repository, {'action': 'delete', 'profile': path.name, 'sha256': result['sha256'], 'confirm': path.name})
    assert not path.exists() and component.read_bytes() == before


def test_invalid_save_and_conflicting_edit_do_not_change_campaign(repository):
    loaded = editor.load(repository, 'baseline.yaml')
    path = repository / 'results/profiles/baseline.yaml'
    before = path.read_text()
    loaded['data']['execution']['repetitions'] = 0
    with pytest.raises(ValueError, match='repetitions'):
        editor.operate(repository, {**loaded, 'action': 'save'})
    assert path.read_text() == before
    loaded['data']['execution']['repetitions'] = 2
    path.write_text(before + '# external change\n')
    with pytest.raises(ValueError, match='changed on disk'):
        editor.operate(repository, {**loaded, 'action': 'save'})
    assert path.read_text().endswith('# external change\n')


def test_save_preserves_unedited_sections_and_unknown_metadata(repository):
    path = repository / 'results/profiles/baseline.yaml'
    path.write_text('# retained heading\n' + path.read_text() + 'notes:\n  custom: keep  # inline note\n')
    loaded = editor.load(repository, path.name)
    loaded['data']['execution']['repetitions'] = 2
    editor.operate(repository, {**loaded, 'action': 'save'})
    text = path.read_text()
    assert text.startswith('# retained heading\n')
    assert 'notes:\n  custom: keep  # inline note\n' in text
    assert yaml.safe_load(text) == loaded['data']


def test_profiles_paths_duplicate_ids_and_incompatible_combinations(repository):
    loaded = editor.load(repository)
    data = loaded['data']
    for name in ('../targets/evil.yaml', '/tmp/evil.yaml'):
        with pytest.raises(ValueError, match='filename'):
            editor.operate(repository, {'action': 'save', 'profile': name, 'data': data})
    (repository / 'results/profiles/link.yaml').symlink_to(repository / 'results/profiles/baseline.yaml')
    with pytest.raises(ValueError, match='symlink'):
        editor.load(repository, 'link.yaml')
    data['id'] = 'baseline'
    with pytest.raises(ValueError, match='ID already'):
        editor.operate(repository, {'action': 'save', 'profile': 'duplicate.yaml', 'data': data})
    data['id'] = 'custom'
    data['fixed'].update(mqtt_transport='plaintext', auth_mode='mutual')
    with pytest.raises(ValueError, match='plaintext'):
        editor.operate(repository, {'action': 'save', 'profile': 'bad.yaml', 'data': data})
    assert not (repository / 'results/profiles/bad.yaml').exists()


def test_editor_factor_checkbox_single_matrix_and_default(repository):
    loaded = editor.load(repository)
    data = copy.deepcopy(loaded['data'])
    factor = next(f for f in fields(loaded['options']) if f[2] == ['tls_auth'])
    apply_value(data, factor, ['ecdsa-p256', 'rsa3072'])
    assert 'tls_auth' not in data['fixed']
    assert value_for(data, factor) == ['ecdsa-p256', 'rsa3072']
    apply_value(data, factor, ['rsa3072'])
    assert data['fixed']['tls_auth'] == 'rsa3072' and 'tls_auth' not in data['matrix']
    apply_value(data, factor, None)
    assert value_for(data, factor) is None


def test_memory_mode_editor_saves_fixed_matrix_and_omission(repository):
    loaded = editor.load(repository, name='memory_options')
    data = loaded['data']
    before = copy.deepcopy(data)
    factor = next(f for f in fields(loaded['options']) if f[2] == ['mldsa_memory_mode'])
    assert factor[4] == [None, 'default', 'verify_small', 'sign_small', 'both_small']
    assert value_for(data, factor) is None
    apply_value(data, factor, None)
    assert data == before
    data['fixed'].update(tls_auth='mldsa65', auth_mode='mutual')
    apply_value(data, factor, ['both_small'])
    saved = editor.operate(repository, {'action': 'save', 'profile': 'memory_options.yaml', 'data': data})
    assert saved['conditions'] == 1
    loaded = editor.load(repository, 'memory_options.yaml')
    assert value_for(loaded['data'], factor) == 'both_small'
    apply_value(loaded['data'], factor, ['default', 'verify_small', 'sign_small', 'both_small'])
    saved = editor.operate(repository, {**loaded, 'action': 'save'})
    assert saved['conditions'] == 4
    assert editor.load(repository, 'memory_options.yaml')['data']['matrix']['mldsa_memory_mode'] == factor[4][1:]


@pytest.mark.parametrize('auth,role,mode', [('ecdsa-p256','server','verify_small'),
    ('mldsa65','server','sign_small'), ('mldsa65','server','both_small')])
def test_memory_mode_editor_rejects_inapplicable_choices_without_saving(repository, auth, role, mode):
    data = editor.load(repository, name='invalid_memory')['data']
    data['fixed'].update(tls_auth=auth, auth_mode=role, mldsa_memory_mode=mode)
    with pytest.raises(ValueError, match='ML-DSA|mutual authentication'):
        editor.operate(repository, {'action':'save', 'profile':'invalid_memory.yaml', 'data':data})
    assert not (repository/'results/profiles/invalid_memory.yaml').exists()


def test_all_existing_campaigns_validate_without_writes(repository):
    for path in (repository / 'configs/campaigns').glob('*.yaml'):
        data = editor.load(repository, template=path.name)['data']
        result = editor.operate(repository, {'action': 'validate', 'data': data})
        assert result['conditions'] > 0


def test_blank_profile_does_not_require_templates(repository):
    for path in (repository / 'configs/campaigns').glob('*.yaml'):
        path.unlink()
    loaded = editor.load(repository)
    result = editor.operate(repository, {'action': 'save', 'profile': 'new_campaign.yaml', 'data': loaded['data']})
    assert result['conditions'] == 1


def test_readonly_preview_cannot_write_campaign(repository):
    loaded = editor.load(repository, 'baseline.yaml')
    path = repository / 'results/profiles/baseline.yaml'
    original = path.read_bytes()
    result = editor.operate(repository, {'action': 'preview', 'data': loaded['data']})
    assert yaml.safe_load(result['yaml']) == loaded['data']
    assert path.read_bytes() == original


def test_external_change_during_validation_is_not_overwritten(repository, monkeypatch):
    loaded = editor.load(repository, 'baseline.yaml')
    path = repository / 'results/profiles/baseline.yaml'
    loaded['data']['execution']['repetitions'] = 2
    original_validate = editor.validate
    def changed(root, data, directory):
        result = original_validate(root, data, directory)
        path.write_text(path.read_text() + '# concurrent external editor\n')
        return result
    monkeypatch.setattr(editor, 'validate', changed)
    with pytest.raises(ValueError, match='changed during validation'):
        editor.operate(repository, {**loaded, 'action': 'save'})
    assert path.read_text().endswith('# concurrent external editor\n')
    assert yaml.safe_load(path.read_text())['execution']['repetitions'] == 1


def test_template_copy_and_profile_crud_never_modify_templates(repository):
    templates = repository / 'configs/campaigns'
    before = {p.name: p.read_bytes() for p in templates.glob('*.yaml')}
    listed = editor.operate(repository, {'action': 'templates'})['templates']
    assert {t['template'] for t in listed} == set(before)
    loaded = editor.operate(repository, {'action': 'load', 'template': 'thesis_authentication.yaml', 'name': 'my_auth'})
    assert loaded['data']['id'] == 'my_auth' and loaded['profile'] is None
    assert loaded['data']['queue_profile'] == {'template': 'thesis_authentication.yaml',
        'template_sha256': hashlib.sha256(before['thesis_authentication.yaml']).hexdigest()}
    result = editor.operate(repository, {**loaded, 'action': 'save', 'profile': 'my_auth.yaml'})
    assert result['attempts'] == 300
    edited = editor.load(repository, 'my_auth.yaml')
    edited['data']['execution']['repetitions'] = 2
    result = editor.operate(repository, {**edited, 'action': 'save'})
    assert result['attempts'] == 20
    editor.operate(repository, {'action': 'delete', 'profile': 'my_auth.yaml', 'sha256': result['sha256'], 'confirm': 'my_auth.yaml'})
    assert before == {p.name: p.read_bytes() for p in templates.glob('*.yaml')}


def test_blank_is_independent_of_baseline_and_template_names_do_not_conflict(repository):
    template = repository / 'configs/campaigns/baseline.yaml'
    template.write_text('this is not a valid campaign')
    # Removing the local fixture allows using the same name as a tracked template.
    (repository / 'results/profiles/baseline.yaml').unlink()
    loaded = editor.load(repository, name='baseline')
    assert loaded['data']['queue_profile']['template'] is None
    assert loaded['data']['matrix'] == {} and loaded['data']['execution']['repetitions'] == 1
    editor.operate(repository, {**loaded, 'action': 'save', 'profile': 'baseline.yaml'})
    assert template.read_text() == 'this is not a valid campaign'


@pytest.mark.parametrize('name', ['', '../escaped', 'name with spaces', '/tmp/escaped'])
def test_creation_requires_valid_personal_name(repository, name):
    with pytest.raises(ValueError, match='profile name'):
        editor.load(repository, name=name)
