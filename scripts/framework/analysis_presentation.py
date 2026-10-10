"""Publication figures from the exact full-precision thesis-table statistics."""
import html
import math
import re
import textwrap
from pathlib import Path


def validate(options):
    if not isinstance(options, dict) or set(options) - {'figures', 'labels', 'order', 'width_inches', 'tables', 'captions', 'measurements'}:
        raise ValueError('unknown presentation options')
    for key in ('figures', 'order', 'tables', 'measurements'):
        values = options.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values) or len(values) != len(set(values)):
            raise ValueError(key + ' must be a list of distinct names')
    labels = options.get('labels', {})
    if not isinstance(labels, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in labels.items()):
        raise ValueError('labels must map original condition names to non-empty display labels')
    captions = options.get('captions', {})
    if not isinstance(captions, dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in captions.items()):
        raise ValueError('captions must map table IDs to nonempty strings')
    width = options.get('width_inches', 6.5)
    if type(width) not in (int, float) or not math.isfinite(width) or not 3 <= width <= 16:
        raise ValueError('width_inches must be between 3 and 16')


def prepare(tables, metrics, spec):
    """Record the statistic displayed by each existing table; never reaggregate."""
    options = spec.get('presentation', {})
    validate(options)
    kinds = {item['id']: item['kind'] for item in spec['selections']}
    by_id = {table['id']: table for table in tables}
    labels = options.get('labels', {})
    order = {name: i for i, name in enumerate(options.get('order', []))}
    available = {row['metric'] for row in metrics}
    if set(options.get('figures', [])) - available:
        raise ValueError('figure metrics unavailable in selected recipes: ' + ', '.join(sorted(set(options['figures']) - available)))
    known_labels = {row[0] for table in tables for row in table['rows']}
    if (set(labels) | set(order)) - known_labels:
        raise ValueError('presentation names must match original table condition labels')
    if (set(options.get('tables', [])) | set(options.get('captions', {}))) - set(by_id):
        raise ValueError('unknown presentation table ID')
    for table in tables:
        table['caption'] = options.get('captions', {}).get(table['id'], table['caption'])
        table['rows'].sort(key=lambda row: order.get(row[0], len(order)))
        displayed = [labels.get(row[0], row[0]) for row in table['rows']]
        if len(displayed) != len(set(displayed)):
            raise ValueError('display labels would merge distinct conditions')
        for row, label in zip(table['rows'], displayed):
            row[0] = label
    for row in metrics:
        if 'reported_statistic' in row:
            continue
        kind = kinds[by_id[row['table']]['selections'][0]]
        if row['metric'] == 'success':
            statistic = 'success_fraction'
            value = row['successes'] / row['attempts'] if row['attempts'] else None
        else:
            statistic = ('value' if row['scope'] == 'static' else 'maximum' if row['scope'] in ('runtime', 'stack')
                         else 'median' if kind == 'network_loss' else 'mean')
            value = None if row['reason'] else row.get(statistic)
        row.update(reported_statistic=statistic, reported_value=value)
    if options.get('tables'):
        tables[:] = [by_id[name] for name in options['tables']]
        metrics[:] = [row for row in metrics if row['table'] in options['tables']]


def figure_rows(tables, metrics, options):
    """Loss conditions keep their configured percentage and all-attempt counts."""
    rows = []
    labels = options.get('labels', {})
    for item in metrics:
        if item['metric'] not in options.get('figures', []):
            continue
        condition = item['condition']
        base, separator, loss = condition.partition('; loss=')
        label = labels.get(base, base) + ('; configured loss=' + loss + '%' if separator else '')
        value = item['reported_value']
        statistic = item['reported_statistic']
        low = high = None
        uncertainty = 'none'
        if value is not None and statistic == 'mean' and item.get('sd') is not None:
            low, high, uncertainty = value - item['sd'], value + item['sd'], 'sample SD (not a confidence interval)'
        elif value is not None and statistic == 'median':
            low, high = item.get('q1'), item.get('q3')
            uncertainty = 'IQR (not a confidence interval)' if low is not None and high is not None else 'none'
        rows.append(dict(table=item['table'], metric=item['metric'], condition=condition,
            label=label, statistic=statistic, value=value, unit='fraction' if statistic == 'success_fraction' else item['unit'],
            low=low, high=high, uncertainty=uncertainty, n=item['n'],
            attempts=item.get('attempts'), successes=item.get('successes'), reason=item.get('reason'),
            sample_unit=item.get('sample_unit', 'captures supporting build fact' if item.get('scope') == 'static' else 'captures'),
            n_runs=item.get('n_runs'),
            loss_percent=item.get('loss_percent'), series=labels.get(base, base)))
    ordering = {label: i for i, label in enumerate(options.get('order', []))}
    rows.sort(key=lambda r: (r['table'], r['metric'], ordering.get(r['condition'].partition('; loss=')[0], len(ordering))))
    return rows


def render(directory, tables, metrics, options):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from framework.thesis_tables import write_csv

    directory = Path(directory)
    rows = figure_rows(tables, metrics, options)
    if not rows:
        return []
    write_csv(directory / 'figure-data.csv', rows)
    figures = []
    for table, metric in sorted({(r['table'], r['metric']) for r in rows}):
        from framework.analysis_comparison import identifier
        safe_metric = identifier(metric) if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in metric) or len(metric)>80 else metric
        selected = [r for r in rows if (r['table'], r['metric']) == (table, metric)]
        if all(r['loss_percent'] is not None for r in selected):
            name = f'figure-{table}-{safe_metric}-1'
            fig, ax = plt.subplots(figsize=(options.get('width_inches', 6.5), 4.5), layout='constrained')
            losses = sorted({r['loss_percent'] for r in selected})
            for series in dict.fromkeys(r['series'] for r in selected):
                points = {r['loss_percent']: r for r in selected if r['series'] == series}
                values = [points[x]['value'] if x in points and points[x]['value'] is not None else float('nan') for x in losses]
                line, = ax.plot(losses, values, marker='o', markersize=4, label=series)
                for x, row in points.items():
                    if row['value'] is not None and row['low'] is not None:
                        ax.plot([x, x], [row['low'], row['high']], color=line.get_color())
            statistic = selected[0]['statistic']
            heading = options.get('captions', {}).get(table, re.sub(r'\.[0-9a-f]{16}$', '', metric).replace('_', ' ').replace('.', ' / '))
            title = heading + ' — ' + statistic.replace('_', ' ')
            ax.set(xlabel='Configured packet loss (%)', ylabel=selected[0]['unit'])
            ax.set_title('\n'.join(textwrap.wrap(title, 45)), fontsize=10)
            if statistic == 'success_fraction':
                ax.set_ylim(-.03, 1.03)
            ax.grid(alpha=.2)
            ax.legend(fontsize=8)
            note = next(t['notes'] for t in tables if t['id'] == table)
            caption = title + '. Missing observations break the line; counts are in figure-data.csv and the matching tables. '
            if statistic == 'median':
                caption += 'Bars show IQR, not confidence intervals. '
            caption += note
            for extension in ('svg', 'pdf', 'png'):
                fig.savefig(directory / (name + '.' + extension), dpi=200)
            plt.close(fig)
            figures.append(dict(id=name, table=table, metric=metric, caption=caption))
            continue
        # Paginate long loss grids; preserve every condition, including unavailable cells.
        for start in range(0, len(selected), 18):
            page = selected[start:start + 18]
            name = f'figure-{table}-{safe_metric}-{start // 18 + 1}'
            height = max(2.6, sum(max(1, len(textwrap.wrap(r['label'], 43))) * .19 + .25 for r in page) + 1.3)
            fig, ax = plt.subplots(figsize=(options.get('width_inches', 6.5), height), layout='constrained')
            for i, row in enumerate(page):
                if row['value'] is None:
                    ax.text(.02, i, 'unavailable', transform=ax.get_yaxis_transform(), va='center', color='gray', fontsize=8)
                    continue
                ax.scatter(row['value'], i, color='#16697a', s=24)
                if row['low'] is not None:
                    ax.plot([row['low'], row['high']], [i, i], color='#16697a', linewidth=1.3)
            tick_labels = [r['label'] + (f" ({r['successes']}/{r['attempts']})" if r['statistic'] == 'success_fraction'
                           else f" (captures={r['n']})" if r['statistic'] == 'value' else f" (n={r['n']}; {r['sample_unit']})") for r in page]
            tick_labels = ['\n'.join(textwrap.wrap(label, 43)) for label in tick_labels]
            ax.set_yticks(range(len(page)), tick_labels, fontsize=8)
            ax.invert_yaxis()
            statistic = page[0]['statistic']
            heading = options.get('captions', {}).get(table, re.sub(r'\.[0-9a-f]{16}$', '', metric).replace('_', ' ').replace('.', ' / '))
            title = heading + ' — ' + statistic.replace('_', ' ')
            ax.set_title('\n'.join(textwrap.wrap(title, 40)), fontsize=10)
            ax.set_xlabel(page[0]['unit'])
            ax.grid(axis='x', alpha=.2)
            if statistic == 'success_fraction':
                ax.set_xlim(-.03, 1.03)
            note = next(t['notes'] for t in tables if t['id'] == table)
            uncertainty = sorted({r['uncertainty'] for r in page if r['uncertainty'] != 'none'})
            caption = title + '. ' + ('; '.join(uncertainty) + '. ' if uncertainty else '') + note
            for extension in ('svg', 'pdf', 'png'):
                fig.savefig(directory / (name + '.' + extension), dpi=200)
            plt.close(fig)
            figures.append(dict(id=name, table=table, metric=metric, caption=caption))
    return figures


def html_figures(figures):
    return '\n'.join('<figure><img style="max-width:100%" src="' + f['id'] + '.svg" alt="' + html.escape(f['caption'], quote=True) + '"><figcaption>' + html.escape(f['caption']) + '</figcaption><p>' + ' · '.join('<a href="' + f['id'] + '.' + ext + '">' + ext.upper() + '</a>' for ext in ('pdf', 'svg', 'png')) + '</p></figure>' for f in figures)
