#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from framework.config_resolver import ConfigResolver, ResolutionError

def main() -> int:
    p=argparse.ArgumentParser(description="Expand and resolve a canonical PQC experiment campaign")
    p.add_argument("campaign", help="campaign id or YAML path")
    p.add_argument("--output-root", type=Path)
    args=p.parse_args()
    try:
        root=ConfigResolver(SCRIPT_DIR.parent).materialize_campaign(args.campaign,args.output_root)
    except ResolutionError as exc:
        print(f"configuration resolution failed: {exc}", file=sys.stderr); return 2
    print(root); return 0
if __name__ == "__main__": raise SystemExit(main())
