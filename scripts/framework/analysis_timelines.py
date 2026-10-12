"""Measured examples on one recorded clock; schematics carry no measured durations."""
import re
from pathlib import Path


def validate(items):
    if not isinstance(items, list):
        raise ValueError('timelines must be a list')
    names = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id', 'selection', 'run_key', 'kind', 'epoch_index', 'iteration_id', 'caption'}:
            raise ValueError('timeline requires an explicit run, epoch, iteration, kind and caption')
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,70}', item['id']) or item['id'] in names:
            raise ValueError('invalid or duplicate timeline ID')
        names.add(item['id'])
        if item['kind'] not in ('tls', 'application') or not re.fullmatch(r'[a-f0-9]{64}', item['run_key']):
            raise ValueError('invalid timeline kind or run key')
        if any(type(item[k]) is not int or item[k] < 0 for k in ('epoch_index', 'iteration_id')):
            raise ValueError('timeline epoch and iteration must be nonnegative integers')
        if any(not isinstance(item[k], str) or not item[k].strip() for k in ('selection', 'caption')):
            raise ValueError('timeline selection and caption must be nonempty')


def measured_rows(item, dataset, attribution):
    """Expose original timestamps, never a sequence assembled from medians."""
    runs = [r for r in dataset.runs if r['run_key'] == item['run_key']]
    if len(runs) != 1 or runs[0]['execution_outcome'] != 'completed' or runs[0]['selected_input_status'] != 'verified':
        raise ValueError('timeline requires one successful verified run')
    def matches(r):
        return all(r[k] == item[k] for k in ('run_key', 'epoch_index', 'iteration_id'))
    base = {k:item[k] for k in ('run_key', 'epoch_index', 'iteration_id')}
    if item['kind'] == 'tls':
        rows = [r for r in attribution if matches(r) and r['representation'] == 'invocation' and r['validity'] == 'valid']
        handshake = [r for r in rows if r['operation'] == 'handshake']
        if len(handshake) != 1:
            raise ValueError('timeline requires one unambiguous handshake interval')
        origin, end = handshake[0]['start_us'], handshake[0]['end_us']
        # Protocol phases and selected expensive operations; retain nesting and exact identities.
        rows = [r for r in rows if r['operation'] in ('handshake', 'server_hello', 'encrypted_extensions', 'certificate', 'certificate_verify', 'finished') or
                any(r['operation'].endswith(s) for s in ('_keygen', '_shared_secret', '_decapsulate', '_sign', '_verify'))]
        output = []
        for r in sorted(rows, key=lambda r:(r['start_us'], r['sequence'])):
            if r['clock_source'] != 'TIM2' or r['counter_hz'] != 1000000 or not origin <= r['start_us'] <= r['end_us'] <= end:
                raise ValueError('TLS timeline clock or interval is inconsistent')
            output.append(dict(base, label=r['operation'], start_us=r['start_us'], end_us=r['end_us'],
                plot_start_us=r['start_us']-origin, plot_end_us=r['end_us']-origin,
                source_records=r['source_records'], source_sha256=r['source_sha256'], sequence=r['sequence'],
                parent_sequence=r['parent_sequence'], depth=r['depth'], clock='TIM2', origin='handshake start'))
        return output
    timings = [r for r in dataset.timings if matches(r) and r['metric'] in ('mqtt_readiness','rtfb','rtlb','ttfb','ttlb','req_tfb','req_tlb')]
    by_metric = {r['metric']: r for r in timings}
    if len(by_metric) != 7 or len(timings) != 7 or any(r['validity'] != 'valid' or r['timing_policy_exclusion'] for r in timings):
        raise ValueError('application timeline requires all seven valid timing intervals')
    offsets = {by_metric[m]['reset_offset_us'] for m in ('rtfb', 'rtlb')}
    if len(offsets) != 1 or None in offsets:
        raise ValueError('application timeline requires one validated reset bridge')
    offset = next(iter(offsets))
    output = []
    for metric in ('mqtt_readiness', 'rtfb', 'rtlb', 'ttfb', 'ttlb', 'req_tfb', 'req_tlb'):
        r = by_metric[metric]
        if r['clock_source'] != 'TIM2' or r['counter_hz'] != 1000000:
            raise ValueError('application timeline requires one TIM2 clock')
        shift = 0 if metric in ('rtfb','rtlb') else offset
        output.append(dict(base, label=metric, start_us=r['start_us'], end_us=r['end_us'],
            plot_start_us=r['start_us']+shift, plot_end_us=r['end_us']+shift,
            source_records=r['source_records'], source_sha256=r['source_sha256'],
            clock='TIM2 with validated boot bridge', origin='operational wolfBoot entry'))
    end_first = {r['plot_end_us'] for r in output if r['label'] in ('rtfb','ttfb','req_tfb')}
    end_last = {r['plot_end_us'] for r in output if r['label'] in ('rtlb','ttlb','req_tlb')}
    if len(end_first) != 1 or len(end_last) != 1:
        raise ValueError('application timeline endpoint mismatch')
    return output


def schematic(plt):
    """Logical TLS 1.3 sequence, including optional client authentication."""
    fig, ax = plt.subplots(figsize=(9, 3.6), layout='constrained')
    ax.set(xlim=(-.5, 10), ylim=(-.5, 2.1))
    ax.hlines([0,1.5], 0, 9.5, color='#c4cdd2', lw=1)
    ax.text(-.2, 1.5, 'Client', ha='right', va='center'); ax.text(-.2, 0, 'Broker', ha='right', va='center')
    events = [(0,.9,1.5,'Key share'), (2,2.9,0,'Key agreement'), (3.1,4.2,0,'Authenticate'),
              (5.1,6.4,1.5,'Verify broker'), (6.7,7.6,1.5,'Client auth.*'), (8.6,9.5,0,'Verify client*')]
    for lo,hi,y,label in events:
        ax.broken_barh([(lo,hi-lo)], (y-.12,.24), facecolors='#cde6eb', edgecolors='#16697a')
        ax.text((lo+hi)/2, y+.22, label, ha='center', fontsize=8)
    for x1,x2,y1,y2,label in [(1,1.9,1.5,0,'ClientHello'), (4.3,5,0,1.5,'Server flight'), (7.7,8.5,1.5,0,'Client flight')]:
        ax.annotate('', (x2,y2), (x1,y1), arrowprops=dict(arrowstyle='->',color='#34495e'))
        ax.text((x1+x2)/2, .65, label, rotation=90, va='center', ha='center', fontsize=8)
    ax.text(0,-.4,'Logical order only; not to scale. * Mutual authentication only. Flights include their Finished messages.',fontsize=8)
    ax.axis('off')
    return fig


def publish(directory, prepared):
    from framework.analysis_comparison import dataset_for
    from framework.thesis_tables import write_csv, escape_tex
    items = prepared['specification'].get('presentation', {}).get('timelines', [])
    validate(items)
    if not items: return []
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    figures, cached = [], {}
    directory = Path(directory)
    def save(fig, name, caption, table):
        for ext in ('pdf', 'svg', 'png'):
            fig.savefig(directory / (name+'.'+ext), dpi=180)
        plt.close(fig)
        (directory / (name+'.tex')).write_text('\n'.join([
            r'\begin{figure}[htbp]', r'\centering', r'\includegraphics[width=\linewidth]{figs/results/'+name+'.pdf}',
            r'\caption{'+escape_tex(caption)+r'}\label{fig:'+name+'}', r'\end{figure}', '']))
        figures.append(dict(id=name, table=table, metric='timeline', caption=caption))
    save(schematic(plt), 'timeline-tls-sequence', 'TLS 1.3 client and broker sequence. Logical order only; durations and arrow positions are schematic.', 'timelines')
    for item in items:
        name = item['selection']
        if name not in prepared['selected']:
            raise ValueError('unknown timeline selection')
        if name not in cached: cached[name] = dataset_for(prepared['selected'][name][1])
        frames = prepared['analyses'][name]['frames']
        rows = measured_rows(item, cached[name], frames.get('tls_attribution', {}).get('rows', []))
        write_csv(directory / (item['id']+'.csv'), rows)
        fig, ax = plt.subplots(figsize=(9, max(3, .3*len(rows)+1.2)), layout='constrained')
        for i,r in enumerate(rows):
            lo,hi = r['plot_start_us']/1000,r['plot_end_us']/1000
            color = ('#16697a' if r.get('depth', 0) <= 1 else '#618f45') if item['kind']=='tls' else '#9b5134'
            ax.broken_barh([(lo,hi-lo)], (i-.27,.54), facecolors=color, alpha=.8)
            ax.scatter([lo,hi],[i,i],s=12,color=color)
        labels = [('  ' * r.get('depth', 0)) + r['label'].replace('_',' ') if item['kind']=='tls' else {'mqtt_readiness':'MQTT ready','req_tfb':'ReqTFB','req_tlb':'ReqTLB'}.get(r['label'], r['label'].upper()) for r in rows]
        ax.set_yticks(range(len(rows)), labels, fontsize=8); ax.invert_yaxis()
        ax.set_xlabel('Time from '+rows[0]['origin']+' (ms)'); ax.set_xlim(left=0); ax.grid(axis='x',alpha=.2)
        caption = item['caption'] + ' Measured single-run example ('+item['run_key'][:12]+', epoch '+str(item['epoch_index'])+', iteration '+str(item['iteration_id'])+'). '
        caption += ('Client observations only: broker execution is not timestamped. Nested intervals overlap and are not added.' if item['kind']=='tls' else 'Each bar shares the same run and clock bridge; its endpoints define the named duration. Reset means operational wolfBoot entry.')
        save(fig,item['id'],caption,'timelines')
    return figures
