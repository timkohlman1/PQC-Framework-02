"""Analyse one finalized experiment PCAP without mutating its run manifest."""
from __future__ import annotations

import argparse
from pathlib import Path

from framework.packet_analysis import PacketAnalysisError, write_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Finalized result manifest.json")
    parser.add_argument(
        "--no-tshark",
        action="store_true",
        help="Disable optional tshark/TLS-key-log enrichment; built-in packet analysis still runs.",
    )
    args = parser.parse_args()
    try:
        output, lineage = write_analysis(args.manifest, use_tshark=not args.no_tshark)
    except (OSError, PacketAnalysisError) as exc:
        parser.error(str(exc))
    print(f"Packet analysis: {output}")
    print(f"Lineage: {lineage}")


if __name__ == "__main__":
    main()
