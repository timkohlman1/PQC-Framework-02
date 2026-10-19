import copy
import pytest
from framework.mldsa_sampling import extract_mldsa_sampling
from framework.timing_metrics import _fields


def records():
    lines = [
        'PQC_TLS_EVENT_BUFFER iteration=3 handshake=7 dropped=0 overflow=0 truncated=0 incomplete=0 invalid_sequence_count=0',
        'PQC_MLDSA_SAMPLING_BUFFER schema=1 iteration=3 handshake=7 count=1 capacity=4 dropped=0',
        'PQC_MLDSA_SAMPLING schema=1 index=0 event_sequence=2 backend=wolfcrypt_software attempts=3 rejected=2 accepted=1 aborted=0 result=0',
        'PQC_TLS_EVENT name=mldsa65_sign sequence=2 completed=1 result_available=1 result=0 start_us=100 end_us=450',
    ]
    return [dict(marker=_fields(line)[0],fields=_fields(line)[1],ref={'record':i}) for i,line in enumerate(lines)]


@pytest.mark.parametrize("algorithm", ["mldsa44", "mldsa65"])
def test_sampling_counts_join_exact_sign_event_and_context(algorithm):
    r=records(); r[3]["fields"]["name"] = algorithm+"_sign"; row=extract_mldsa_sampling(r)[0]
    assert row['validity']=='valid' and row['rejected']==2 and row['attempts']==3
    assert row['iteration']=='3' and row['handshake']=='7' and row['duration_us']==350
    other=copy.deepcopy(r)
    other[0]['fields']['iteration']=other[1]['fields']['iteration']='4'
    other[2]['fields'].update(attempts='1',rejected='0')
    rows=extract_mldsa_sampling(r+other)
    assert [v['rejected'] for v in rows]==[2,0]


@pytest.mark.parametrize('index,key,value,reason',[
    (1,'dropped','1','sampling_buffer_incomplete'),
    (1,'schema','2','unsupported_sampling_schema'),
    (1,'handshake','9','sampling_context_mismatch'),
    (2,'attempts','4','sampling_count_identity'),
    (2,'rejected','-1','invalid_unsigned_count'),
    (2,'attempts',str(2**32),'count_out_of_range'),
    (2,'event_sequence','9','expected_one_software_call_per_sign_event'),
    (2,'index','1','sampling_index_mismatch'),
    (3,'result','-1','signing_outcome_mismatch'),
    (3,'completed','0','signing_outcome_mismatch'),
    (0,'overflow','1','tls_hierarchy_incomplete'),
])
def test_bad_evidence_is_unavailable(index,key,value,reason):
    r=records();r[index]['fields'][key]=value;row=extract_mldsa_sampling(r)[0]
    assert row['validity']=='unavailable' and row['reason']==reason and row['rejected'] is None


def test_historical_missing_and_error_before_loop_are_distinct():
    r=records();old=extract_mldsa_sampling([r[0],r[3]])[0]
    assert old['reason']=='sampling_not_recorded' and old['rejected'] is None
    r[2]['fields'].update(attempts='0',rejected='0',accepted='0',aborted='0',result='-132')
    r[3]['fields']['result']='-132';row=extract_mldsa_sampling(r)[0]
    assert row['validity']=='valid' and row['attempts']==0 and row['result']==-132
