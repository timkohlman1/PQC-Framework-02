"""Selection and presentation policy using explicitly synthetic observations."""
import copy
from pathlib import Path

import pytest

from framework import analysis_workspace as workspace
from framework.analysis_presentation import prepare, figure_rows, validate
from framework.thesis_tables import make_tables
from test_thesis_tables import frame, item, loss_frame


def test_figure_values_are_the_table_statistics_and_missing_is_not_zero():
    data = frame()
    spec = {'selections': [item()], 'presentation': {'figures': ['handshake', 'app_ram']}}
    tables, metrics = make_tables(spec, {'tls_auth': (data, data)})
    prepare(tables, metrics, spec)
    rows = figure_rows(tables, metrics, spec['presentation'])
    timing = next(r for r in rows if r['metric'] == 'handshake')
    assert timing['value'] == 2 and timing['statistic'] == 'mean'
    assert timing['high'] - timing['value'] == pytest.approx(2 ** .5)
    assert timing['uncertainty'].startswith('sample SD')
    missing = next(r for r in rows if r['metric'] == 'app_ram')
    assert missing['value'] is None and missing['reason'] == 'no_eligible_measurement'
    assert tables[0]['rows'][0][2] == '2.00 (1.41)'


def test_loss_figures_preserve_attempt_denominator_and_success_conditioning():
    data = loss_frame()
    spec = {'selections': [item('network_loss')], 'presentation': {'figures': ['success', 'completion']}}
    tables, metrics = make_tables(spec, {'network_loss': (data, data)})
    prepare(tables, metrics, spec)
    rows = figure_rows(tables, metrics, spec['presentation'])
    outcomes = next(r for r in rows if r['metric'] == 'success')
    assert outcomes['value'] == .5 and outcomes['attempts'] == 2
    timing = next(r for r in rows if r['metric'] == 'completion')
    assert timing['n'] == 1 and timing['statistic'] == 'median'
    assert timing['value'] == 2


def test_presentation_changes_labels_without_changing_scientific_values():
    data = frame()
    options = {'figures': ['handshake'], 'labels': {'ML-DSA-65 / mutual': 'PQ mutual'}}
    spec = {'selections': [item()], 'presentation': options}
    tables, metrics = make_tables(spec, {'tls_auth': (data, data)})
    before = copy.deepcopy(metrics)
    prepare(tables, metrics, spec)
    assert tables[0]['rows'][0][0] == 'PQ mutual'
    assert figure_rows(tables, metrics, options)[0]['label'] == 'PQ mutual'
    assert all(all(row[k] == original[k] for k in original) for row, original in zip(metrics, before))
    with pytest.raises(ValueError, match='names must match'):
        prepare(tables, metrics, dict(spec, presentation={'labels': {'typo': 'x'}}))


@pytest.mark.parametrize('options', [{'width_inches': 0}, {'width_inches': float('nan')},
    {'figures': ['handshake', 'handshake']}, {'labels': {'a': ''}}, {'unknown': True}])
def test_invalid_presentation_refused(options):
    with pytest.raises(ValueError):
        validate(options)


def test_draft_freezes_hash_source_and_count_without_manual_metadata(tmp_path, monkeypatch):
    export = tmp_path / 'export'; export.mkdir(); (export / 'archive.json').write_text('{}')
    monkeypatch.setattr(workspace, 'load_inputs', lambda spec: (frame(), []))
    spec = workspace.draft(['export'], [dict(id='auth', kind='tls_auth', filters={'campaign_id': 'auth'})], directory=tmp_path)
    selection = spec['selections'][0]
    assert selection['source_commit'] == 'a' * 40 and selection['expected_current_runs'] == 2
    assert spec['exports'][0]['archive_sha256'] == workspace.digest(export / 'archive.json')
    assert spec['presentation']['figures'] == ['handshake']
    destination = tmp_path / 'selection.json'
    workspace.save_selection(spec, destination)
    assert workspace.read_spec(destination) == spec
    with pytest.raises(FileExistsError):
        workspace.save_selection(spec, destination)
    with pytest.raises(ValueError, match='outside source'):
        workspace.save_selection(spec, export / 'selection.json')


def test_catalogue_keeps_invalid_exports_visible(tmp_path, monkeypatch):
    for name in ['good', 'bad']:
        (tmp_path / name).mkdir(); (tmp_path / name / 'archive.json').write_text('{}')
    def load(path):
        if path.name == 'bad':
            raise ValueError('archive table hash mismatch')
        return frame()
    monkeypatch.setattr(workspace, 'load_archive', load)
    rows = workspace.catalogue(tmp_path)
    assert rows[0]['status'] == 'invalid' and 'hash mismatch' in rows[0]['error']
    assert rows[1]['current_attempts'] == 2


def test_draft_refuses_mixed_sources_and_empty_selection(tmp_path, monkeypatch):
    (tmp_path / 'archive.json').write_text('{}')
    data = frame(); data.loc[1, 'source_commit'] = 'b' * 40
    monkeypatch.setattr(workspace, 'load_inputs', lambda spec: (data, []))
    request = dict(id='auth', kind='tls_auth', filters={'campaign_id': 'auth'})
    with pytest.raises(ValueError, match='exactly one'):
        workspace.draft([tmp_path], [request])
    with pytest.raises(ValueError, match='choose exports'):
        workspace.draft([], [request])


def test_plaintext_loss_selection_has_no_invented_handshake_figure(tmp_path, monkeypatch):
    (tmp_path / 'archive.json').write_text('{}')
    data = loss_frame(); data['transport_mode'] = 'plaintext'
    data['tls_kex'] = data['tls_auth'] = data['auth_mode'] = 'not_applicable'
    # The same export may also contain an unrelated TLS campaign.
    import pandas as pd
    other = frame(); other['campaign_id'] = 'other'
    monkeypatch.setattr(workspace, 'load_inputs', lambda spec: (pd.concat([data, other]), []))
    spec = workspace.draft([tmp_path], [dict(id='loss', kind='network_loss', filters={'campaign_id': 'auth'})])
    assert spec['presentation']['figures'] == ['completion', 'success']
    from framework.thesis_tables import select
    selected = select(data, spec['selections'][0])
    tables, metrics = make_tables(spec, {'loss': selected})
    prepare(tables, metrics, spec)
    assert {t['id'] for t in tables} == {'loss_success', 'loss_completion'}


def test_catalogue_accepts_imported_captures_without_queue_history(tmp_path, monkeypatch):
    export=tmp_path/'retained';export.mkdir();(export/'archive.json').write_text('{}')
    data=frame().drop(columns=['attempt_current'])
    monkeypatch.setattr(workspace,'load_archive',lambda path:data)
    row=workspace.catalogue(tmp_path)[0]
    assert row['status']=='outputs_verified'
    assert row['current_attempts']==2 and row['history_rows']==0
