#!/usr/bin/env python3
"""
Runtime entrypoint for the shared TVMaze cache refresh sweep.

Re-fetches cached shows that may have continued since we last looked, so the
cache CleanMedia owns (and lime reads) stops going stale.

Usage:
  python -m src.RefreshCache                 # dry-run: report what is stale
  python -m src.RefreshCache --commit        # actually re-fetch and write
  python -m src.RefreshCache --commit -n 20  # bounded first pass
"""
from __future__ import annotations

import argparse
import logging
import sys


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Refresh stale entries in the shared TVMaze episode cache"
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Fetch and write (omit for a dry-run that only reports what is stale)",
    )
    ap.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Stop after this many re-fetches (selection is sorted, so it is reproducible)",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log every show considered, not just the ones that changed",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    # Imported after logging is configured so module-level cache diagnostics land.
    from src.tvmaze_refresh import refresh_stale_entries

    report = refresh_stale_entries(
        commit=args.commit,
        limit=args.limit,
        logger=logging.getLogger("refresh"),
    )
    print(report.summary())
    for key, before, after in report.changed:
        detail = f"{before} -> {after}" if before != after else f"{before} (details corrected)"
        print(f"  {key}: {detail}")


if __name__ == "__main__":
    main()
