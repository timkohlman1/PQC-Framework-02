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
    return tmp_path


def test_read_view_and_noop_save_preserve_original_bytes(repository):
    path = repository / 'configs/campaigns/thesis_authentication.yaml'
    before = path.read_bytes()
    loaded = editor.operate(repository, {'action': 'load', 'profile': path.name})
    assert path.read_bytes() == before
    assert 'rsa3072' in loaded['options']['tls_auth']
    result = editor.operate(repository, {**loaded, 'action': 'save'})
    assert result['conditions'] == 8 and result['attempts'] == 80
    assert path.read_bytes() == before


def test_create_edit_validate_and_delete_without_editing_components(repository):
    component = repository / 'configs/tls_auth/rsa3072.yaml'
    before = component.read_bytes()
    loaded = editor.load(repository)
    data = loaded['data']
    data['id'] = 'custom_campaign'
    data['matrix'] = {'tls_auth': ['ecdsa-p256', 'rsa3072']}
    result = editor.operate(repository, {'action': 'save', 'profile': 'custom_campaign.yaml', 'data': data})
    path = repository / 'configs/campaigns/custom_campaign.yaml'
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
    path = repository / 'configs/campaigns/baseline.yaml'
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
    path = repository / 'configs/campaigns/baseline.yaml'
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
    (repository / 'configs/campaigns/link.yaml').symlink_to(repository / 'configs/campaigns/baseline.yaml')
    with pytest.raises(ValueError, match='symlink'):
        editor.load(repository, 'link.yaml')
    data['id'] = 'baseline'
    with pytest.raises(ValueError, match='ID already'):
        editor.operate(repository, {'action': 'save', 'profile': 'duplicate.yaml', 'data': data})
    data['id'] = 'custom'
    data['fixed'].update(mqtt_transport='plaintext', auth_mode='mutual')
    with pytest.raises(ValueError, match='plaintext'):
        editor.operate(repository, {'action': 'save', 'profile': 'bad.yaml', 'data': data})
    assert not (repository / 'configs/campaigns/bad.yaml').exists()


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


def test_all_existing_campaigns_validate_without_writes(repository):
    for path in (repository / 'configs/campaigns').glob('*.yaml'):
        data = editor.load(repository, path.name)['data']
        result = editor.operate(repository, {'action': 'validate', 'data': data})
        assert result['conditions'] > 0


def test_new_campaign_still_works_after_all_campaign_files_deleted(repository):
    for path in (repository / 'configs/campaigns').glob('*.yaml'):
        path.unlink()
    loaded = editor.load(repository)
    result = editor.operate(repository, {'action': 'save', 'profile': 'new_campaign.yaml', 'data': loaded['data']})
    assert result['conditions'] == 1


def test_readonly_preview_cannot_write_campaign(repository):
    loaded = editor.load(repository, 'baseline.yaml')
    path = repository / 'configs/campaigns/baseline.yaml'
    original = path.read_bytes()
    result = editor.operate(repository, {'action': 'preview', 'data': loaded['data']})
    assert yaml.safe_load(result['yaml']) == loaded['data']
    assert path.read_bytes() == original


def test_external_change_during_validation_is_not_overwritten(repository, monkeypatch):
    loaded = editor.load(repository, 'baseline.yaml')
    path = repository / 'configs/campaigns/baseline.yaml'
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
