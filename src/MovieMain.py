#!/usr/bin/env python3
"""
Runtime entrypoint for Clean-Movie.

Usage:
  python -m src.MovieMain --directory "/path/to/movies" [--commit] [--plan] [--quarantine DIR] [--lookup]

--directory may be repeated to organize several libraries in one run:

  python -m src.MovieMain -d /Volumes/Seagate/seagate-movie \
                          -d /Volumes/Summer/movie-archive

Each root is organized IN PLACE, within itself. Repeating --directory does not
merge libraries; --dest does that, and is refused alongside multiple roots so a
second library cannot be emptied into the first by accident. (CLEAN-18)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.cli_args import add_work_selection_args, resolve_since_seconds
from src.library_roots import resolve_roots
from src.service.clean_movie_service import CleanMovieService


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Safely organize movie media (Clean-Movie)")
    ap.add_argument(
        "--directory", "-d",
        required=True,
        action="append",
        metavar="DIR",
        help="Root directory to scan. Repeat to organize several libraries, "
             "each in place.",
    )
    ap.add_argument("--dest", help="Destination library root (default: same as --directory). "
                                   "Not allowed with more than one --directory.")
    ap.add_argument("--commit", action="store_true", help="Apply changes (omit for dry-run)")
    ap.add_argument("--plan", action="store_true", help="Write journal only (no changes)")
    ap.add_argument("--quarantine", help="Quarantine directory for sample/trailer files")
    ap.add_argument("--undo", metavar="JOURNAL", help="Undo from journal file")
    ap.add_argument(
        "--lookup",
        action="store_true",
        help="Use TMDB API to look up missing years (requires TMDB_API_KEY env var)",
    )
    add_work_selection_args(ap, "Title (Year)")
    args = ap.parse_args()

    # Guarded here rather than at the call site: --dest names ONE destination,
    # so pairing it with several sources says "pour these libraries into that
    # one", which is a 586 GB cross-volume migration wearing the costume of a
    # tidy-up. If that is ever wanted it should be asked for one root at a time.
    if args.dest and len(args.directory) > 1:
        ap.error("--dest cannot be combined with more than one --directory: "
                 "each root is organized in place. Run them separately if you "
                 "really mean to merge libraries.")
    return args


def main() -> None:
    args = parse_args()
    service = CleanMovieService()

    if args.undo:
        service.undo(Path(args.undo).expanduser().resolve())
        return

    roots = resolve_roots(args.directory, service._logger)
    if not roots:
        service._logger.error(
            "No usable library root out of %d given: nothing to do", len(args.directory)
        )
        sys.exit(1)

    dest = Path(args.dest).expanduser().resolve() if args.dest else None
    quarantine = Path(args.quarantine).expanduser().resolve() if args.quarantine else None
    since_seconds = resolve_since_seconds(args.since, args.recent)

    if len(roots) > 1:
        service._logger.info(
            "ROOTS (%d, each organized in place): %s",
            len(roots), ", ".join(str(r) for r in roots),
        )

    # One run() per root, sequentially. Each writes its own journal next to its
    # own library, so an undo restores one library without touching the other.
    for root in roots:
        service.run(
            root=root,
            commit=args.commit,
            plan=args.plan,
            quarantine=quarantine,
            lookup=args.lookup,
            dest=dest,
            since_seconds=since_seconds,
            structural=args.structural,
        )


if __name__ == "__main__":
    main()
