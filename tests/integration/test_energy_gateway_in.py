"""Exercise the gateway control subprocess protocol using local MQTT client doubles."""
import json
import os
from pathlib import Path
import sys

import pytest
from framework.energy_gateway import main
from framework.energy_capture import start_gate_script

pytestmark = pytest.mark.integration


def test_start_gate_ignores_a_marker_from_before_reset(tmp_path):
    import subprocess
    import time
    import shlex
    uart = tmp_path/"uart"
    device = tmp_path/"device"
    uart.write_text("PQC_ENERGY_WAITING\n")
    command = f"uart_file={shlex.quote(str(uart))}; reset_rc=0; " + start_gate_script(str(device))
    process = subprocess.Popen(["sh","-c",command])
    try:
        time.sleep(.25)
        assert not device.exists(), "stale pre-reset announcement released workload"
        with uart.open("a") as output:
            output.write("PQC_ENERGY_WAITING\n")
        assert process.wait(timeout=2) == 0
        assert device.read_text() == "PQC_ENERGY_GO\n"
    finally:
        if process.poll() is None:
            process.kill(); process.wait()


def test_suback_token_acknowledgement_and_retained_cleanup(tmp_path, monkeypatch, capsys):
    pub = tmp_path/"mosquitto_pub"
    pub.write_text(f"#!{sys.executable}\n" + r'''
import json, os, pathlib, sys
a=sys.argv; topic=a[a.index('-t')+1]; data=a[a.index('-m')+1] if '-m' in a else ''
with pathlib.Path(os.environ['ENERGY_TEST_DIR'],'commands').open('a') as f: f.write(json.dumps([topic,data])+'\n')
if topic.endswith('/associate') and data:
    pathlib.Path(os.environ['ENERGY_TEST_DIR'],'token').write_text(data)
''')
    sub = tmp_path/"mosquitto_sub"
    sub.write_text(f"#!{sys.executable}\n" + r'''
import json, os, pathlib, time
print('Client received SUBACK',flush=True)
p=pathlib.Path(os.environ['ENERGY_TEST_DIR'],'token')
while True:
    if p.exists():
        print(json.dumps(dict(type='status',source='energy',status='ready',association_token=p.read_text(),
            sensor_online=True,sensor_valid=True,acquisition='continuous',status_timestamp_us=1000,sample_timestamp_us=999,
            ring_capacity_samples=10,ring_used_samples=2,sample_record_bytes=64,ring_allocated_bytes=640)),flush=True)
    time.sleep(.05)
''')
    pub.chmod(0o700); sub.chmod(0o700)
    monkeypatch.setenv("PATH",str(tmp_path)+os.pathsep+os.environ["PATH"])
    monkeypatch.setenv("ENERGY_TEST_DIR",str(tmp_path))
    args=dict(action="associate",host="unused",port=1886,run_id="run",token="a"*32,timeout=2)
    assert main(args) == 0
    assert main({**args,"action":"cleanup","token":"b"*32}) == 0
    commands=[json.loads(line) for line in (tmp_path/"commands").read_text().splitlines()]
    assert commands[0] == ["pqc/control/instrument/energy/associate","a"*32]
    assert ["pqc/control/instrument/energy/collect",""] in commands
    assert commands[-1] == ["pqc/control/instrument/energy/associate",""]
    # Even an expired health probe must clear retained commands before returning.
    assert main({**args,"action":"cleanup","token":"c"*32,"timeout":0}) == 1
    commands=[json.loads(line) for line in (tmp_path/"commands").read_text().splitlines()]
    assert commands[-2:] == [["pqc/control/instrument/energy/collect", ""],
                              ["pqc/control/instrument/energy/associate", ""]]


def test_terminal_capacity_failure_returns_promptly_and_preserves_stream(tmp_path, monkeypatch):
    import subprocess
    calls=[]
    monkeypatch.setattr(subprocess,"run",lambda command,**kwargs:calls.append(command))
    stream=tmp_path/"raw"
    raw=json.dumps({"topic":"pqc/instrument/energy/run/complete", "payload":{
        "type":"error","source":"energy","run_id":"run","status":"capacity_exceeded","ring_allocated_bytes":7340032}})+"\n"
    stream.write_text(raw)
    assert main(dict(action="collect",host="unused",port=1886,run_id="run",token="a"*32,intervals=1,timeout=.2,stream=str(stream))) == 1
    assert stream.read_text() == raw
    request=json.loads(calls[0][-1])
    assert request["association_token"] == "a"*32 and request["expected_intervals"] == 1
