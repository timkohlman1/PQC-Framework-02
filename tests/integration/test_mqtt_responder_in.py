"""Native feeder isolation and lifecycle on a disposable gateway broker; no STM32."""
import json
from pathlib import Path
import shlex
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework import mqtt_responder
from framework.bounded_command import run


@pytest.mark.integration
@pytest.mark.parametrize('scenario', ['success','no_request','missing_ready'])
def test_broker_namespace_feeder_survives_total_external_loss(pqc_require_capabilities,scenario):
    pqc_require_capabilities('gateway',strict_mode='gateway')
    # Only a random container's interface is impaired; no lab broker or STM32.
    script = r'''
import json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path
source=__MODULE_SOURCE__
scenario=__SCENARIO__
name='pqc-responder-test-'+uuid.uuid4().hex[:12]
image=__PINNED_IMAGE__
with tempfile.TemporaryDirectory(prefix='pqc-responder-test-') as raw:
    folder=Path(raw);helper=folder/'responder.py';helper.write_text(source)
    broker=subprocess.Popen(['docker','run','--rm','--name',name,'--entrypoint','mosquitto',image,'-p','1884'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    coordinator=receiver=None
    try:
        for i in range(100):
            result=subprocess.run(['docker','inspect','-f','{{.State.Pid}}',name],capture_output=True,text=True)
            if result.returncode==0 and result.stdout.strip().isdigit() and int(result.stdout)>0:
                pid=result.stdout.strip();break
            time.sleep(.1)
        else:raise AssertionError('isolated broker failed to start')
        ns=['sudo','-n','nsenter','-t',pid,'-n']
        namespace=subprocess.check_output(ns+['readlink','/proc/self/ns/net'],text=True).strip()
        assert namespace!=os.readlink('/proc/self/ns/net')
        native=ns+['--setgid',str(os.getgid()),'--setuid',str(os.getuid())]
        subprocess.run(ns+['/usr/sbin/tc','qdisc','add','dev','eth0','root','netem','loss','100%'],check=True,timeout=10)
        subprocess.run(ns+['/usr/sbin/ip','link','set','dev','eth0','mtu','400'],check=True,timeout=10)
        cfg=dict(token=uuid.uuid4().hex[:12],host='127.0.0.1',port=1884,tls_args=[],oqs=False,response_topic='test/ready',request_topic='test/request',payload_topic='test/data',request_payload='send',payload_bytes=204800,chunk_bytes=400,timeout=3 if scenario=='no_request' else 30)
        response,ready,rc=[folder/n for n in ('response','ready','rc')]
        log=(folder/'log').open('w+')
        coordinator=subprocess.Popen(native+[sys.executable,'-u',str(helper),json.dumps(cfg),str(response),str(ready),str(rc),namespace],stdout=log,stderr=subprocess.STDOUT)
        def wait_for(predicate,limit=35):
            until=time.monotonic()+limit
            while time.monotonic()<until:
                if predicate():return
                if coordinator.poll() is not None:raise AssertionError((folder/'log').read_text())
                time.sleep(.05)
            raise AssertionError((folder/'log').read_text())
        wait_for(ready.exists)
        if scenario!='no_request':
            receiver_log=(folder/'received').open('w+')
            receiver=subprocess.Popen(native+['stdbuf','-oL','-eL','mosquitto_sub','-h','127.0.0.1','-p','1884','-d','-t','test/data','-C','512','-W','20'],stdout=receiver_log,stderr=subprocess.STDOUT)
            wait_for(lambda:'Subscribed (mid: 1): 0' in (folder/'received').read_text())
            subprocess.run(native+['mosquitto_pub','-h','127.0.0.1','-p','1884','-t','test/request','-m','send'],check=True,timeout=10)
            assert receiver.wait(timeout=25)==0
            data=[line for line in (folder/'received').read_bytes().splitlines() if line.startswith(b'A')]
            assert len(data)==512 and b''.join(data)==b'A'*204800
            wait_for(lambda:'"event": "publisher_complete"' in (folder/'log').read_text())
        if scenario=='success':
            subprocess.run(native+['mosquitto_pub','-h','127.0.0.1','-p','1884','-t','test/ready','-m','ready'],check=True,timeout=10)
            expected=0
        else:
            if scenario=='no_request':time.sleep(4)
            coordinator.terminate();expected=27 if scenario=='no_request' else 28
        assert coordinator.wait(timeout=40)==expected,(folder/'log').read_text()
        print((folder/'log').read_text())
        assert response.read_text()==('test/ready ready\n' if scenario=='success' else '')
        assert 'loss 100%' in subprocess.check_output(ns+['/usr/sbin/tc','-s','qdisc','show','dev','eth0'],text=True)
        assert 'mtu 400' in subprocess.check_output(ns+['/usr/sbin/ip','link','show','dev','eth0'],text=True)
        print('PQC_TEST_EXTERNAL_LOSS=100 MTU=400 PAYLOAD_VERIFIED='+str(scenario!='no_request'))
    finally:
        for child in (coordinator,receiver):
            if child and child.poll() is None:child.terminate();child.wait(timeout=40)
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        broker.wait(timeout=10)
'''.replace('__PINNED_IMAGE__',repr(mqtt_responder.IMAGE)).replace('__MODULE_SOURCE__',repr(Path(mqtt_responder.__file__).read_text())).replace('__SCENARIO__',repr(scenario))
    import yaml
    gateway=yaml.safe_load((ROOT/'configs/gateways/pqc_gateway1.yaml').read_text())
    target=gateway['identity']['ssh_user']+'@'+gateway['identity']['alias']
    result=run(['ssh',target,'python3 -u -c '+shlex.quote(script)],cwd=ROOT,timeout=150)
    assert result.returncode==0,result.stdout+result.stderr
    details=mqtt_responder.evidence(result.stdout)
    assert details['verified'] and details['cleanup_verified'],result.stdout
    assert details['contract']==mqtt_responder.CONTRACT
    events=details['events'];names=[e['event'] for e in events]
    assert names.index('ready')<names.index('cleanup')
    assert all(e['monotonic_ns']<events[names.index('ready')]['monotonic_ns'] for e in events if e['event']=='client_started')
    assert events[-1]['return_code']=={'success':0,'no_request':27,'missing_ready':28}[scenario]
