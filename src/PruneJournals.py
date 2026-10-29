#!/usr/bin/env python3
"""
Trash clean's undo journals older than the retention window (default 3 days).

Committed clean runs already do this for their own journals; this is the
by-hand path (backlog, other roots, checking what would go).

Usage:
  python -m src.PruneJournals -d /Volumes/Seagate/seagate-qBittorrent            # dry run
  python -m src.PruneJournals -d ROOT -d ROOT2 --commit                          # trash them
  python -m src.PruneJournals -d ROOT --days 7 --service clean-tv                # other window / one service
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import JOURNAL_KEEP_DAYS
from .journal_retention import prune_journals

ALL_SERVICES = ("clean-tv", "clean-movie")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Trash clean undo journals older than N days")
    ap.add_argument("-d", "--directory", action="append", required=True, help="Root holding the journals (repeatable)")
    ap.add_argument("--days", type=float, default=JOURNAL_KEEP_DAYS,
                    help=f"Keep journals newer than this many days (default {JOURNAL_KEEP_DAYS:g})")
    ap.add_argument("--service", action="append", choices=ALL_SERVICES,
                    help="Only this service's journals (repeatable; default both)")
    ap.add_argument("--commit", action="store_true", help="Trash them (omit for a dry run)")
    ap.add_argument("--verbose", "-v", action="store_true", help="List every journal affected")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
    log = logging.getLogger("prune-journals")
    if args.days <= 0:
        log.error("--days must be > 0 (0 would mean 'retention off', which prunes nothing)")
        return 2
    services = tuple(args.service or ALL_SERVICES)
    for d in args.directory:
        prune_journals(Path(d), services, args.days, args.commit, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
