#!/usr/bin/env python3
"""
Runtime entrypoint for Clean-Movie.

Usage:
  python -m src.MovieMain --directory "/path/to/movies" [--commit] [--plan] [--quarantine DIR] [--lookup]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import DEFAULT_RECENT_WINDOW, parse_duration
from src.service.clean_movie_service import CleanMovieService


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Safely organize movie media (Clean-Movie)")
    ap.add_argument("--directory", "-d", required=True, help="Root directory to scan")
    ap.add_argument("--dest", help="Destination library root (default: same as --directory)")
    ap.add_argument("--commit", action="store_true", help="Apply changes (omit for dry-run)")
    ap.add_argument("--plan", action="store_true", help="Write journal only (no changes)")
    ap.add_argument("--quarantine", help="Quarantine directory for sample/trailer files")
    ap.add_argument("--undo", metavar="JOURNAL", help="Undo from journal file")
    ap.add_argument(
        "--lookup",
        action="store_true",
        help="Use TMDB API to look up missing years (requires TMDB_API_KEY env var)",
    )
    ap.add_argument(
        "--since",
        metavar="DURATION",
        help=(
            "Incremental mode: only process files modified within DURATION "
            "(e.g. '1h', '30m', '2d', or a bare number of seconds). The "
            "already-organized library is skipped. Omit for a full run."
        ),
    )
    ap.add_argument(
        "--recent",
        action="store_true",
        help=f"Incremental mode shorthand for --since {DEFAULT_RECENT_WINDOW}.",
    )
    return ap.parse_args()


def resolve_since_seconds(since: str | None, recent: bool) -> float | None:
    """Resolve --since / --recent flags into a window in seconds (or None)."""
    if since:
        return parse_duration(since)
    if recent:
        return parse_duration(DEFAULT_RECENT_WINDOW)
    return None


def main() -> None:
    args = parse_args()
    service = CleanMovieService()

    if args.undo:
        service.undo(Path(args.undo).expanduser().resolve())
        return

    root = Path(args.directory).expanduser().resolve()
    dest = Path(args.dest).expanduser().resolve() if args.dest else None
    quarantine = Path(args.quarantine).expanduser().resolve() if args.quarantine else None
    since_seconds = resolve_since_seconds(args.since, args.recent)
    service.run(
        root=root,
        commit=args.commit,
        plan=args.plan,
        quarantine=quarantine,
        lookup=args.lookup,
        dest=dest,
        since_seconds=since_seconds,
    )


if __name__ == "__main__":
    main()
