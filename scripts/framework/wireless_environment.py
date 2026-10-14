"""Read-only AP telemetry; no scan, radio changes, traffic generation or credentials.

Driver counters are optional. Unsupported fields are unavailable, never zero.
This supplementary collection is not retroactive evidence for an earlier run.
"""
import json
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def remote(host, command, *, control_path=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host):
        raise ValueError('use a configured SSH host alias')
    options=[] if control_path is None else ['-o','ControlMaster=auto',
        '-o','ControlPersist=30','-o','ControlPath='+str(control_path)]
    start=time.monotonic_ns()
    started_utc=datetime.now(timezone.utc).isoformat()
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',
            '-o','StrictHostKeyChecking=yes',*options,host,command],capture_output=True,text=True,timeout=20)
        return dict(command=command,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,
            started_utc=started_utc,elapsed_ns=time.monotonic_ns()-start,status='available' if p.returncode==0 else 'unavailable')
    except (OSError,subprocess.TimeoutExpired) as exc:
        return dict(command=command,status='unavailable',reason=type(exc).__name__,started_utc=started_utc,elapsed_ns=time.monotonic_ns()-start)


def interfaces(iw_text, proc_text):
    found=set(re.findall(r'^\s*Interface ([A-Za-z0-9_.-]+)\s*$',iw_text,re.M))
    found.update(re.findall(r'^\s*([A-Za-z0-9_.-]+):',proc_text,re.M))
    return sorted(found)


def survey(text):
    """Only the in-use channel; retain cumulative counters, not invented rates."""
    blocks=text.split('Survey data from ')
    active=[b for b in blocks if '[in use]' in b]
    if len(active)!=1:
        return dict(status='unavailable',reason='no_unique_in_use_channel')
    b=active[0]; values={}
    for field,pattern in {
        'frequency_mhz':r'frequency:\s*(\d+) MHz',
        'noise_dbm':r'noise:\s*(-?\d+) dBm',
        'active_ms':r'channel active time:\s*(\d+) ms',
        'busy_ms':r'channel busy time:\s*(\d+) ms',
        'transmit_ms':r'channel transmit time:\s*(\d+) ms'}.items():
        match=re.search(pattern,b);values[field]=int(match[1]) if match else None
    return dict(status='available',**values)


def busy_fraction(before, after):
    if before.get('frequency_mhz') is None or before.get('frequency_mhz')!=after.get('frequency_mhz'):
        return None
    if any(x.get(k) is None for x in (before,after) for k in ('active_ms','busy_ms')):
        return None
    elapsed=after['active_ms']-before['active_ms'];busy=after['busy_ms']-before['busy_ms']
    return busy/elapsed if elapsed>0 and 0<=busy<=elapsed else None


def collect(host, output, *, samples=12, interval=5, context='idle-baseline',
            backend='iw', radio=None, interface=None, station=None):
    if type(samples) is not int or not 2<=samples<=10000 or not 1<=interval<=3600:
        raise ValueError('require 2..10000 samples and a 1..3600 second interval')
    if backend=='unifi':
        return collect_unifi(host,output,samples=samples,interval=interval,context=context,
                             radio=radio,interface=interface,station=station)
    if backend!='iw':
        raise ValueError('unsupported wireless backend')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    inventory={cmd:remote(host,cmd) for cmd in ('uname -a','cat /proc/net/wireless','iw dev')}
    devices=interfaces(inventory['iw dev'].get('stdout',''),inventory['cat /proc/net/wireless'].get('stdout',''))
    metadata=dict(schema='pqc-wireless-environment',version=1,ssh_host=host,context=context,
        requested_samples=samples,interval_seconds=interval,interfaces=devices,inventory=inventory,
        boundary='AP-side radio observations; not a calibrated RF survey or wired-control comparison')
    (output/'collection.json').write_text(json.dumps(metadata,indent=2)+'\n')
    previous={};deadline=time.monotonic()
    with (output/'samples.ndjson').open('x') as stream:
        for index in range(samples):
            commands=['cat /proc/net/wireless']
            for device in devices:
                commands += [f'iw dev {device} info',f'iw dev {device} station dump',f'iw dev {device} survey dump']
            raw=[remote(host,c) for c in commands]
            metrics={}
            for device in devices:
                command=f'iw dev {device} survey dump'
                response=next(r for r in raw if r['command']==command)
                current=survey(response.get('stdout','')) if response['status']=='available' else dict(status='unavailable',reason='survey_command_failed')
                metrics[device]=dict(current,busy_fraction=busy_fraction(previous.get(device,{}),current))
                previous[device]=current
            stream.write(json.dumps(dict(index=index,host_utc=datetime.now(timezone.utc).isoformat(),
                host_monotonic_ns=time.monotonic_ns(),raw=raw,survey=metrics))+'\n');stream.flush()
            deadline+=interval
            if index+1<samples:
                time.sleep(max(0,deadline-time.monotonic()))
    return metadata



def unifi_stats(text, level, identity):
    """Retain driver field names/units; disabled or ambiguous values stay null."""
    label = 'Radio' if level == 'radio' else 'Node'
    if not re.search(r'^' + label + r' Level Stats: ' + re.escape(identity) + r'(?:\s|$)', text, re.M | re.I):
        return dict(status='unavailable', reason='identity_or_output_mismatch', fields={})
    fields = {}
    duplicates = set()
    for line in text.splitlines():
        match = re.fullmatch(r'\s*([^=]+?)\s*=\s*(.*?)\s*', line)
        if not match:
            continue
        name, value = match.groups()
        if name in fields:
            duplicates.add(name)
        fields[name] = int(value) if re.fullmatch(r'-?\d+', value) else None
    for name in duplicates:
        fields[name] = None
    vap = re.search(r'\(under VAP ([A-Za-z0-9_.-]+)\)', text)
    return dict(status='available' if fields else 'unavailable', fields=fields,
                vap=vap[1] if vap else None,
                interpretation='driver-native values; RSSI has no verified dBm conversion')


def unifi_channel(text):
    match = re.search(r'Current Frequency:([0-9.]+) GHz \(Channel (\d+)\)', text)
    return dict(frequency_mhz=round(float(match[1])*1000), channel=int(match[2])) if match else None


def collect_unifi(host, output, *, samples, interval, context, radio, interface, station):
    # Only explicit read-only commands with validated argument tokens are emitted.
    for name in (radio, interface):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise ValueError('UniFi backend requires a radio and wireless interface')
    if not isinstance(station, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', station):
        raise ValueError('UniFi backend requires a target station MAC')
    station = station.lower()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with connection(host) as query:
        inventory = {cmd: query(cmd) for cmd in ('uname -a', 'cat /etc/version', 'apstats -h')}
        metadata = dict(schema='pqc-wireless-environment', version=2, backend='unifi-apstats',
            ssh_host=host, context=context, requested_samples=samples, interval_seconds=interval,
            radio=radio, interface=interface, station=station, inventory=inventory,
            collection_status='running', recorded_samples=0,
            boundary='AP observations; no calibrated RF survey or historical-run qualification',
            limitations=['Driver-native RSSI is not asserted to be dBm.',
                         'Disabled counters are unavailable, not zero.',
                         'Station counters can reset at reassociation; no cross-reset rate is inferred.',
                         'Radio counters include other stations and desired traffic.',
                         'Self/other-BSS utilisation values retain unverified driver units/window.'])
        metadata_path = output/'collection.json'
        metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
        commands = ['cat /proc/uptime', f'iwlist {interface} channel',
                    f'wlanconfig {interface} list sta', f'apstats -r -i {radio}',
                    f'apstats -s -m {station}']
        recorded = 0
        status = 'interrupted'
        try:
            with (output/'samples.ndjson').open('x') as stream:
                for index in range(samples):
                    started = time.monotonic()
                    started_utc = datetime.now(timezone.utc).isoformat()
                    raw = [query(command) for command in commands]
                    available = {r['command']: r.get('stdout', '') for r in raw if r['status']=='available'}
                    radio_values = unifi_stats(available.get(commands[3], ''), 'radio', radio)
                    station_values = unifi_stats(available.get(commands[4], ''), 'station', station)
                    if station_values.get('vap') != interface:
                        station_values = dict(status='unavailable', reason='station_not_on_selected_interface', fields={})
                    record = dict(index=index, started_utc=started_utc,
                        finished_utc=datetime.now(timezone.utc).isoformat(),
                        host_monotonic_ns=time.monotonic_ns(), raw=raw,
                        channel=unifi_channel(available.get(commands[1], '')),
                        radio=radio_values, station=station_values)
                    stream.write(json.dumps(record)+'\n')
                    stream.flush()
                    recorded += 1
                    if index+1<samples:
                        time.sleep(max(0, interval-(time.monotonic()-started)))
            status = 'completed'
        finally:
            metadata.update(collection_status=status, recorded_samples=recorded,
                            finished_utc=datetime.now(timezone.utc).isoformat())
            metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
        return metadata


@contextmanager
def connection(host):
    """Reuse one owned SSH transport so polling avoids repeated AP key exchange."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host):
        raise ValueError('use a configured SSH host alias')
    with TemporaryDirectory(prefix='pqc-ap-') as directory:
        control_path=Path(directory)/'connection'
        try:
            yield lambda command: remote(host,command,control_path=control_path)
        finally:
            try:
                subprocess.run(['ssh','-S',str(control_path),'-O','exit',host],
                               capture_output=True,text=True,timeout=5)
            except (OSError,subprocess.TimeoutExpired):
                pass  # Owned master expires after 30 seconds if explicit close fails.
