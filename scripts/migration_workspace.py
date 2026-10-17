#!/usr/bin/env python3
"""Docker-side option discovery and analysis for the host migration CLI."""
import argparse
import json
from pathlib import Path
import sys

from framework.campaign_editor import load
from framework.config_resolver import ConfigResolver
from framework.run_queue import owned_path, read
from framework import migration_report

ROOT = Path(__file__).resolve().parents[1]


def catalogue(root):
    blank = load(root)
    available = blank['options']
    resolver = ConfigResolver(root)
    descriptions = {}
    for kind in ('tls_kex', 'tls_auth', 'secure_boot', 'network_condition'):
        descriptions[kind] = {}
        for name in available[kind]:
            data = resolver.load_profile(kind, name).data
            if kind == 'network_condition':
                params = data['impairment']
                text = ('No injected impairment' if not params['enabled'] else
                    f"{params['rate_kbit']} kbit/s, {params['rtt_ms']} ms RTT, {params['loss_percent']}% loss, MTU {params['mtu']}")
            elif kind == 'secure_boot' and name == 'integrity_sha256':
                text = 'Integrity only; no firmware signature authentication'
            elif kind == 'tls_kex':
                text = data.get('class', '')
            else:
                text = data.get('description', name)
            descriptions[kind][name] = text
    descriptions['mqtt_transport'] = {'tls': 'MQTT over TLS 1.3', 'plaintext': 'MQTT without transport encryption or authentication'}
    descriptions['mldsa_memory_mode'] = {
        'default': 'Current signing and verification implementation',
        'verify_small': 'Small-memory verification on the STM32',
        'sign_small': 'Small-memory signing on the STM32 (mutual authentication)',
        'both_small': 'Small-memory signing and verification on the STM32 (mutual authentication)',
    }
    descriptions['firmware_mode'] = {'single_bank': 'Single application bank; OTA disabled',
        'dual_bank_no_ota': 'Dual-bank layout; OTA disabled',
        'dual_bank_ota': 'Dual-bank layout; OTA support compiled in'}
    return dict(base=blank['data'], options=available, descriptions=descriptions,
        auth_modes={name: resolver.load_profile('tls_auth',name).data['supported_modes'] for name in available['tls_auth']},
        signed_boot=[name for name in available['secure_boot']
                     if resolver.load_profile('secure_boot',name).data.get('signing',{}).get('requires_private_key')])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['catalogue','report','verify'])
    parser.add_argument('--session')
    args = parser.parse_args(argv)
    try:
        if args.action == 'catalogue':
            result = catalogue(ROOT)
        else:
            if not args.session:
                parser.error('--session is required')
            session = read(owned_path(ROOT, args.session))
            result = (migration_report.publish if args.action == 'report' else migration_report.verify)(ROOT, session)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print('migration-workspace: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
