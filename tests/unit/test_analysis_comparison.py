"""Selection/projection policies for the unified workspace, synthetic data only."""
import copy
import json
import pandas as pd
import pytest
from framework import analysis_comparison as comparison
from framework import analysis_workspace as workspace
from framework.analysis_presentation import figure_rows
from test_timing_summary import data


def test_conditions_are_explicit_and_no_controls_are_waived():
    dataset = data()
    spec = comparison.comparison_for(dataset, group_by=['tls_kex'])
    assert spec['baseline'] == 'tls_kex=base'
    assert spec['treatment'] == [] and not spec['independent_runs']
    assert 'not_applicable' not in spec
    with pytest.raises(ValueError, match='known scalar'):
        comparison.comparison_for(dataset, group_by=['missing'])
    with pytest.raises(ValueError, match='baseline'):
        comparison.comparison_for(dataset, group_by=['tls_kex'], baseline='missing')


def test_current_selection_keeps_standalone_and_does_not_promote_unknown_campaign_attempt():
    frame = pd.DataFrame(dict(attempt_current=[True,False,None,None], campaign_manifest_path=['x','x',None,'x']))
    assert list(comparison.current_rows(frame).index) == [0,2]


def test_partial_repeated_capture_filter_is_rejected():
    frame = pd.DataFrame(dict(row_id=['r:1','r:2'], run_key=['r','r'], row_kind=['handshake','handshake'],
        attempt_current=[True,True], iteration_id=[1,2], source_commit=['a'*40]*2))
    item = dict(id='tls', kind='tls', expected_current_runs=1, source_commit='a'*40, filters={'iteration_id':1})
    with pytest.raises(ValueError, match='complete runs'):
        comparison.select(frame,item)


def test_descriptive_median_with_no_quartiles_has_no_fabricated_error_bar():
    row = dict(table='t', metric='ram', condition='c', reported_value=4, reported_statistic='median',
        q1=None,q3=None,n=1,unit='bytes',sample_unit='unique_build',n_runs=4)
    result = figure_rows([], [row], {'figures':['ram']})[0]
    assert result['value']==4 and result['low'] is None and result['uncertainty']=='none'
    assert result['sample_unit']=='unique_build' and result['n_runs']==4


def test_generic_recipe_validation_and_file_identifiers():
    with pytest.raises(ValueError, match='multiple domains'):
        comparison.validate({'kind':'tls','domains':['tls','energy'],'comparison':{}})
    assert set(comparison.RECIPES['comparison']) == set(comparison.DOMAINS)
    assert set(r['recipe'] for r in workspace.recipes()) == workspace.KINDS
    assert comparison.identifier('a/b') != comparison.identifier('a?b')
    assert '/' not in comparison.identifier('../../plot')


def test_projected_conditions_remain_stratified_and_failed_deltas_stay_null(monkeypatch):
    from framework.timing_summary import summarise
    dataset=data();dataset.metadata['inputs']=[];dataset.runs[2]['controls']['fixed']=2
    frames, spec=summarise(dataset,comparison.comparison_for(dataset,group_by=['tls_kex'],treatment=['tls_kex']))
    monkeypatch.setattr(comparison,'dataset_for',lambda _:dataset)
    monkeypatch.setattr(comparison,'analyse_dataset',lambda *a:(dataset,frames,spec,{}))
    tables,metrics,analysis=comparison.analyse(dict(id='t',kind='timing',comparison=spec),None, measurements=['tls_handshake'])
    value=next(r for r in metrics if r['metric']=='tls_handshake' and r['condition_id']=='tls_kex=base')
    assert value['reported_value']==5 and value['n_runs']==2
    delta=next(t for t in tables if t['id']=='t_differences')
    assert all(r[2]=='—' for r in delta['rows'])
    assert any('conflicting_control' in r[-1] for r in delta['rows'])


def test_labels_captions_and_table_choice_preserve_statistic():
    from framework.analysis_presentation import prepare
    tables=[dict(id='a',caption='original',headers=['Condition','Median'],rows=[['c','4']],selections=['s']),
            dict(id='b',caption='other',headers=['Condition','Median'],rows=[['d','5']],selections=['s'])]
    metrics=[dict(table='a',condition='c',metric='ram',unit='bytes',scope='run',n=2,reported_statistic='median',reported_value=4),
             dict(table='b',condition='d',metric='ram',unit='bytes',scope='run',n=2,reported_statistic='median',reported_value=5)]
    spec=dict(selections=[dict(id='s',kind='resources')],presentation={'tables':['a'],'captions':{'a':'Memory'},'labels':{'c':'Reference'},'figures':['ram']})
    prepare(tables,metrics,spec)
    assert len(tables)==len(metrics)==1
    assert tables[0]['caption']=='Memory' and tables[0]['rows']==[['Reference','4']]
    assert metrics[0]['reported_value']==4 and figure_rows(tables,metrics,spec['presentation'])[0]['label']=='Reference'


def test_unverified_campaign_inventory_cannot_define_current_attempts():
    frame=pd.DataFrame(dict(row_id=['r'],run_key=['r'],row_kind=['retained_capture'],attempt_current=[True],
        campaign_manifest_path=['/record'],campaign_manifest_valid=[False],source_commit=['a'*40]))
    item=dict(id='t',kind='timing',filters={'source_commit':'a'*40},source_commit='a'*40,expected_current_runs=1)
    with pytest.raises(ValueError,match='inventory is not finalized'):
        comparison.select(frame,item)
