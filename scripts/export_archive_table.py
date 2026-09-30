#!/usr/bin/env python3
"""Export pandas-ready experiment and individual-handshake rows from a retained results archive."""
import argparse
import json
from pathlib import Path
from framework.archive_table import export_archive, load_archive

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--results-root',type=Path)
    source.add_argument('--check',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--annotations',type=Path,help='Explicit electrical boundary and device-IP assertions for this selection')
    p.add_argument('--verify-sources',action='store_true')
    a=p.parse_args(argv)
    if a.check and (a.output or a.annotations): p.error('--check does not accept export options')
    if not a.check and (not a.output or a.verify_sources): p.error('export requires --output; --verify-sources requires --check')
    try:
        if a.check:
            frame=load_archive(a.check,verify_sources=a.verify_sources)
            print(json.dumps({'status':'verified','rows':len(frame),'columns':len(frame.columns)}))
        else:
            meta=export_archive(results_root=a.results_root,output=a.output,
                annotations=json.loads(a.annotations.read_text()) if a.annotations else None)
            print(json.dumps({'status':'exported','rows':meta['rows'],'columns':len(meta['columns']),'output':str(a.output)}))
        return 0
    except (ValueError,OSError,KeyError) as exc:
        print('archive-table: '+str(exc));return 2
if __name__=='__main__': raise SystemExit(main())
