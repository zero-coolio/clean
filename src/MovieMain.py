#!/usr/bin/env python3
"""
Runtime entrypoint for Clean-Movie.

Usage:
  python -m src.MovieMain --directory "/path/to/movies" [--commit] [--plan] [--quarantine DIR]
"""
from __future__ import annotations
import argparse
from pathlib import Path
from src.service.clean_movie_service import CleanMovieService


def parse_args():
    ap = argparse.ArgumentParser(description="Safely organize movie media (Clean-Movie)")
    ap.add_argument("--directory", "-d", required=True, help="Root directory to process")
    ap.add_argument("--commit", action="store_true", help="Apply changes (omit for dry-run)")
    ap.add_argument("--plan", action="store_true", help="Write journal only (no changes)")
    ap.add_argument("--quarantine", help="Quarantine directory for sample/trailer files")
    ap.add_argument("--lookup", action="store_true", help="Use TMDB API to look up missing years (requires TMDB_API_KEY env var)")
    return ap.parse_args()


def main():
    args = parse_args()
    service = CleanMovieService()
    root = Path(args.directory).expanduser().resolve()
    quarantine = Path(args.quarantine).expanduser().resolve() if args.quarantine else None
    service.run(root=root, commit=args.commit, plan=args.plan, quarantine=quarantine, lookup=args.lookup)


if __name__ == "__main__":
    main()
