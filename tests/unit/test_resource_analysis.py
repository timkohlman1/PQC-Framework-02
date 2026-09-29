"""A3 known-answer fixtures: synthetic values, never hardware evidence."""
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / 'scripts', ROOT / 'tests'):
    sys.path.insert(0, str(directory))
from framework.resource_analysis import elf_resources, extract_resources, summarise_resources, _union
from framework.timing_dataset import export_dataset, DatasetError
from framework.timing_dataset_loader import load_dataset
from framework.run_evidence import register_artifact
from timing_dataset_support import make_run, logical, rm2_records, reseal, tls_records


def synthetic_elf():
    """ELF fixture: 16 text + 8 data Flash, 80 static RAM, 128 RAM reservation.

    RAM3 has a 32-byte result buffer and 64-byte workspace. NOBITS/debug/header
    padding must not enter the 24-byte Flash result or 24-byte image span.
    """
    data = bytearray(4096)
    data[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
    names = b'\0.text\0.data\0.bss\0.pqc_result_buffer\0.pqc_mldsa_workspace\0._user_heap_stack\0.symtab\0.strtab\0.shstrtab\0'
    symbols = {'__ram_region_start__':0x20000000,'__ram_region_end__':0x20030000,
               '__ram2_region_start__':0x10000000,'__ram2_region_end__':0x10010000,
               '__ram3_region_start__':0x20040000,'__ram3_region_end__':0x200a0000,
               '_end':0x20000050,'__user_heap_stack_end__':0x20000080}
    strings = b'\0'; sym = bytes(16)
    for name,value in symbols.items():
        sym += struct.pack('<IIIBBH',len(strings),value,0,0,0,0xfff1)
        strings += name.encode()+b'\0'
    data[1024:1024+len(sym)] = sym
    data[1280:1280+len(strings)] = strings
    data[1792:1792+len(names)] = names
    def sec(name,kind,flags,addr,off,size,link=0,entry=0):
        return (names.index(name.encode()+b'\0'),kind,flags,addr,off,size,link,0,4,entry)
    sections = [(0,)*10,
        sec('.text',1,2,0x08003000,512,16),sec('.data',1,3,0x20000000,528,8),
        sec('.bss',8,3,0x20000008,0,72),sec('.pqc_result_buffer',8,3,0x20040000,0,32),
        sec('.pqc_mldsa_workspace',8,3,0x20040020,0,64),sec('._user_heap_stack',8,3,0x20000050,0,48),
        sec('.symtab',2,0,0,1024,len(sym),8,16),sec('.strtab',3,0,0,1280,len(strings)),sec('.shstrtab',3,0,0,1792,len(names))]
    struct.pack_into('<HHIIIIIHHHHHH',data,16,2,40,1,0x08003001,52,2048,0,52,32,2,40,len(sections),9)
    struct.pack_into('<IIIIIIII',data,52,1,512,0x08003000,0x08003000,16,16,5,4)
    struct.pack_into('<IIIIIIII',data,84,1,528,0x20000000,0x08003010,8,80,6,4)
    for i,s in enumerate(sections):struct.pack_into('<IIIIIIIIII',data,2048+40*i,*s)
    return bytes(data)


def memory(peak=40, saturated=0):
    fields = dict(freertos_heap_total_bytes=64,freertos_heap_peak_used_bytes=peak,
        freertos_heap_min_free_bytes=64-peak,freertos_heap_final_free_bytes=32,
        sbrk_capacity_bytes=100,sbrk_peak_used_bytes=16,sbrk_final_used_bytes=8,
        msp_reserved_bytes=48,msp_peak_used_bytes=24,msp_measurement_window_bytes=100,
        msp_measurement_saturated=saturated,mldsa_workspace_total_bytes=64,mldsa_workspace_peak_used_bytes=32)
    return logical(' '.join(f'{k}={v}' for k,v in fields.items()),context='memory')


def fixture(tmp_path, *, count=2, records=None, signed=False, bad_link=False, uart=False):
    runs=[]
    for i in range(count):
        r=make_run(tmp_path/f'run{i}',run_id=f'synthetic-{i}',records=records or [*rm2_records(), memory()])
        elf=synthetic_elf(); (r/'firmware.elf').write_bytes(elf); (r/'firmware.bin').write_bytes(bytes(24))
        p=r/'run-provenance.json';d=json.loads(p.read_text());d['records']['firmware']['sha256']=hashlib.sha256(elf).hexdigest();p.write_text(json.dumps(d))
        p=r/'manifest.json';d=json.loads(p.read_text())
        for role,name in [('application_elf','firmware.elf'),('application_binary','firmware.bin')]:
            register_artifact(d,result_dir=r,role=role,path=r/name,stage='synthetic',tool=__name__)
        if uart:
            (r/'uart.log').write_text('application task stack: stage=network_task_complete task=networkTask total_bytes=8192 minimum_free_bytes=2048 peak_used_bytes=6144\n')
            register_artifact(d,result_dir=r,role='diagnostic_uart',path=r/'uart.log',stage='synthetic',tool=__name__)
        if signed:
            image=bytes([i+1])*12
            (r/'signed.bin').write_bytes(image)
            register_artifact(d,result_dir=r,role='signed_application',path=r/'signed.bin',stage='synthetic',tool=__name__)
            pp=r/'run-provenance.json';pd=json.loads(pp.read_text())
            pd['records']['firmware']={'sha256':hashlib.sha256(image).hexdigest(),'evidence_role':'signed_application'}
            pd['records']['build_reference']={'artifact_sha256':'a'*64 if bad_link else hashlib.sha256(elf).hexdigest()}
            pp.write_text(json.dumps(pd))
        p.write_text(json.dumps(d));reseal(r);runs.append(r)
    out=tmp_path/'dataset';export_dataset(run_dirs=runs,output=out)
    return load_dataset(out),runs


def test_elf_regions_do_not_add_heap_workspace_or_reservations_twice():
    values=elf_resources(synthetic_elf())
    assert values == dict(flash_section_bytes=24,application_image_span_bytes=24,
        ram_static_base_bytes=80,ram_linker_reserved_bytes=128,ram2_section_bytes=0,
        ram3_section_bytes=96,result_buffer_reserved_bytes=32,workspace_reserved_bytes=64)
    assert _union([(0,10),(5,12),(20,25)]) == 17
    with pytest.raises(ValueError):elf_resources(synthetic_elf()[:200])
    b=bytearray(synthetic_elf());b[4]=2
    with pytest.raises(ValueError):elf_resources(bytes(b))


def test_build_dedup_lifetime_scope_lineage_and_missing_total(tmp_path):
    dataset,runs=fixture(tmp_path)
    result=extract_resources(dataset)
    assert len(result['builds'])==1
    assert len(result['builds'][0]['run_keys'])==2
    assert result['builds'][0]['source_inputs']
    peaks=[r for r in result['runtime'] if r['metric']=='freertos_heap_peak_used_bytes']
    assert [p['value_bytes'] for p in peaks]==[40,40]
    assert all(p['iteration_id'] is None and p['source_records'] for p in peaks)
    total=[r for r in result['runtime'] if r['metric']=='simultaneous_system_peak_bytes']
    assert all(r['value_bytes'] is None and 'independent_regional_peaks' in r['reason'] for r in total)
    frames,provenance=summarise_resources(dataset,{'conditions':{'base':{}},'baseline':'base'})
    stats={r['metric']:r for r in frames['resource_distributions'].to_dict('records')}
    assert stats['flash_section_bytes']['n_observations']==1
    assert stats['flash_section_bytes']['median_KiB']==24/1024
    assert stats['freertos_heap_peak_used_bytes']['n_observations']==2
    assert provenance['conversion']=='1 KiB = 1024 bytes'


def test_repeated_handshakes_do_not_duplicate_final_memory(tmp_path):
    records=[*tls_records(1,repeat=True),*tls_records(2,repeat=True),memory()]
    d,_=fixture(tmp_path,count=1,records=records)
    result=extract_resources(d)
    assert len([r for r in result['runtime'] if r['metric']=='freertos_heap_peak_used_bytes'])==1


def test_saturation_duplicate_final_records_and_bad_heap_are_excluded(tmp_path):
    d,_=fixture(tmp_path,count=1,records=[*rm2_records(),memory(saturated=1),memory(saturated=1)])
    f,_=summarise_resources(d,{'conditions':{'base':{}},'baseline':'base'})
    assert all(r['n_observations']==0 for r in f['resource_distributions'].to_dict('records') if r['sample_unit']=='run_lifetime')
    m=f['resource_observations'].query('metric == "msp_peak_used_bytes"')
    assert set(m.validity)=={'lower_bound'}


def test_tampered_source_refused_and_missing_elf_not_capacity(tmp_path):
    d,runs=fixture(tmp_path,count=1)
    (runs[0]/'firmware.elf').write_bytes(b'invalid')
    result=extract_resources(d)
    assert all(r['value_bytes'] is None and r['reason'] for r in result['builds'][0]['resources'])
    with (runs[0]/'mqtt-reporting-raw.ndjson').open('a') as f:f.write('tamper')
    with pytest.raises(DatasetError):extract_resources(d)


def test_unsafe_artifact_does_not_read_private_material(tmp_path):
    d,runs=fixture(tmp_path,count=1)
    secret=tmp_path/'secret';secret.write_text('DO_NOT_EXPORT')
    (runs[0]/'firmware.elf').unlink();(runs[0]/'firmware.elf').symlink_to(secret)
    result=extract_resources(d)
    assert 'DO_NOT_EXPORT' not in json.dumps(result)
    assert all(r['value_bytes'] is None for r in result['builds'][0]['resources'])


def test_matched_deltas_and_control_mismatch(tmp_path):
    from framework.timing_summary import CORE_CONTROLS, leaves, field
    d,_=fixture(tmp_path)
    d.runs[1]['tls_kex']='new'
    # The fixture lacks some optional scientific controls; explain each explicitly.
    keys=set(CORE_CONTROLS)
    for run in d.runs:keys |= leaves(run['controls'])
    missing={key:'not supplied by synthetic fixture' for key in keys if any(field(r,key) is None or field(r,key)=={} for r in d.runs)}
    spec={'conditions':{'base':{'tls_kex':'secp256r1'},'new':{'tls_kex':'new'}},
          'baseline':'base','treatment':['tls_kex'],'not_applicable':missing}
    f,_=summarise_resources(d,spec)
    diff=next(r for r in f['resource_differences'].to_dict('records') if r['metric']=='flash_section_bytes')
    assert diff['delta_median_bytes']==0 and diff['percent_difference']==0
    assert diff['baseline_observation_ids']==diff['treatment_observation_ids']
    d.runs[1]['target']='other-board'
    f,_=summarise_resources(d,spec)
    diff=next(r for r in f['resource_differences'].to_dict('records') if r['metric']=='flash_section_bytes')
    assert diff['delta_median_bytes'] is None and 'conflicting_control:target' in diff['reason']


def test_heap_inconsistency_and_handshake_minima_are_not_peaks(tmp_path):
    bad=memory();bad['text']=bad['text'].replace('freertos_heap_peak_used_bytes=40','freertos_heap_peak_used_bytes=60')
    tls=logical('PQC_TLS_HANDSHAKE_MEMORY stack_before_min_free_bytes=100 stack_after_min_free_bytes=80 heap_before_free_bytes=32 heap_after_free_bytes=32 heap_before_min_ever_free_bytes=24 heap_after_min_ever_free_bytes=24',iteration=3)
    d,_=fixture(tmp_path,count=1,records=[*rm2_records(),bad,tls])
    rows=extract_resources(d)['runtime']
    peak=next(r for r in rows if r['metric']=='freertos_heap_peak_used_bytes')
    assert peak['value_bytes'] is None and peak['reason']=='inconsistent_heap_accounting'
    stack=next(r for r in rows if r['metric']=='stack_after_min_free_bytes')
    assert stack['value_bytes']==80 and stack['iteration_id']==3
    assert stack['scope']=='lifetime_checkpoint_at_handshake' and 'minimum_free' in stack['accounting']


def test_distinct_signed_images_map_to_one_explicit_elf_build(tmp_path):
    d,_=fixture(tmp_path,signed=True)
    result=extract_resources(d)
    assert len(result['builds'])==1
    build=result['builds'][0]
    assert len(set(build['firmware_identities']))==2
    assert build['build_id']==hashlib.sha256(synthetic_elf()).hexdigest()
    assert all(r['validity']=='valid' for r in build['resources'])


def test_signed_image_without_correct_build_link_stays_unavailable(tmp_path):
    d,_=fixture(tmp_path,count=1,signed=True,bad_link=True)
    result=extract_resources(d)
    assert result['builds'][0]['build_id'] is None
    assert all(r['value_bytes'] is None for r in result['builds'][0]['resources'])


def test_known_nonzero_delta_and_zero_baseline(monkeypatch):
    from test_timing_summary import data, spec
    import framework.resource_analysis as module
    d=data()
    builds=[]
    for i,run in enumerate(d.runs):
        value=100 if i<2 else 150
        builds.append(dict(build_id=str(i),run_keys=[run['run_key']],resources=[
            module._row('flash_section_bytes',module.STATIC['flash_section_bytes'],value),
            module._row('ram2_section_bytes',module.STATIC['ram2_section_bytes'],0 if i<2 else 8)]))
    monkeypatch.setattr(module,'extract_resources',lambda dataset:dict(builds=builds,runtime=[],inputs=[]))
    f,_=module.summarise_resources(d,spec())
    diff={r['metric']:r for r in f['resource_differences'].to_dict('records')}
    assert diff['flash_section_bytes']['delta_median_bytes']==50
    assert diff['flash_section_bytes']['percent_difference']==50
    assert diff['ram2_section_bytes']['delta_median_bytes']==8
    assert diff['ram2_section_bytes']['percent_difference'] is None
    assert diff['ram2_section_bytes']['percent_reason']=='zero_baseline'


def test_missing_heap_field_does_not_hide_an_independent_region(tmp_path):
    record=memory();record['text']=record['text'].replace('freertos_heap_min_free_bytes=24 ', '')
    d,_=fixture(tmp_path,count=1,records=[*rm2_records(),record])
    rows=extract_resources(d)['runtime']
    assert next(r for r in rows if r['metric']=='freertos_heap_peak_used_bytes')['value_bytes'] is None
    assert next(r for r in rows if r['metric']=='sbrk_peak_used_bytes')['value_bytes']==16


def test_task_stack_completion_checkpoint_retains_allocation_and_use(tmp_path):
    d,_=fixture(tmp_path,count=1,uart=True)
    result=extract_resources(d)
    rows={r['metric']:r for r in result['runtime'] if r.get('task')=='networkTask'}
    assert rows['task_stack_total_bytes']['value_bytes']==8192
    assert rows['task_stack_peak_used_bytes']['value_bytes']==6144
    assert rows['task_stack_minimum_free_bytes']['value_bytes']==2048
    assert all(r['stage']=='network_task_complete' and r['source_records']==[{'line':1}] for r in rows.values())
    assert rows['task_stack_total_bytes']['accounting']=='allocated_task_stack_within_heap'
