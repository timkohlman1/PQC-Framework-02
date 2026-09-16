#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framework.campaign_executor import CampaignError, CampaignExecutor
from framework.config_resolver import ResolutionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute a canonical PQC experiment campaign")
    parser.add_argument("campaign", nargs="?", help="campaign id or configs/campaigns YAML path")
    parser.add_argument("--results-root", type=Path, default=Path("results/campaigns"))
    parser.add_argument("--resume", type=Path, default=None, help="resume an existing campaign-manifest.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resume is None and not args.campaign:
        print("campaign is required unless --resume is supplied", file=sys.stderr)
        return 2
    campaign = args.campaign
    if args.resume is not None and campaign is None:
        try:
            import json
            state = json.loads(args.resume.read_text(encoding="utf-8"))
            source = state.get("source")
            campaign = (SCRIPT_DIR.parent / source).resolve() if isinstance(source, str) and source else source
        except (OSError, json.JSONDecodeError) as exc:
            print(f"cannot read resume manifest: {exc}", file=sys.stderr)
            return 2
    try:
        executor = CampaignExecutor(SCRIPT_DIR.parent, results_root=args.results_root)
        manifest = executor.execute(campaign, resume_manifest=args.resume)
    except (CampaignError, ResolutionError) as exc:
        print(f"campaign execution failed: {exc}", file=sys.stderr)
        return 1
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
