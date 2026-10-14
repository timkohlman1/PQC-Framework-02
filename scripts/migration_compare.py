#!/usr/bin/env python3
"""Linux host entry point for the interactive MQTT migration comparison."""
import argparse
import os
from pathlib import Path
import sys

from framework import migration
from framework.run_queue import Queue, owned_path, read

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', metavar='SESSION_JSON', help='resume waiting/export without repeating submitted runs')
    parser.add_argument('--directory', default='results/queue', help='shared queue directory for a new comparison')
    args = parser.parse_args(argv)
    if os.environ.get('PQC_CONTAINER') == '1':
        parser.error('run on the Linux host; this launcher owns Docker')
    path = None
    try:
        if args.resume:
            path = owned_path(ROOT, args.resume)
            value = read(path)
            queue = Queue(ROOT, value['queue'])
        else:
            queue = Queue(ROOT, args.directory)
            print('Loading supported framework options…', flush=True)
            catalogue = migration.helper(queue, 'catalogue')
            choices = migration.wizard(catalogue)
            for key, label in migration.LABELS.items():
                print(f"{label}: {choices['from'][key]} -> {choices['to'][key]}")
            print(f"{choices['repetitions']} attempts per state; {2*choices['repetitions']} total. "
                  'All changed choices are evaluated together.')
            decision = migration.choose('Create the two profiles and queue the comparison?', ['Run', 'Cancel'], 'Run')
            if decision == 'Cancel':
                return 0
            path, value = migration.new_session(queue, catalogue, choices)
        print('Session: ' + str(path), flush=True)
        print('Ctrl-C detaches; queued experiments continue. Resume with:\n'
              'python3 scripts/migration_compare.py --resume ' + queue.relative(path), flush=True)
        migration.run(queue, path, value)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('\nDetached. Queue jobs continue; no experiments were cancelled.', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError) as exc:
        print('migration-compare: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if path:
            print('Resume: python3 scripts/migration_compare.py --resume ' + str(path), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
