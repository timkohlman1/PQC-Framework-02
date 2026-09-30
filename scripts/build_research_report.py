#!/usr/bin/env python3
"""Freeze, verify or rebuild an explicit offline thesis evidence selection."""
import argparse
from pathlib import Path
import sys

from framework.research_report import build, specification, verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--spec',type=Path,help='explicit datasets, A2 specifications and domains')
    action.add_argument('--verify',type=Path,help='verify a frozen snapshot without execution')
    action.add_argument('--rebuild',type=Path,help='verify and regenerate exactly the frozen selection')
    parser.add_argument('--output',type=Path,help='new snapshot directory (never overwritten)')
    args=parser.parse_args()
    try:
        if args.verify:
            if args.output:raise ValueError('--verify does not accept --output')
            verify(args.verify)
            print('Frozen inputs and outputs verified.')
        else:
            if not args.output:raise ValueError('--output is required')
            if args.rebuild:
                lock=verify(args.rebuild)
                build(lock['specification'],lock['specification_sources'],args.output,expected=lock)
            else:
                value,paths=specification(args.spec)
                build(value,paths,args.output)
            print('Report: '+str(args.output/'report/notebook.html'))
        return 0
    except Exception as exc:
        print('Research report failed: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
