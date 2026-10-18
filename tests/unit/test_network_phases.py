import copy
import pytest
from framework.network_phases import PHASES,extract_network_phases


def records():
    header=dict(marker='PQC_NETWORK_PHASES',context='network_phases',ref={'record':1},
                fields=dict(schema='1',count='7',errors='0',clock='TIM2',counter_hz='1000000',timestamp_origin='application_timebase_start'))
    return [header]+[dict(marker='PQC_NETWORK_PHASE',context='network_phases',ref={'record':i+2},
        fields=dict(schema='1',phase=name,state='2',start_us=str(10*i),end_us=str(10*i+5),result='0')) for i,name in enumerate(PHASES)]


def test_historical_absence_is_not_zero_and_failed_phase_is_still_timed():
    assert extract_network_phases([])==[]
    r=records();r[4]['fields']['result']='-1'
    phases=extract_network_phases(r)
    assert phases[3]['result']==-1 and phases[3]['duration_us']==5
    assert phases[3]['source_record']=={'record':5}


@pytest.mark.parametrize('mutation',['missing','duplicate','context','header_context','clock','backward','overlap','errors','width','unknown'])
def test_malformed_phase_trace_cannot_supply_shading(mutation):
    r=records()
    if mutation=='missing':r.pop()
    elif mutation=='duplicate':r[-1]=copy.deepcopy(r[1])
    elif mutation=='context':r[1]['context']='uart'
    elif mutation=='header_context':r[0]['context']='uart'
    elif mutation=='clock':r[0]['fields']['clock']='DWT'
    elif mutation=='backward':r[2]['fields']['end_us']='9'
    elif mutation=='overlap':r[2]['fields']['start_us']='4'
    elif mutation=='errors':r[0]['fields']['errors']='1'
    elif mutation=='width':r[1]['fields']['end_us']=str(2**64)
    elif mutation=='unknown':r[1]['fields']['state']='3'
    with pytest.raises(ValueError):extract_network_phases(r)
