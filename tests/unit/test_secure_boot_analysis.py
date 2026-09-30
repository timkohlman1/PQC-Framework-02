"""A7 synthetic boot observations: no hardware success asserted."""
import copy
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts', ROOT/'tests', ROOT/'tests/unit'):
    sys.path.insert(0, str(p))
from framework.secure_boot_analysis import decode_boot, image_layout, extract_secure_boot, summarise_secure_boot, control_problems
from framework.timing_metrics import _fields
from framework.timing_dataset import export_dataset, DatasetError
from framework.timing_dataset_loader import load_dataset
from framework.run_evidence import register_artifact
from test_resource_analysis import synthetic_elf
from timing_dataset_support import make_run, logical, rm2_records, reseal


def boot_texts(algorithm='ecdsa_p256'):
    return [
        f'PQC_SECURE_BOOT_PROFILE schema=1 mailbox_version=8 signature_algorithm={algorithm}',
        f'PQC_SECURE_BOOT schema=1 mailbox_version=8 mailbox_status=present verification_type=integrity_sha256 measurement_valid=1 cycles=80000 result=0 hclk_hz=80000000 signature_algorithm={algorithm}',
        f'PQC_SECURE_BOOT schema=1 mailbox_version=8 mailbox_status=present verification_type=signature_authenticity measurement_valid=1 cycles=160000 result=0 hclk_hz=80000000 signature_algorithm={algorithm}',
        'PQC_SECURE_BOOT_VERIFICATION schema=1 mailbox_version=8 boundary=selected_image_integrity_start_to_authenticity_end measurement_valid=1 cycles=250000 hclk_hz=80000000 selected_image_valid=1 selected_image_part=0 selected_image_fw_size_bytes=24',
        'PQC_SECURE_BOOT_IMAGE schema=1 mailbox_version=8 identity_kind=wolfboot_verified_image_content_sha256 image_sha256='+ 'a'*64 +' image_part=0 image_fw_size_bytes=24',
        'PQC_SECURE_BOOT_HANDOFF schema=1 mailbox_version=8 origin_kind=1 reset_origin_to_handoff_us_high=0 reset_origin_to_handoff_us_low=4000 bridge_counter_hz=1000000 bridge_counter_bits=16 bridge_status=1',
        'PQC_SECURE_BOOT_TOTAL schema=1 mailbox_version=8 boundary=hal_init_entry_to_hal_prepare_boot measurement_valid=1 elapsed_us_high=0 elapsed_us_low=4000 clock_domain=reset_origin_lptim2_dwt_bridge',
    ]


def decoded(texts):
    return [dict(marker=_fields(t)[0], fields=_fields(t)[1], context='secure_boot', ref={'record':i}) for i,t in enumerate(texts)]


def signed_image():
    return b'WOLF'+struct.pack('<I',24)+struct.pack('<HH',0x20,8)+bytes(8)+bytes([255])*12+bytes(24)


def fixture(tmp_path, *, negative=False, records=None):
    run=make_run(tmp_path/'run',choices={'secure_boot':'ecdsa_p256'},records=[*rm2_records(),*[logical(t,context='secure_boot') for t in (records or boot_texts())]])
    image=signed_image(); (run/'signed.bin').write_bytes(image); (run/'wolfboot.elf').write_bytes(synthetic_elf())
    p=run/'run-provenance.json';d=json.loads(p.read_text());d['records']['firmware']['sha256']=hashlib.sha256(image).hexdigest();p.write_text(json.dumps(d))
    p=run/'manifest.json';d=json.loads(p.read_text())
    for role,name in [('signed_application','signed.bin'),('wolfboot_image','wolfboot.elf')]:
        register_artifact(d,result_dir=run,role=role,path=run/name,stage='synthetic',tool=__name__)
    if negative:
        d['capture_contract']['experiment_class']='secure_boot_negative_validation'
        d['execution_outcome']['result']='secure_boot_negative_test_passed'
    p.write_text(json.dumps(d));reseal(run)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    return load_dataset(tmp_path/'dataset'),run


def test_boundaries_clock_and_handoff():
    rows,identity=decode_boot(decoded(boot_texts()))
    by={r['metric']:r for r in rows}
    assert [by[k]['elapsed_ms'] for k in ('integrity','authenticity','image_verification','boot')]==[1,2,3.125,4]
    assert by['application_start']['elapsed_ms'] is None
    assert identity['handoff']=='observed_application_report_after_handoff'
    assert identity['image_content_sha256']=='a'*64


@pytest.mark.parametrize('old,new', [('hclk_hz=80000000','hclk_hz=0'),('measurement_valid=1','measurement_valid=0'),('mailbox_version=8','mailbox_version=99')])
def test_invalid_clock_mailbox_and_flags(old,new):
    rows,identity=decode_boot(decoded([t.replace(old,new) for t in boot_texts()]))
    assert next(r for r in rows if r['metric']=='integrity')['elapsed_ms'] is None
    assert identity['handoff']=='unconfirmed'


def test_integrity_reference_not_zero_signature():
    texts=boot_texts('integrity_sha256')
    texts[2]=texts[2].replace('measurement_valid=1','measurement_valid=0').replace('cycles=160000','cycles=0')+' measurement_status=not_applicable'
    rows,identity=decode_boot(decoded(texts))
    auth=next(r for r in rows if r['metric']=='authenticity')
    assert auth['validity']=='not_applicable' and auth['elapsed_ms'] is None
    assert identity['handoff']!='unconfirmed'


def test_duplicate_record_bridge_mismatch_and_failure():
    texts=boot_texts(); texts.append(texts[1])
    rows,identity=decode_boot(decoded(texts)); assert identity['handoff']=='unconfirmed'
    texts=boot_texts();texts[-1]=texts[-1].replace('elapsed_us_low=4000','elapsed_us_low=4001')
    rows,_=decode_boot(decoded(texts));assert next(r for r in rows if r['metric']=='boot')['elapsed_ms'] is None
    texts=boot_texts();texts[2]=texts[2].replace('result=0','result=-1')
    _,identity=decode_boot(decoded(texts));assert identity['handoff']=='unconfirmed'


def test_actual_layout_and_reservation():
    result=image_layout(signed_image())
    assert result==dict(packaged_image_bytes=56,image_payload_bytes=24,image_header_reserved_bytes=32,image_metadata_used_bytes=20,image_signature_used_bytes=8)
    bad=bytearray(signed_image());struct.pack_into('<H',bad,10,400)
    with pytest.raises(ValueError):image_layout(bad)


def test_retained_hashes_resources_and_no_concurrent_total(tmp_path):
    dataset,run=fixture(tmp_path)
    data=extract_secure_boot(dataset)
    resources={r['metric']:r for r in data['resources']}
    assert resources['bootloader_flash_bytes']['value_bytes']==24
    assert resources['bootloader_static_ram_bytes']['value_bytes']==80
    assert resources['image_signature_used_bytes']['value_bytes']==8
    assert resources['boot_stack_high_water_bytes']['value_bytes'] is None
    assert data['inputs'] and resources['bootloader_flash_bytes']['build_id']
    assert not any('combined' in k for k in resources)
    (run/'signed.bin').write_bytes(b'changed')
    data=extract_secure_boot(dataset)
    assert next(r for r in data['resources'] if r['metric']=='image_payload_bytes')['validity']=='unavailable'


def test_expected_rejection_is_not_normal_boot(tmp_path):
    dataset,_=fixture(tmp_path,negative=True,records=['PQC_SECURE_BOOT schema=1 mailbox_status=unavailable reason=invalid_magic_or_version'])
    data=extract_secure_boot(dataset)
    assert data['outcomes'][0]['observed_outcome']=='expected_rejection_validation_passed'
    assert data['outcomes'][0]['normal_boot_success'] is False
    assert data['outcomes'][0]['missing_workload_interpretation']=='expected_absence_in_negative_capture'


def test_matched_controls_require_payload_and_source():
    from framework.timing_summary import CORE_CONTROLS
    run={k:'same' for k in CORE_CONTROLS};run.update(run_key='a', controls={'firmware':{'application':'same'}})
    spec={'controls':[], 'treatment':['secure_boot'],'not_applicable':{}}
    out=[dict(run_key='a',image_payload_bytes=24,bootloader_hclk_hz=80000000)]
    assert control_problems([run],spec,out)==[]
    changed=copy.deepcopy(run);changed['run_key']='b';changed['source_commit']='other'
    out.append(dict(run_key='b',image_payload_bytes=32,bootloader_hclk_hz=40000000))
    problems=control_problems([run,changed],spec,out)
    assert 'conflicting_bootloader_hclk' in problems
    assert 'conflicting_control:source_commit' in problems and 'conflicting_image_payload_size' in problems


def test_summary_keeps_unavailable_and_lineage(tmp_path):
    dataset,_=fixture(tmp_path)
    frames,provenance=summarise_secure_boot(dataset,{'conditions':{'base':{}},'baseline':'base'})
    assert provenance['inputs'] and provenance['source_sha256']
    assert len(frames['secure_boot_observations'])==5
    assert frames['secure_boot_distributions'].query("metric == 'application_start'").iloc[0]['n_observations']==0


def test_stack_window_separate_from_timing_and_application(tmp_path):
    texts=boot_texts()+['PQC_SECURE_BOOT_STACK schema=1 boundary=selected_image_integrity_begin_to_verification_end profiling_enabled=1 measurement_status=measured high_water_bytes=128 watermark_capacity_bytes=512 selected_image_valid=1 timing_comparable=0']
    dataset,_=fixture(tmp_path,records=texts)
    dataset.runs[0]['boot_stack_profiling']=True
    data=extract_secure_boot(dataset)
    stack=next(r for r in data['resources'] if r['metric']=='boot_stack_high_water_bytes')
    assert stack['value_bytes']==128 and stack['scope']=='boot_lifetime'
    assert all(not r['timing_comparable'] for r in data['observations'])


def test_invalid_epoch_and_negative_handoff():
    rows,identity=decode_boot(decoded(boot_texts()),invalid='invalid_reporting_epoch')
    assert all(r['elapsed_ms'] is None for r in rows)
    assert identity['handoff']=='unconfirmed'


def test_unexpected_handoff_in_negative_case(tmp_path):
    dataset,_=fixture(tmp_path,negative=True)
    out=extract_secure_boot(dataset)['outcomes'][0]
    assert out['observed_outcome']=='unexpected_handoff' and not out['normal_boot_success']


def test_artifact_symlink_is_not_followed(tmp_path):
    dataset,run=fixture(tmp_path)
    image=run/'signed.bin';target=tmp_path/'outside.bin';target.write_bytes(image.read_bytes())
    image.unlink();image.symlink_to(target)
    data=extract_secure_boot(dataset)
    assert next(r for r in data['resources'] if r['metric']=='image_payload_bytes')['value_bytes'] is None


def test_build_identity_deduplication(tmp_path):
    dataset,_=fixture(tmp_path)
    second=copy.deepcopy(dataset.runs[0]);second['run_key']='second-reference'
    from dataclasses import replace
    dataset=replace(dataset,runs=(*dataset.runs,second))
    frames,_=summarise_secure_boot(dataset,{'conditions':{'base':{}},'baseline':'base'})
    row=frames['secure_boot_distributions'].query("metric == 'bootloader_flash_bytes'").iloc[0]
    assert row['n_observations']==1 and row['median']==24


def test_different_epochs_cannot_complete_each_others_mailbox():
    texts=boot_texts()
    for partial in (texts[:4],texts[4:]):
        _,identity=decode_boot(decoded(partial))
        assert identity['handoff']=='unconfirmed'


def test_stale_manifest_is_rejected(tmp_path):
    dataset,run=fixture(tmp_path)
    p=run/'manifest.json';p.write_text(p.read_text()+' ')
    with pytest.raises(DatasetError):extract_secure_boot(dataset)


def test_inconsistent_mailbox_clock_is_not_comparable():
    texts=boot_texts();texts[2]=texts[2].replace('hclk_hz=80000000','hclk_hz=40000000')
    rows,identity=decode_boot(decoded(texts))
    assert identity['handoff']=='unconfirmed'
    assert next(r for r in rows if r['metric']=='authenticity')['reason']=='inconsistent_mailbox_hclk'


def test_configured_profile_must_match_observed_profile(tmp_path):
    dataset,_=fixture(tmp_path)
    dataset.runs[0]['secure_boot']='mldsa44'
    data=extract_secure_boot(dataset)
    assert data['outcomes'][0]['reason']=='configured_observed_profile_mismatch'
    assert all(r['elapsed_ms'] is None for r in data['observations'])


def test_identity_only_boot_image_uses_only_sealed_matching_retained_bytes(tmp_path):
    from framework.secure_boot_analysis import _retained
    data = b'synthetic ELF bytes'; path = tmp_path/'boot.elf'; path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    manifest = {'artifacts':[{'role':'wolfboot_image','path':None,'sha256':sha,'acquisition':{'status':'available'}}],
        'retained_files':[{'path':'boot.elf','sha256':sha,'size_bytes':len(data)}]}
    inputs=[]
    assert _retained(tmp_path,manifest,'wolfboot_image',inputs)[0] == data
    assert inputs
    path.write_bytes(b'changed')
    with pytest.raises(ValueError): _retained(tmp_path,manifest,'wolfboot_image',[])
