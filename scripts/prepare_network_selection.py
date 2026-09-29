#!/usr/bin/env python3
"""Create conservative A5 selections from retained broker client identities.

Offline only. Failed handshakes without broker identity remain unselected. No
inference from broker port alone; ambiguous/NAT-translated identities are refused.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re

from framework.packet_analysis import read_pcap
from framework.timing_dataset_loader import load_dataset
from framework.timing_summary import digest


def verified_file(root, manifest, role, name):
    items = [a for a in manifest.get('artifacts', []) if a.get('role') == role]
    if not items or items[0].get('acquisition', {}).get('status') != 'available':
        return None
    path = root / name
    if (len(items) != 1 or items[0].get('path') != name or path.is_symlink()
            or not path.is_file() or digest(path) != items[0].get('sha256')):
        raise ValueError('invalid retained ' + role)
    return path


def broker_clients(text, client_id):
    pattern = re.compile(r'New client connected from ([0-9.]+):([0-9]+) as ' + re.escape(client_id) + r' \(')
    found = set()
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            ip = str(ipaddress.IPv4Address(match[1])); port = int(match[2])
            if not 1 <= port <= 65535:
                raise ValueError('invalid broker client port')
            found.add((ip, port))
    return found


def prepare(dataset_path, output):
    dataset_path, output = Path(dataset_path).resolve(), Path(output).resolve()
    dataset = load_dataset(dataset_path, verify_inputs=True)
    for source in [dataset_path, *[Path(r['input_path']).resolve() for r in dataset.runs]]:
        if output == source or source in output.parents or output in source.parents:
            raise ValueError('selection output must be separate from dataset and captures')
    selections, statuses = {}, []
    for run in dataset.runs:
        root = Path(run['input_path'])
        manifest = json.loads((root/'manifest.json').read_text())
        log = verified_file(root, manifest, 'experiment_broker_log', 'mqtt-broker-log.log')
        snapshot = verified_file(root, manifest, 'resolved_case_snapshot', 'resolved-case.json')
        pcap = verified_file(root, manifest, 'packet_capture', 'gateway-network-capture.pcap')
        status = 'missing_broker_log_snapshot_or_pcap'
        if log and snapshot and pcap:
            hashes = {p: digest(p) for p in (log, snapshot, pcap)}
            mqtt = json.loads(snapshot.read_text())['effective_non_secret_parameters']['mqtt']
            client_id = mqtt.get('client_id')
            if not isinstance(client_id, str) or not client_id.startswith('pqc-stm32-'):
                raise ValueError('missing explicit STM32 client ID')
            clients = broker_clients(log.read_text(), client_id)
            server = mqtt['orchestration']['host']; port = mqtt['broker']['port']
            _, packets = read_pcap(pcap)
            candidates = {(p.src_ip, p.src_port) for p in packets if p.dst_ip == server and p.dst_port == port}
            matched = clients & candidates
            ips = {ip for ip, _ in matched}
            status = 'missing_or_ambiguous_broker_to_pcap_identity'
            if len(ips) == 1:
                ip = next(iter(ips))
                # A5 currently selects all client ports. Refuse selection when
                # any other port from this IP lacks explicit STM32 association.
                if {pair for pair in candidates if pair[0] == ip} <= clients:
                    selections[run['run_key']] = dict(client_ip=ip, server_ip=server, server_port=port,
                        evidence_reference=f'mqtt-broker-log.log SHA256={hashes[log]}; exact client_id={client_id}; endpoint intersection with retained PCAP',
                        window={'kind':'retained_flow'})
                    status = 'selected_from_retained_broker_identity'
            if any(digest(p) != sha for p, sha in hashes.items()):
                raise ValueError('retained selection evidence changed during read')
        statuses.append(dict(run_key=run['run_key'], status=status))
    load_dataset(dataset_path, verify_inputs=True)
    output.mkdir(parents=True, exist_ok=False)
    (output/'network-selection.json').write_text(json.dumps(selections, indent=2, sort_keys=True)+'\n')
    (output/'selection-status.json').write_text(json.dumps(statuses, indent=2)+'\n')
    return dict(selected=len(selections), unselected=len(statuses)-len(selections), output=str(output))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args=parser.parse_args()
    try:
        print(json.dumps(prepare(args.dataset, args.output)))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'network selection failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
