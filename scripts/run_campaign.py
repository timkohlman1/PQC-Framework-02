#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framework.campaign_executor import CampaignError, CampaignExecutor
from framework.config_resolver import ResolutionError
from framework.run_console import RunStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute a canonical PQC experiment campaign")
    parser.add_argument("campaign", nargs="?", help="campaign id or configs/campaigns YAML path")
    parser.add_argument("--results-root", type=Path, default=Path("results/campaigns"))
    parser.add_argument("--resume", type=Path, default=None, help="resume an existing campaign-manifest.json")
    parser.add_argument("--pause-file", type=Path, help="cooperative pause request; operations finish before cleanup")
    parser.add_argument("--stop-on-error", action="store_true", help="pause at the first failed attempt/setup")
    parser.add_argument("--preserve-completed", action="store_true", help="validate completed slots against their original preparations when resume rebuilds an image")
    parser.add_argument("--defer-failed", action="store_true", help="preserve failed/blocked slots on resume for later review, without accepting them; explicit retry overrides this")
    decisions = parser.add_mutually_exclusive_group()
    decisions.add_argument("--accept-failed", action="store_true", help="resume while retaining failed outcomes without repeating them")
    decisions.add_argument("--retry-failed", action="store_true", help="resume including previously accepted failed attempts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resume is None and not args.campaign:
        print("campaign is required unless --resume is supplied", file=sys.stderr)
        return 2
    if (args.accept_failed or args.retry_failed) and args.resume is None:
        print("failure decisions require --resume", file=sys.stderr)
        return 2
    campaign = args.campaign
    if args.resume is not None and campaign is None:
        try:
            state = json.loads(args.resume.read_text(encoding="utf-8"))
            source = state.get("source")
            campaign = (SCRIPT_DIR.parent / source).resolve() if isinstance(source, str) and source else source
        except (OSError, json.JSONDecodeError) as exc:
            print(f"cannot read resume manifest: {exc}", file=sys.stderr)
            return 2
    try:
        executor = CampaignExecutor(
            SCRIPT_DIR.parent, results_root=args.results_root, pause_file=args.pause_file,
            stop_on_error=args.stop_on_error, accept_failed=args.accept_failed,
            retry_failed=args.retry_failed, preserve_completed=args.preserve_completed,
            defer_failed=args.defer_failed,
        )
        manifest = executor.execute(campaign, resume_manifest=args.resume)
    except (CampaignError, ResolutionError) as exc:
        print(f"campaign execution failed: {exc}", file=sys.stderr)
        return 1
    state = json.loads(manifest.read_text(encoding="utf-8"))
    summary = state.get("summary", {})
    executor._diagnostic(manifest.parent, f"Manifest: {manifest}; summary: {summary}")
    if state["state"] == "paused":
        print("Campaign paused after cleanup: " + str(manifest), flush=True)
        return 75
    progress = RunStatus()
    finished = sum(summary.get(key, 0) for key in ("completed", "failed", "blocked"))
    progress.start(state["campaign_id"], finished, summary.get("planned", 0), label="campaign")
    progress.finish("Success" if state["state"] == "completed" else "Failed")
    return 1 if state["state"] == "completed_with_failures" else 0


if __name__ == "__main__":
    raise SystemExit(main())
