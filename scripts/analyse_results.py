#!/usr/bin/env python3
"""Discover, select, preview, publish and reproduce offline thesis analyses."""
import argparse
import json
from pathlib import Path

from framework import analysis_workspace as workspace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    catalog = commands.add_parser('catalog', help='list queue and imported exports; verify output tables')
    catalog.add_argument('--exports-root', type=Path)
    commands.add_parser('recipes', help='list supported recipes and their purpose')
    for name, help_text in [('select', 'freeze a campaign/filter selection'), ('inspect', 'show available controls, run keys and timing metrics')]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument('--export', action='append', required=True)
        command.add_argument('--exports-root', type=Path)
        command.add_argument('--campaign')
        command.add_argument('--filter', action='append', default=[], metavar='FIELD=JSON', help='additional archive equality filter; JSON string/number/boolean')
        if name == 'select':
            command.add_argument('--recipe', choices=sorted(workspace.KINDS - {'tls_auth_followup', 'secure_boot_stack'}), required=True)
            command.add_argument('--id')
            command.add_argument('--group-by', action='append', help='domain condition field, e.g. tls_kex; default case_id')
            command.add_argument('--baseline', help='exact generated condition label; default first sorted condition')
            command.add_argument('--treatment', action='append', help='explicit changed control field; never guessed')
            command.add_argument('--comparison', type=Path, help='existing comparison JSON, instead of grouping options')
            command.add_argument('--domain', action='append', choices=list(workspace.comparison.DOMAINS), help='domains for the comparison recipe')
            command.add_argument('--network-selection', type=Path)
            command.add_argument('--energy-selection', type=Path)
            command.add_argument('--no-figures', action='store_true')
            command.add_argument('--output', type=Path, required=True)
    imported = commands.add_parser('import', help='archive explicit retained folders; no acquisition')
    imported.add_argument('--source', action='append', type=Path, required=True)
    imported.add_argument('--annotations', type=Path, help='existing energy/network boundary annotations')
    imported.add_argument('--output', type=Path)
    preview = commands.add_parser('preview', help='review audit and tables without publishing')
    preview.add_argument('--spec', type=Path, required=True)
    publish = commands.add_parser('publish', help='write a fresh immutable report revision')
    publish.add_argument('--spec', type=Path, required=True)
    publish.add_argument('--name', default='analysis')
    publish.add_argument('--output', type=Path)
    verify = commands.add_parser('verify', help='check outputs, optionally also original sources')
    verify.add_argument('report', type=Path)
    verify.add_argument('--verify-sources', action='store_true')
    rebuild = commands.add_parser('rebuild', help='require unchanged sources/code/environment and identical scientific CSV/LaTeX')
    rebuild.add_argument('report', type=Path)
    rebuild.add_argument('--output', type=Path, required=True)
    ram = commands.add_parser('ram-budget', help='publish configured RAM budgets from retained report ELFs')
    ram.add_argument('--report', type=Path, required=True)
    ram.add_argument('--selection', action='append', required=True)
    ram.add_argument('--output', type=Path, required=True)
    dist = commands.add_parser('authentication-distribution', help='render fixed-KEx authentication boxplots from published run observations')
    dist.add_argument('--report', type=Path, required=True)
    dist.add_argument('--output', type=Path, required=True)
    review = commands.add_parser('chapter5-review', help='publish pinned timing-stage, loss-outcome and sampled-power diagnostics')
    review.add_argument('--report', type=Path, required=True)
    review.add_argument('--output', type=Path, required=True)
    observed = commands.add_parser('observed-ram', help='derive RAM demand from recorded regional peaks, excluding identified experiment storage')
    observed.add_argument('--report', type=Path, required=True)
    observed.add_argument('--selection', action='append', required=True)
    observed.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'observed-ram':
            from framework.observed_ram import publish as publish_ram_observed
            value = publish_ram_observed(args.report, args.selection, args.output)
        elif args.action == 'chapter5-review':
            from framework.chapter5_review import publish as publish_review
            value = publish_review(args.report, args.output)
        elif args.action == 'authentication-distribution':
            from framework.authentication_distribution import publish as publish_distribution
            value = publish_distribution(args.report, args.output)
        elif args.action == 'ram-budget':
            from framework.ram_budget_report import publish as publish_ram
            value = publish_ram(args.report, args.selection, args.output)
        elif args.action == 'catalog':
            value = workspace.catalogue(args.exports_root)
        elif args.action == 'recipes':
            value = workspace.recipes()
        elif args.action in ('select', 'inspect'):
            filters = {'campaign_id': args.campaign} if args.campaign else {}
            for expression in args.filter:
                key, separator, raw = expression.partition('=')
                if not separator or key in filters:
                    raise ValueError('filters need distinct FIELD=JSON expressions')
                filters[key] = json.loads(raw)
            if not filters:
                raise ValueError('choose a campaign or explicit filters')
            if args.action == 'inspect':
                value = workspace.describe(args.export, filters, directory=args.exports_root)
            else:
                request = dict(id=args.id or args.recipe, kind=args.recipe, filters=filters)
                for key in ('group_by', 'baseline', 'treatment'):
                    if getattr(args, key) is not None:
                        request[key] = getattr(args, key)
                if args.domain:
                    request['domains'] = args.domain
                for key, filename in [('comparison', args.comparison), ('network', args.network_selection), ('energy', args.energy_selection)]:
                    if filename:
                        request[key] = json.loads(filename.read_text())
                value = workspace.draft(args.export, [request], directory=args.exports_root,
                    presentation={'figures': []} if args.no_figures else None)
                workspace.save_selection(value, args.output)
        elif args.action == 'import':
            output, archive = workspace.import_sources(args.source, output=args.output,
                annotations=json.loads(args.annotations.read_text()) if args.annotations else None)
            value = dict(output=str(output), rows=archive['rows'], captures=archive['capture_rows'])
        elif args.action == 'preview':
            audit = workspace.selection_audit(args.spec)
            print(json.dumps({'selection_audit': audit}, indent=2))
            prepared = workspace.prepare(args.spec)
            value = {k: prepared[k] for k in ('tables', 'metrics')}
        elif args.action in ('publish', 'rebuild'):
            if args.action == 'publish':
                output, report = workspace.publish(args.spec, name=args.name, output=args.output)
            else:
                output, report = workspace.rebuild(args.report, output=args.output)
            value = dict(output=str(output), tables=len(report['tables']), figures=len(report['figures']))
        else:
            workspace.verify(args.report, verify_sources=args.verify_sources)
            value = dict(status='verified', scope='outputs_and_sources' if args.verify_sources else 'outputs_only')
        print(json.dumps(value, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, 'Analysis failed: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
