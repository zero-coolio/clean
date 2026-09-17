#!/usr/bin/env python3
"""Shared work-selection CLI arguments for the clean entry points.

One job: define, in one place, how a clean run is told WHICH files to consider,
and translate those flags into what BaseCleanService.run expects.

Main (TV) and MovieMain ask the identical question and previously answered it
with identical copies of `--since`, `--recent` and `resolve_since_seconds`.
`--structural` then landed on the TV side only, and the movie watcher kept the
mtime window it was already known to be broken under — which is how
"The.End.of.Oak.Street...mkv" sat unrenamed in the movie library from
2026-09-15 onward. Divergence between these two parsers has a body count, so
they share the definition now; the only per-service variation is the folder
shape named in the help text.
"""
from __future__ import annotations

import argparse

from .config import DEFAULT_RECENT_WINDOW, parse_duration


def add_work_selection_args(ap: argparse.ArgumentParser, organized_dir_example: str) -> None:
    """Add --since / --recent / --structural to `ap`.

    Args:
        ap: Parser to extend.
        organized_dir_example: How this service's organized folders are named
            ("Show (Year)" / "Title (Year)"), quoted into the --structural help.
    """
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
    ap.add_argument(
        "--structural",
        action="store_true",
        help=(
            "Select work by library STRUCTURE instead of file mtime: process "
            f"anything not yet filed under a '{organized_dir_example}' folder, "
            "plus anything inside one whose name clean did not produce. Unlike "
            "--since this cannot silently miss a download (torrents arrive from "
            "a temp dir with stale mtimes), and a dropped watcher event costs "
            "latency, not the file. Overrides --since/--recent."
        ),
    )


def resolve_since_seconds(since: str | None, recent: bool) -> float | None:
    """Resolve --since / --recent flags into a window in seconds (or None)."""
    if since:
        return parse_duration(since)
    if recent:
        return parse_duration(DEFAULT_RECENT_WINDOW)
    return None
