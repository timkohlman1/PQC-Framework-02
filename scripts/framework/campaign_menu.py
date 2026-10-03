"""Menu-style campaign view/editor for the stdlib host terminal."""
from __future__ import annotations

import copy
import curses


def get(data, path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def put(data, path, value):
    parent = data
    for key in path[:-1]:
        parent = parent.setdefault(key, {})
    if value is None:
        parent.pop(path[-1], None)
    else:
        parent[path[-1]] = value


def fields(options):
    result = [('Campaign', 'ID', ['id'], 'text', None),
              ('Campaign', 'Description', ['description'], 'text', None)]
    for name in ('target', 'gateway', 'workload'):
        result.append(('Components', name.replace('_', ' ').title(), [name], 'single', options[name]))
    for name in ('experiment_broker', 'reporting_broker'):
        result.append(('Components', name.replace('_', ' ').title(), ['services', name], 'single', options['broker']))
    result.append(('Components', 'Energy instrument', ['instruments', 'energy'], 'single', [None, *options['energy']]))
    for name in ('tls_kex', 'tls_auth', 'secure_boot', 'network_condition', 'auth_mode',
                 'mqtt_transport', 'firmware_mode', 'standby_signing_keys',
                 'boot_stack_profiling', 'boot_uart_diagnostics'):
        result.append(('Factors / matrix', name.replace('_', ' ').title(), [name], 'factor', [None, *options[name]]))
    for key, label in (('transfer.payload_bytes', 'Payload bytes'), ('transfer.chunk_bytes', 'Chunk bytes'),
                       ('iterations.operations_per_run', 'Benchmark operations per run'),
                       ('iterations.handshakes_per_run', 'TLS handshakes per run')):
        result.append(('Workload parameters', label, ['matrix', 'workload.' + key], 'integers', None))
    result.append(('Workload parameters', 'UART output', ['matrix', 'workload.uart_output_mode'],
                   'multi', [None, 'disabled', 'minimal', 'full']))
    result.extend([('Execution', 'Repetitions per condition', ['execution', 'repetitions'], 'integer', None),
                   ('Execution', 'Reset between runs', ['execution', 'reset_between_runs'], 'single', ['hardware_reset', 'none'])])
    for key, value in {'build': 'once_per_firmware_identity', 'flash': 'once_per_firmware_identity',
                       'experiment_broker': 'reuse_if_compatible', 'reporting_broker': 'always_available',
                       'condition': 'retain_within_condition', 'evidence': 'per_run'}.items():
        result.append(('Execution', key.replace('_', ' ').title(), ['execution', key], 'single', [value]))
    result.append(('Analysis', 'Authentication baseline', ['analysis_baselines', 'tls_auth'],
                   'single', [None, *options['tls_auth']]))
    return result


def value_for(data, field):
    _, _, path, kind, _ = field
    if kind == 'factor':
        return data.get('matrix', {}).get(path[0], data.get('fixed', {}).get(path[0]))
    return get(data, path)


def apply_value(data, field, value):
    _, _, path, kind, _ = field
    if kind == 'factor':
        key = path[0]
        data.setdefault('fixed', {}).pop(key, None)
        data.setdefault('matrix', {}).pop(key, None)
        if value is not None:
            values = value if isinstance(value, list) else [value]
            if len(values) == 1:
                data['fixed'][key] = values[0]
            else:
                data['matrix'][key] = values
    else:
        put(data, path, value)


def label(value):
    if value is None:
        return '(use default / omit)'
    if isinstance(value, bool):
        return 'enabled' if value else 'disabled'
    if isinstance(value, list):
        return ', '.join(label(v) for v in value)
    return str(value)


class CampaignMenu:
    def __init__(self, terminal, loaded, *, readonly=False):
        self.ui = terminal
        self.loaded = loaded
        self.data = copy.deepcopy(loaded['data'])
        self.readonly = readonly
        self.fields = fields(loaded['options'])
        self.sections = list(dict.fromkeys(f[0] for f in self.fields))
        self.section = None
        self.cursor = 0
        self.message = 'Choose a section. Component profiles are selected, not modified.'

    def draw_list(self, title, rows, cursor, hint):
        screen = self.ui.screen
        screen.erase()
        height, width = screen.getmaxyx()
        self.ui.put(0, 2, title, self.ui.ink(1) | curses.A_BOLD)
        self.ui.put(1, 2, '─' * max(0, width-4), self.ui.ink(1))
        offset = max(0, cursor-max(1, height-7)+1)
        for i, text in enumerate(rows[offset:offset+max(1, height-7)], offset):
            self.ui.put(3+i-offset, 2, text, curses.A_REVERSE if i == cursor else 0)
        self.ui.put(height-3, 2, self.message, self.ui.ink(3))
        self.ui.put(height-2, 2, hint, self.ui.ink(1))
        screen.refresh()

    def call(self, request):
        future = self.ui.pool.submit(self.ui.queue.campaign_editor, request)
        while not future.done():
            self.draw_list('Campaign: ' + request['action'], ['Working…'], 0, 'Please wait')
            self.ui.screen.getch()
        return future.result()

    def choose(self, title, options, current, multiple):
        choices = list(options)
        values = current if isinstance(current, list) else [current]
        for value in values:
            if value not in choices:
                choices.append(value)
        selected = [value for value in values if value in choices]
        cursor = next((i for i, value in enumerate(choices) if value in selected), 0)
        while True:
            rows = [('[*] ' if v in selected else '[ ] ') + label(v) for v in choices]
            self.draw_list(title, rows, cursor, '↑/↓ move  Space toggle  Enter apply  Esc cancel')
            key = self.ui.screen.getch()
            if key == 27:
                return False, None
            if key in (curses.KEY_UP, ord('k')):
                cursor = max(0, cursor-1)
            elif key in (curses.KEY_DOWN, ord('j')):
                cursor = min(len(choices)-1, cursor+1)
            elif key == ord(' '):
                value = choices[cursor]
                if value is None or not multiple:
                    selected = [value]
                elif value in selected:
                    selected.remove(value)
                else:
                    selected = [v for v in selected if v is not None] + [value]
            elif key in (10, 13):
                if not selected:
                    self.message = 'Select at least one option, or choose default/omit.'
                    continue
                return True, None if selected == [None] else selected if multiple else selected[0]

    def edit(self, field):
        _, title, path, kind, options = field
        current = value_for(self.data, field)
        if options is not None:
            accepted, value = self.choose(title, options, current, kind in {'factor', 'multi'})
            if not accepted:
                return
        else:
            text = self.ui.prompt(f'{title} [{label(current)}] (blank keeps; - omits): ')
            if text is None or not text.strip():
                return
            if text.strip() == '-':
                value = None
            elif kind in {'integer', 'integers'}:
                values = [int(part.strip()) for part in text.split(',')]
                if kind == 'integer' and len(values) != 1:
                    raise ValueError('enter one integer')
                value = values[0] if kind == 'integer' else values
            else:
                value = text
        apply_value(self.data, field, value)
        self.message = 'Changed in draft. V validates; S saves; Esc returns.'

    def preview(self):
        text = self.loaded['yaml'] if self.data == self.loaded['data'] else self.call({'action': 'preview', 'data': self.data})['yaml']
        lines = text.splitlines()
        cursor = 0
        while True:
            self.draw_list('Campaign YAML', lines, cursor, '↑/↓ scroll  Esc return')
            key = self.ui.screen.getch()
            if key == 27:
                return
            if key in (curses.KEY_UP, ord('k')):
                cursor = max(0, cursor-1)
            elif key in (curses.KEY_DOWN, ord('j')):
                cursor = min(len(lines)-1, cursor+1)

    def run(self):
        while True:
            entries = self.sections if self.section is None else [f for f in self.fields if f[0] == self.section]
            rows = [f'{s}  →' for s in entries] if self.section is None else [
                f'{f[1]:<32} {label(value_for(self.data, f))}' for f in entries]
            title = ('VIEW' if self.readonly else 'EDIT') + ' CAMPAIGN / ' + (self.loaded['profile'] or 'new campaign')
            if self.section:
                title += ' / ' + self.section
            hint = 'Enter open  Esc back  P contents  e edit' if self.readonly else 'Enter/Space edit  Esc back  P contents  V validate  S save'
            self.draw_list(title, rows, self.cursor, hint)
            key = self.ui.screen.getch()
            try:
                if key == 27:
                    if self.section is not None:
                        self.section = None
                        self.cursor = 0
                    elif self.data != self.loaded['data'] and not self.readonly:
                        if self.ui.prompt('Discard draft? Type yes: ') == 'yes':
                            return False
                    else:
                        return False
                elif key in (curses.KEY_UP, ord('k')):
                    self.cursor = max(0, self.cursor-1)
                elif key in (curses.KEY_DOWN, ord('j')):
                    self.cursor = min(len(entries)-1, self.cursor+1)
                elif key in (10, 13, ord(' ')):
                    if self.section is None:
                        self.section = entries[self.cursor]
                        self.cursor = 0
                    elif not self.readonly:
                        self.edit(entries[self.cursor])
                elif key == ord('e') and self.readonly:
                    self.readonly = False
                elif key in (ord('p'), ord('P')):
                    self.preview()
                elif key in (ord('v'), ord('V')):
                    result = self.call({'action': 'validate', 'data': self.data})
                    self.message = f"Valid: {result['conditions']} conditions × {result['repetitions']} repetitions = {result['attempts']} runs"
                elif key in (ord('s'), ord('S')) and not self.readonly:
                    profile = self.loaded['profile']
                    if not profile:
                        proposed = self.data.get('id', 'new_campaign') + '.yaml'
                        answer = self.ui.prompt(f'Campaign filename [{proposed}]: ')
                        if answer is None:
                            continue
                        profile = answer.strip() or proposed
                    result = self.call({'action': 'save', 'profile': profile, 'sha256': self.loaded['sha256'], 'data': self.data})
                    self.ui.message = f"Saved {result['profile']}: {result['conditions']} conditions, {result['attempts']} runs"
                    return True
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.message = str(exc)
