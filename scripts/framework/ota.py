"""STM32L4R5 dual-bank OTA planning, manifest generation and delivery evidence."""
from __future__ import annotations
import hashlib, json, shlex, struct, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_MAGIC=0x504F5441
MANIFEST_VERSION=1
FLAG_BOOTLOADER_MIGRATION=0x1
FLAG_TEST_NO_CONFIRM=0x80000000
BANK_BYTES=0x100000
BOOTLOADER_MAX_BYTES=0x1C000
MANIFEST_SLOT_BYTES=0x4000
APPLICATION_SLOT_BYTES=0xE0000
INACTIVE_LOGICAL_BASE=0x08100000
INACTIVE_MANIFEST_ADDRESS=0x0811C000
INACTIVE_APPLICATION_ADDRESS=0x08120000
CHUNK_BYTES=192

@dataclass(frozen=True)
class OtaCandidate:
    bootloader: Path
    signed_application: Path
    signed_manifest: Path
    bootloader_sha256: str
    application_sha256: str
    manifest_sha256: str
    bootloader_size: int
    application_size: int
    manifest_size: int
    migration: bool
    test_no_confirm: bool

def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def build_manifest_payload(*,bootloader:Path,signed_application:Path,migration:bool,test_no_confirm:bool=False,output:Path)->dict[str,Any]:
    bs=bootloader.stat().st_size; aps=signed_application.stat().st_size
    if not 0 < bs <= BOOTLOADER_MAX_BYTES: raise ValueError(f'candidate wolfBoot size {bs} exceeds {BOOTLOADER_MAX_BYTES}')
    if not 0 < aps <= APPLICATION_SLOT_BYTES: raise ValueError(f'candidate signed application size {aps} exceeds {APPLICATION_SLOT_BYTES}')
    bh=bytes.fromhex(_sha(bootloader)); ah=bytes.fromhex(_sha(signed_application))
    flags=(FLAG_BOOTLOADER_MIGRATION if migration else 0) | (FLAG_TEST_NO_CONFIRM if test_no_confirm else 0)
    payload=struct.pack('<IIIII32s32s',MANIFEST_MAGIC,MANIFEST_VERSION,flags,bs,aps,bh,ah)
    output.parent.mkdir(parents=True,exist_ok=True); output.write_bytes(payload)
    return {'schema_version':1,'magic':'POTA','version':MANIFEST_VERSION,'flags':flags,'migration':migration,'test_no_confirm':test_no_confirm,'bootloader_size':bs,'bootloader_sha256':bh.hex(),'application_size':aps,'application_sha256':ah.hex(),'payload':str(output)}

def candidate_from_files(*,bootloader:Path,signed_application:Path,signed_manifest:Path,migration:bool,test_no_confirm:bool=False)->OtaCandidate:
    for path in (bootloader,signed_application,signed_manifest):
        if not path.is_file(): raise FileNotFoundError(path)
    if signed_manifest.stat().st_size > (MANIFEST_SLOT_BYTES - 24): raise ValueError('signed candidate manifest overlaps reserved OTA state markers')
    return OtaCandidate(bootloader,signed_application,signed_manifest,_sha(bootloader),_sha(signed_application),_sha(signed_manifest),bootloader.stat().st_size,signed_application.stat().st_size,signed_manifest.stat().st_size,migration,test_no_confirm)

def write_plan(candidate:OtaCandidate, output:Path)->Path:
    plan={'schema_version':1,'transport':'reporting_mqtt_plaintext','impairment_exempt':True,'inactive_logical_base':hex(INACTIVE_LOGICAL_BASE),'candidate_manifest_address':hex(INACTIVE_MANIFEST_ADDRESS),'application_address':hex(INACTIVE_APPLICATION_ADDRESS),'migration':candidate.migration,'test_no_confirm':candidate.test_no_confirm,'artifacts':{'wolfboot':{'path':str(candidate.bootloader),'bytes':candidate.bootloader_size,'sha256':candidate.bootloader_sha256},'candidate_manifest':{'path':str(candidate.signed_manifest),'bytes':candidate.manifest_size,'sha256':candidate.manifest_sha256},'signed_application':{'path':str(candidate.signed_application),'bytes':candidate.application_size,'sha256':candidate.application_sha256}}}
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n',encoding='utf-8'); return output

def make_fault_plan(*, plan_path:Path, repo_root:Path, output_dir:Path, fault:str)->Path:
    """Create deterministic negative-test plans without modifying canonical artifacts."""
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    output_dir.mkdir(parents=True,exist_ok=True)
    artifacts=plan['artifacts']
    if fault not in {'invalid-manifest','corrupt-application','interrupted'}:
        raise ValueError(f'unsupported OTA fault: {fault}')
    if fault in {'invalid-manifest','corrupt-application'}:
        key='candidate_manifest' if fault=='invalid-manifest' else 'signed_application'
        src=Path(artifacts[key]['path'])
        if not src.is_absolute(): src=repo_root/src
        data=bytearray(src.read_bytes())
        if not data: raise ValueError(f'cannot corrupt empty artifact: {src}')
        data[len(data)//2] ^= 0x01
        dst=output_dir/f'{fault}-{src.name}'
        dst.write_bytes(data)
        artifacts[key]['path']=str(dst.relative_to(repo_root) if dst.is_relative_to(repo_root) else dst)
        artifacts[key]['bytes']=len(data)
        artifacts[key]['sha256']=hashlib.sha256(data).hexdigest()
    if fault=='interrupted':
        plan['delivery_fault']='interrupted'
    plan['negative_test_fault']=fault
    out=output_dir/f'ota-plan-{fault}.json'
    out.write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return out

def _ssh(target:str, script:str, cwd:Path)->subprocess.CompletedProcess[str]:
    # Send the publish program on stdin rather than as one SSH argv element. A
    # full 1 MiB bank produces thousands of bounded MQTT chunks and would exceed
    # host/SSH argument-length limits if embedded in the remote command line.
    return subprocess.run(['ssh', target, 'sh'], cwd=cwd, text=True, input=script, capture_output=True, check=False)

def deliver_retained_plan(*,plan_path:Path,repo_root:Path,gateway_target:str,reporting_host:str,reporting_port:int,run_id:str)->dict[str,Any]:
    plan=json.loads(plan_path.read_text(encoding='utf-8')); started=time.perf_counter(); published=0
    safe=''.join(c if c.isalnum() or c in '-_.' else '_' for c in run_id)
    prefix=f'pqc/control/ota/stm32/{safe}'
    a=plan['artifacts']
    request='|'.join(['request',str((FLAG_BOOTLOADER_MIGRATION if plan.get('migration') else 0) | (FLAG_TEST_NO_CONFIRM if plan.get('test_no_confirm') else 0)),str(a['wolfboot']['bytes']),a['wolfboot']['sha256'],str(a['candidate_manifest']['bytes']),a['candidate_manifest']['sha256'],str(a['signed_application']['bytes']),a['signed_application']['sha256'],'1'])
    commands=[f"mosquitto_pub -h {shlex.quote(reporting_host)} -p {int(reporting_port)} -q 1 -r -t {shlex.quote(prefix+'/request')} -m {shlex.quote(request)}"]
    for region,key in [('bootloader','wolfboot'),('manifest','candidate_manifest'),('application','signed_application')]:
        data=(repo_root/plan['artifacts'][key]['path']).read_bytes() if not Path(plan['artifacts'][key]['path']).is_absolute() else Path(plan['artifacts'][key]['path']).read_bytes()
        for seq,off in enumerate(range(0,len(data),CHUNK_BYTES)):
            payload=f'{region}|{off}|'+data[off:off+CHUNK_BYTES].hex()
            topic=f'{prefix}/data/{region}/{seq:06d}'
            commands.append(f"mosquitto_pub -h {shlex.quote(reporting_host)} -p {int(reporting_port)} -q 1 -r -t {shlex.quote(topic)} -m {shlex.quote(payload)}")
    commands.append(f"mosquitto_pub -h {shlex.quote(reporting_host)} -p {int(reporting_port)} -q 1 -r -t {shlex.quote(prefix+'/data/zzzzzz-complete')} -m complete")
    if plan.get('delivery_fault') == 'interrupted':
        commands=commands[:max(2,len(commands)//2)]
    script='set -e\ncommand -v mosquitto_pub >/dev/null\n' + '\n'.join(commands) + '\n'
    result=_ssh(gateway_target,script,repo_root)
    if result.returncode==0: published=len(commands)
    return {'return_code':result.returncode,'run_id':run_id,'topic_prefix':prefix,'published_messages':published,'duration_seconds':time.perf_counter()-started,'stdout':result.stdout,'stderr':result.stderr}
