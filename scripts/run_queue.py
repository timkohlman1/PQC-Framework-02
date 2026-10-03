#!/usr/bin/env python3
"""PQC terminal queue. Run on the Linux host; children use the Docker wrappers."""
from __future__ import annotations
import argparse
import json
import os
import sys
from framework.run_queue import Queue


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', default='results/queue', help='ignored queue directory below results/')
    sub = p.add_subparsers(dest='action')
    for action in ('ui', 'profiles', 'list', 'start', 'stop', 'quit', 'export'):
        sub.add_parser(action)
    add = sub.add_parser('add')
    add.add_argument('profiles', nargs='+', help='campaign IDs or paths relative to configs/campaigns')
    add.add_argument('--repetitions', type=int, help='override repetitions per condition for each selected profile')
    for action in ('pause', 'resume', 'retry', 'accept', 'mark', 'remove'):
        cmd = sub.add_parser(action)
        cmd.add_argument('id')
    purge = sub.add_parser('purge', help='Permanently delete retained job files')
    purge.add_argument('id')
    purge.add_argument('--confirm', required=True, help='repeat the exact entry ID')
    move = sub.add_parser('move')
    move.add_argument('id')
    move.add_argument('direction', choices=['up', 'down'])
    worker = sub.add_parser('worker', help=argparse.SUPPRESS)
    worker.add_argument('--once', action='store_true')
    args = p.parse_args(argv)
    if os.environ.get('PQC_CONTAINER') == '1':
        p.error('run run_queue.py with host python3; its framework children already use Docker')
    try:
        queue = Queue(directory=args.directory)
        action = args.action or 'ui'
        if action == 'ui':
            from framework.queue_tui import run
            return run(queue)
        if action == 'profiles':
            result = queue.catalogue()
        elif action == 'list':
            result = {'dispatch': queue.dispatch(), 'worker_active': queue.worker_alive(), 'jobs': queue.display_jobs()}
        elif action == 'add':
            result = {'added': queue.add(args.profiles, args.repetitions)}
        elif action in {'resume', 'retry', 'accept'}:
            queue.decide(args.id, action)
            result = {'id': args.id, 'decision': action}
        elif action == 'purge':
            queue.purge(args.id, args.confirm)
            result = {'id': args.id, 'action': 'purged'}
        elif action in {'pause', 'mark', 'remove'}:
            getattr(queue, action)(args.id)
            result = {'id': args.id, 'action': action}
        elif action == 'move':
            queue.move(args.id, args.direction)
            result = {'id': args.id, 'direction': args.direction}
        elif action == 'quit':
            queue.shutdown()
            result = {'dispatch': queue.dispatch(), 'worker_active': False}
        elif action == 'worker':
            return queue.worker(once=args.once)
        elif action == 'export':
            result = queue.export()
        else:
            getattr(queue, action)()
            result = {'dispatch': queue.dispatch()}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print('queue: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Command cancelled. An existing queue worker continues; use run_queue.py stop to pause it.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
