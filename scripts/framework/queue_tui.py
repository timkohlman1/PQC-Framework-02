"""Responsive full-screen terminal interface, using Linux's standard curses UI."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import curses
import re
import sys
import time
from datetime import datetime

from framework.run_queue import DONE, HISTORY, framework_version, log_tail

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def visible(value):
    return ''.join(c if c.isprintable() else ' ' for c in ANSI.sub('', str(value)))


def run(queue):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('the UI requires a terminal; use profiles/add/list commands for scripts')
    return curses.wrapper(lambda screen: Terminal(screen, queue).run())


class Terminal:
    def __init__(self, screen, queue):
        self.screen, self.queue = screen, queue
        self.tab = 0
        self.cursor = [0, 0, 0]
        self.profiles = []
        self.picked = set()
        self.filter = ''
        self.message = 'Loading campaign catalogue…'
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = self.pool.submit(queue.catalogue)
        self.operation = 'catalogue'
        self.control_pool = ThreadPoolExecutor(max_workers=1)
        self.shutdown_future = None
        self.exit_requested = False
        self.version_pool = ThreadPoolExecutor(max_workers=1)
        self.version_future = None
        self.version = {'label': 'checking…', 'date': 'unknown'}
        self.next_version_check = 0
        self.gateway_pool = ThreadPoolExecutor(max_workers=1)
        self.gateway_future = None
        self.gateways = []
        self.gateway_error = ''
        self.next_gateway_check = 0
        self.next_jobs_check = 0
        self.rows = []
        self.jobs = []
        screen.keypad(True)
        screen.timeout(150)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for pair, foreground in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN,
                                               curses.COLOR_YELLOW, curses.COLOR_RED,
                                               curses.COLOR_WHITE), start=1):
                curses.init_pair(pair, foreground, -1)

    def ink(self, pair):
        return curses.color_pair(pair) if curses.has_colors() else 0

    def put(self, y, x, value, style=0):
        height, width = self.screen.getmaxyx()
        if y < 0 or y >= height or x >= width - 1:
            return
        try:
            self.screen.addnstr(y, x, visible(value), max(0, width-x-1), style)
        except curses.error:
            pass

    def prompt(self, label):
        value = ''
        while True:
            height, width = self.screen.getmaxyx()
            self.screen.move(height-2, 0)
            self.screen.clrtoeol()
            self.put(height-2, 2, label + value + '▏', self.ink(1))
            self.screen.refresh()
            key = self.screen.getch()
            if key in (10, 13):
                return value
            if key == 27:
                return None
            if key in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif 32 <= key < 127 and len(value) < 160:
                value += chr(key)

    def background(self, operation, function, *args):
        if self.future is not None:
            raise ValueError('a catalogue/plan/export operation is already in progress')
        self.operation = operation
        self.future = self.pool.submit(function, *args)
        self.message = operation.capitalize() + ' in progress…'

    def poll(self):
        if self.shutdown_future is not None and self.shutdown_future.done():
            try:
                self.shutdown_future.result()
                self.exit_requested = True
            except Exception as exc:
                self.message = str(exc)
                self.shutdown_future = None
        if self.future is not None and self.future.done():
            try:
                result = self.future.result()
                if self.operation == 'catalogue':
                    self.profiles = result
                    self.message = f'{len(result)} campaign profiles. Space to select; a to enqueue.'
                elif self.operation == 'purge':
                    self.message = 'Entry and job files permanently deleted; combined exports retained.'
                elif self.operation == 'export':
                    self.message = f"Exported {result['rows']} rows → {result['output']}/analysis.ipynb"
                else:
                    self.picked.clear()
                    self.message = 'Added to queue: ' + ', '.join(result)
            except Exception as exc:
                self.message = str(exc)
            self.future = None
        now = time.monotonic()
        if self.version_future is not None and self.version_future.done():
            self.version = self.version_future.result()
            self.version_future = None
            self.next_version_check = now + 5
        if self.version_future is None and now >= self.next_version_check:
            self.version_future = self.version_pool.submit(framework_version, self.queue.root)
        if self.gateway_future is not None and self.gateway_future.done():
            try:
                self.gateways = self.gateway_future.result()
                self.gateway_error = ''
            except Exception:
                self.gateway_error = 'Gateway status unavailable (check failed)'
            self.gateway_future = None
            self.next_gateway_check = now + 5
        if self.gateway_future is None and now >= self.next_gateway_check:
            self.gateway_future = self.gateway_pool.submit(self.queue.gateway_statuses)
        if now >= self.next_jobs_check:
            self.jobs = self.queue.display_jobs()
            self.next_jobs_check = now + 1
        if self.tab == 0:
            self.rows = [r for r in self.profiles if self.filter.lower() in r['profile'].lower()]
        elif self.tab == 1:
            self.rows = [r for r in self.jobs if r['status'] not in HISTORY]
        else:
            self.rows = [r for r in self.jobs if r['status'] in HISTORY]
        self.cursor[self.tab] = min(self.cursor[self.tab], max(0, len(self.rows)-1))

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        minimum_height = 28 + max(0, len(self.gateways)-1)
        if height < minimum_height or width < 120:
            self.put(1, 1, f'PQC Queue — resize terminal to at least 120 × {minimum_height}. q exits.')
            self.screen.refresh()
            return
        self.put(0, 2, f"PQC / EXPERIMENT QUEUE - Framework Version {self.version['label']} {self.version['date']} | Today {datetime.now():%Y-%m-%d}", self.ink(1) | curses.A_BOLD)
        dispatch = self.queue.dispatch()
        self.put(1, 2, f'{dispatch.upper()}  ·  {len(self.jobs)} entries  ·  {sum(r["selected"] for r in self.jobs)} marked for export  ·  * dirty checkout', self.ink(2) if dispatch == 'running' else self.ink(3))
        gateway_lines = self.gateways or [{'gateway': 'Gateways', 'status': 'CHECKING…', 'hostname': ''}]
        for index, gateway in enumerate(gateway_lines):
            status = gateway['status']
            label = status + (' - ' + gateway['hostname'] if status == 'IN USE' else '')
            self.put(2+index, 2, self.gateway_error or f"{gateway['gateway']}: {label}",
                     self.ink(2 if status == 'READY' else 3 if status == 'IN USE' else 4))
        extra = len(gateway_lines)-1
        labels = ['1 Profiles', '2 Queue', '3 Completed']
        x = 2
        for i, label in enumerate(labels):
            self.put(3+extra, x, ' ' + label + ' ', curses.A_REVERSE | curses.A_BOLD if i == self.tab else self.ink(1))
            x += 19
        self.put(4+extra, 2, '─' * (width-4), self.ink(1))
        self.put(5+extra, 2, '   CAMPAIGN                                      REPS   CASES  ATTEMPTS' if self.tab == 0
                 else '   ID            CAMPAIGN                  VERSION       REPS   OK/ERR/TOTAL  STATE' if self.tab == 1
                 else '   CAMPAIGN                  VERSION   FINISHED (LOCAL)      OK/ERR/REPEAT  EXPORTED  STATE')
        usable = max(1, height-25-extra)
        cursor = self.cursor[self.tab]
        offset = max(0, cursor-usable+1)
        for i, row in enumerate(self.rows[offset:offset+usable], start=offset):
            if self.tab == 0:
                mark = '●' if row['profile'] in self.picked else '○'
                line = f"{mark}  {row['profile']:<44.44} {row.get('repetitions',0):>5} {row.get('conditions',0):>7} {row.get('attempts',0):>9}"
                colour = 4 if row.get('error') else 5
            else:
                mark = '●' if row['selected'] else '○'
                progress = f"{row['success']}/{row['attempts']}" if row['progress_available'] else '?'
                if self.tab == 1:
                    counts = f"{row['success']}/{row['errors']}/{row['attempts']}" if row['progress_available'] else '?'
                    line = f"{mark}  {row['id']}  {row['profile']:<25.25} {row['version']:<9.9} {progress:>9}  {counts:>12}  {row['status']}"
                else:
                    finished = datetime.fromtimestamp(row['completed_at']).strftime('%Y-%m-%d %H:%M:%S') if row['completed_at'] else 'unknown'
                    counts = f"{row['success']}/{row['errors']}/{row['repeats']}" if row['progress_available'] else '?'
                    line = f"{mark}  {row['profile']:<25.25} {row['version']:<9.9} {finished}  {counts:>13}  {'YES' if row['exported'] else 'NO':<8}  {row['status']}"
                colour = 4 if row['status'] == 'attention' else 3 if row['status'] in {'paused','pausing'} else 2
            self.put(6+extra+i-offset, 2, line, self.ink(colour) | (curses.A_REVERSE if i == cursor else 0))
        if not self.rows:
            self.put(7+extra, 4, 'No entries. Add campaign profiles from the Profiles tab.', self.ink(3))
        y = height-19
        if self.rows:
            row = self.rows[cursor]
            if self.tab == 0:
                self.put(y, 2, row.get('error') or f"{row.get('workload')} · repetitions per condition; thesis energy policy")
                self.put(y+1, 2, f'Filter: {self.filter or "all profiles"} · {len(self.picked)} selected')
            else:
                self.put(y, 2, row['detail'] or f"{row['conditions']} conditions × {row['repetitions']} repetitions = {row['attempts']} attempts")
                stats = f"Success {row['success']} / Errors {row['errors']} / Total {row['attempts']} / Repeats {row['repeats']}" if row['progress_available'] else 'Progress unavailable: inspect campaign evidence'
                self.put(y+1, 2, f"{row['id']}  {row['profile']} · {stats}")
        self.put(y+2, 2, '─ Log ' + '─' * (width-10), self.ink(1))
        if self.rows and self.tab != 0:
            for i, line in enumerate(log_tail(self.queue, self.rows[cursor]['id'], 8)):
                self.put(y+3+i, 2, line)
        self.put(y+11, 2, '─' * (width-4), self.ink(1))
        message = 'Pausing and quitting: waiting for the current operation, cleanup and worker exit…' if self.shutdown_future is not None else self.message
        self.put(height-6, 2, message, self.ink(3))
        hints = ('Space select  a add  / filter  R refresh' if self.tab == 0 else
                 'Space mark completed  e export  t retry failures  D permanently delete job files' if self.tab == 2 else
                 'p pause  r resume  t retry  f accept failures  K/J move  d remove (keep files)')
        self.put(height-4, 2, hints, self.ink(1))
        self.put(height-2, 2, 'Tab switch  ↑/↓ navigate  s start queue  x pause queue  q detach  Q pause and quit', self.ink(1))
        self.screen.refresh()

    def key(self, key):
        if self.shutdown_future is not None:
            return
        if key == ord('Q'):
            self.shutdown_future = self.control_pool.submit(self.queue.shutdown)
            return
        row = self.rows[self.cursor[self.tab]] if self.rows else None
        if key in (ord('1'), ord('2'), ord('3')):
            self.tab = key-ord('1')
        elif key == 9:
            self.tab = (self.tab+1) % 3
        elif key in (curses.KEY_UP, ord('k')):
            self.cursor[self.tab] = max(0, self.cursor[self.tab]-1)
        elif key in (curses.KEY_DOWN, ord('j')):
            self.cursor[self.tab] = min(max(0, len(self.rows)-1), self.cursor[self.tab]+1)
        elif key == ord('s'):
            self.queue.start()
            self.message = 'Queue started. Detaching leaves the worker running.'
        elif key == ord('x'):
            self.queue.stop()
            self.message = 'Queue will stop at the next safe breakpoint.'
        elif key == ord('R') and self.tab == 0:
            self.background('catalogue', self.queue.catalogue)
        elif key == ord('/') and self.tab == 0:
            value = self.prompt('Filter profiles (blank = all): ')
            if value is not None:
                self.filter = value
                self.cursor[0] = 0
        elif key == ord(' ') and row:
            if self.tab == 0:
                if row.get('error'):
                    raise ValueError(row['error'])
                if row['profile'] in self.picked:
                    self.picked.remove(row['profile'])
                else:
                    self.picked.add(row['profile'])
            elif self.tab == 2:
                self.queue.mark(row['id'])
        elif key == ord('a') and self.tab == 0:
            names = [r['profile'] for r in self.profiles if r['profile'] in self.picked]
            if not names and row:
                names = [row['profile']]
            if not names:
                raise ValueError('select a campaign first')
            value = self.prompt('Repetitions per condition (Enter = each profile default): ')
            if value is not None:
                self.background('add', self.queue.add, names, int(value) if value.strip() else None)
        elif key == ord('d') and row and self.tab == 1:
            self.queue.remove(row['id'])
            self.next_jobs_check = 0
            self.message = 'Removed from queue; retained files are on Completed.'
        elif key == ord('D') and row and self.tab == 2:
            value = self.prompt(f"Permanently delete job files (exports kept). Type {row['id']}: ")
            if value == row['id']:
                self.background('purge', self.queue.purge, row['id'], value)
            else:
                self.message = 'Deletion cancelled.'
        elif key == ord('e'):
            self.background('export', self.queue.export)
        elif row and self.tab != 0:
            if key == ord('p'):
                self.queue.pause(row['id'])
            elif key in (ord('r'), ord('t'), ord('f')):
                action = {ord('r'): 'resume', ord('t'): 'retry', ord('f'): 'accept'}[key]
                self.queue.decide(row['id'], action)
                self.message = action.capitalize() + ' queued; failed outcomes remain recorded.'
            elif key in (ord('K'), ord('J')):
                self.queue.move(row['id'], 'up' if key == ord('K') else 'down')

    def run(self):
        try:
            while True:
                self.poll()
                if self.exit_requested:
                    return 0
                self.draw()
                key = self.screen.getch()
                if key == ord('q'):
                    return 0
                try:
                    self.key(key)
                except (ValueError, OSError) as exc:
                    self.message = str(exc)
        finally:
            self.pool.shutdown(wait=True)
            self.gateway_pool.shutdown(wait=True)
            self.version_pool.shutdown(wait=True)
            self.control_pool.shutdown(wait=True)
