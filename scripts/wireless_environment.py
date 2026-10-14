#!/usr/bin/env python3
"""Collect passive AP radio diagnostics using an existing SSH host alias."""
import argparse
import json
from pathlib import Path
from framework.wireless_environment import collect


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ssh-host',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=12)
    p.add_argument('--interval',type=float,default=5)
    p.add_argument('--context',default='idle-baseline')
    p.add_argument('--backend',choices=('iw','unifi'),default='iw')
    p.add_argument('--radio',help='UniFi radio, for example wifi0')
    p.add_argument('--interface',help='UniFi wireless interface, for example wifi0ap2')
    p.add_argument('--station',help='Target device MAC for UniFi station counters')
    a=p.parse_args()
    print(json.dumps(collect(a.ssh_host,a.output,samples=a.samples,interval=a.interval,context=a.context,
        backend=a.backend,radio=a.radio,interface=a.interface,station=a.station),indent=2))


if __name__=='__main__':
    main()
