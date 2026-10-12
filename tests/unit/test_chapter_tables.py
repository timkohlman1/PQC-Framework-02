"""Chapter routing cannot invent evidence or silently change selections."""
import copy

import pandas as pd
import pytest

from framework import chapter_tables as chapter
from framework.research_report import INVENTORY_COLUMNS, OUTCOME_COLUMNS


def prepared():
    routes = {section: [] for section in chapter.SECTIONS}
    routes['kex-timing'] = [{'selection': 'kex', 'conditions': ['hybrid']}]
    rows = [dict(condition=c, capture_class='tls_runtime', evidence_class=e,
                 metric='tls_handshake', unit='us', median=v, n_runs=2, n_observations=2)
            for c, e, v in [('classical', 'classical_e2e', 100), ('hybrid', 'hybrid_e2e', 200),
                             ('hybrid', 'incomplete', None)]]
    frame = pd.DataFrame(rows)
    frames = dict(tls_run_distributions={'columns': list(frame.columns), 'rows': rows},
                  inventory={'columns': INVENTORY_COLUMNS, 'rows': []},
                  completeness={'columns': OUTCOME_COLUMNS, 'rows': []})
    return dict(specification={'presentation': {'chapter_tables': routes}}, selected={'kex': None},
                analyses={'kex': {'frames': frames, 'normalized_comparison': {'conditions': {'classical': {}, 'hybrid': {}}}}})


def test_routes_project_exact_conditions_without_averaging_strata_or_filling_nulls():
    data = prepared()
    original = copy.deepcopy(data)
    result = chapter.collect(data)
    rows = result['kex-timing']['rows']
    assert [r['value'] for r in rows] == [200, None]
    assert rows[1]['reason'] == 'no_eligible_measurements'
    assert len(result) == 20 and data == original
    assert result['energy-secureboot-ota']['rows'][0]['value'] is None
    assert 'D7:' in result['energy-secureboot-ota']['gaps'][0]
    tex = chapter.render('kex-timing', result['kex-timing'])
    assert 'hybrid' in tex and 'incomplete' in tex
    assert '0.2' in tex and 'tab:results-kex-timing' in tex
    assert 'endhead' in tex and 'D3:' in tex


@pytest.mark.parametrize('mutation', ['missing_section', 'bad_selection', 'bad_condition', 'duplicate', 'compact'])
def test_incomplete_ambiguous_or_unknown_routes_fail(mutation):
    data = prepared()
    routes = data['specification']['presentation']['chapter_tables']
    if mutation == 'missing_section': routes.pop('packet-analysis')
    elif mutation == 'bad_selection': routes['kex-timing'][0]['selection'] = 'missing'
    elif mutation == 'bad_condition': routes['kex-timing'][0]['conditions'] = ['typo']
    elif mutation == 'duplicate': routes['kex-timing'] *= 2
    else: data['analyses'] = {}
    with pytest.raises(ValueError): chapter.collect(data)


def test_dataset_summary_preserves_no_capture_and_historical_attempts():
    data = prepared()
    data['specification']['presentation']['chapter_tables']['dataset-summary'] = [{'selection': 'kex'}]
    current = pd.DataFrame([dict(run_key='a', case_id='c', row_kind='retained_capture'),
                            dict(run_key='b', case_id='c', row_kind='campaign_attempt_without_capture')])
    all_rows = pd.concat([current, pd.DataFrame([dict(run_key='old', case_id='c', row_kind='retained_capture')])])
    data['selected']['kex'] = (all_rows, current)
    rows = chapter.collect(data)['dataset-summary']['rows']
    counts = {r['metric']: r['value'] for r in rows}
    assert counts == dict(resolved_cases=1, current_attempts=2, historical_attempts=1, attempts_without_capture=1)


def test_tex_escapes_evidence_labels_and_unavailable_reasons():
    data = {'rows': [dict(condition='a&b_%', metric='raw#metric', value=None, reason='missing_$input')], 'gaps': []}
    tex = chapter.render('baremetal-reference', data)
    assert r'a\&b\_\allowbreak{}\%' in tex
    assert r'raw\#metric' in tex and r'\textsuperscript{*}' in tex


def test_repeated_p95_is_projected_from_the_shared_run_distribution():
    data = prepared()
    data['specification']['presentation']['chapter_tables']['repeated-tls'] = [{'selection': 'kex', 'conditions': ['hybrid']}]
    frame = data['analyses']['kex']['frames']['tls_run_distributions']
    frame['columns'].append('p95')
    frame['rows'][1]['p95'] = 250
    rows = chapter.collect(data)['repeated-tls']['rows']
    assert [(r['statistic'], r['value']) for r in rows] == [('median', 200), ('median', None), ('p95', 250), ('p95', None)]
    assert '(p95)' in chapter.render('repeated-tls', {'rows': rows, 'gaps': []})


def test_duplicate_scalar_cannot_be_silently_combined_in_a_matrix_cell():
    row = dict(condition='a', metric='elapsed', value=10)
    with pytest.raises(ValueError, match='ambiguous'):
        chapter.render('kex-timing', {'rows': [row, row], 'gaps': []})


def test_compact_cells_move_counts_to_notes_and_keep_unique_build_units():
    rows = [dict(analysis='kex', condition='P-256', metric='tls_handshake', unit='us', value=1234567,
                 statistic='median', table='tls_run_distributions', sample_unit='run', n_runs=30, n_observations=30),
            dict(analysis='kex', condition='P-256', metric='flash_section_bytes', unit='bytes', value=262144,
                 statistic='median', table='resource_distributions', sample_unit='unique_build', n_runs=30, n_observations=1)]
    tex = chapter.render('kex-resources', {'rows': rows, 'gaps': []})
    assert '1,234.567' in tex and '256' in tex and 'KiB' in tex
    assert '30 eligible runs per condition' in tex
    assert '1 distinct build/image observations per condition' in tex
    assert r'\newline{\scriptsize' not in tex
    assert r'\dimexpr' in tex and r'\footnotesize' in tex


def test_role_alignment_keeps_hybrid_ecdh_and_kem_separate_and_rejects_collisions():
    def row(metric, value):
        return dict(condition='hybrid', metric='aggregate:' + metric + ':elapsed', unit='us',
                    value=value, statistic='median', table='tls_operation_distributions', sample_unit='run')
    rows = [row('p256_keygen', 1000), row('p384_keygen', None), row('mlkem768_keygen', 2000)]
    tex = chapter.render('kex-timing', {'rows': rows, 'gaps': []})
    assert 'ECDHE keygen' in tex and 'ML-KEM keygen' in tex
    with pytest.raises(ValueError, match='ambiguous'):
        chapter.render('kex-timing', {'rows': rows + [row('p521_keygen', 3000)], 'gaps': []})


def test_outcome_counts_stay_visible_for_reliability_and_failed_conditions():
    rows = [dict(condition='loss 15%', metric=metric, value=value, table='completeness', statistic='count', unit='runs')
            for metric, value in [('included_runs', 10), ('failed_runs', 4), ('unknown_runs', 0)]]
    tex = chapter.render('network-impairment-summary', {'rows': rows, 'gaps': []})
    assert 'Attempts' in tex and 'Failed' in tex and 'loss 15' in tex
    assert r'\newline{\scriptsize' not in tex


def test_unavailable_metric_moves_to_note_without_removing_csv_projection():
    data = prepared()
    rows = chapter.collect(data)['kex-timing']['rows']
    before = copy.deepcopy(rows)
    tex = chapter.render('kex-timing', {'rows': rows, 'gaps': []})
    assert rows == before
    assert 'incomplete' in tex and r'\textemdash{}' in tex


def test_empty_selection_blocks_are_notes_but_failed_conditions_remain_rows():
    def row(selection, condition, value):
        return dict(analysis=selection, condition=condition, metric='ttlb', value=value, unit='us',
                    table='distributions', statistic='median', reason='unavailable' if value is None else None)
    rows = [row('normal', 'success', 1000), row('normal', 'failed_condition', None),
            row('profiling', 'profiling_only', None)]
    tex = chapter.render('secureboot-auth', {'rows': rows, 'gaps': []})
    assert 'failed' in tex and 'profiling only' not in tex
    assert 'unavailable for profiling' in tex


def test_baseline_and_primitive_orientation_and_scaled_cycles():
    rows=[dict(condition='tls_kex=ML_KEM_'+str(n),metric='mlkem_keygen:ML_KEM_'+str(n),table='baremetal_distributions',
        unit='cycles',value=123456789+n,statistic='median',n_runs=10,n_observations=10) for n in (1024,512,768)]
    tex=chapter.render('baremetal-reference',dict(rows=rows,gaps=[]))
    assert 'Measurement & ML-KEM-512 & ML-KEM-768 & ML-KEM-1024' in tex
    assert '123,457.' in tex and 'e+08' not in tex and 'thousand cycles' in tex
    tex=chapter.render('classical-tls-baseline',dict(rows=[dict(condition='P-256',metric='tls_handshake',value=2000,unit='us')],gaps=[]))
    assert 'Measurement & Value' in tex and tex.count('begin{longtable}')==1


def test_timing_and_static_resources_share_one_landscape_condition_row():
    rows=[dict(analysis='a',condition='P-256',metric='tls_handshake',unit='us',value=2000,capture_class='tls_runtime',evidence_class='classical'),
          dict(analysis='a',condition='P-256',metric='ram_static_base_bytes',unit='bytes',value=2048)]
    tex=chapter.render('kex-timing',dict(rows=rows,gaps=[]))
    assert tex.count('P-256 &')==1 and r'\begin{landscape}' in tex
    assert '2 & 2' in tex
