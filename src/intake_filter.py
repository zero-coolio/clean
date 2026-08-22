#!/usr/bin/env python3
"""Decide, from library structure alone, whether a file still needs cleaning.

One job: given a path relative to the library root, answer "does clean still
have work to do here?" — using only the shape of the path and filename. No
clock, no filesystem, no cache, so it is unit-testable and cannot drift out of
sync with reality.

This replaces the mtime window (`--since`/`--recent`, see BaseCleanService.
_is_recent). That window asked "was this file written recently?", which is a
proxy for "is this new?" — and the proxy breaks, because qBittorrent downloads
into a temp directory and MOVES the completed folder into the library. The files
keep their temp-dir mtimes, so a download that took longer than the window
arrives already "old" and is silently skipped forever. Worse, the miss is
permanent: nothing ever revisits it.

Structure does not have that problem. A release folder that has not been
consumed is still sitting there; clean deletes it when it is done with it. So
presence IS the work queue, it maintains itself, and a dropped fswatch event
costs latency instead of the file.

SCOPE: this encodes the TV layout (Show (Year)/Season NN/Show.(Year).SxxExx).
The movie service files as "Title (Year)/Title (Year).ext" with no SxxExx, so
structural mode is TV-only for now; MovieMain keeps the mtime window. Applying
this filter to movies would mark every one of them as unfinished work.

Three tiers:
  0. clean's own artifacts (journals, .DS_Store) — never work.
  1. anything NOT inside an organized "Show (Year)" folder — a release folder
     or a loose episode dropped at the top level. Always processed.
  2. inside an organized folder, a file whose name is not already canonical —
     i.e. something clean did not place. Always processed.
Everything else (canonical name in an organized folder) is done, and is left to
the separate full re-verification pass that handles episode-title backfill.
"""
from __future__ import annotations

import re
from pathlib import PurePath

# An organized destination folder clean created: "Reacher (2022)".
# Mirrors the fswatch exclusion in watch-tv.sh (`.*/[^/]+ \([0-9]{4}\)$`), which
# has always encoded this same "organized folders are uninteresting" idea.
_RE_ORGANIZED_DIR = re.compile(r"^.+ \((?:19|20)\d{2}\)$")

# A filename clean itself produced:
#   Eastbound.&.Down.(2009).S02E05.Chapter.11.mkv
#   Reacher.(2022).S04E01.mp4                       (no title yet — still ours)
#   Avenue.5.(2020).S01E06.Was.It.Your.Ears (alt).mkv
#   C.S.Forester's.Horatio.Hornblower.(1998).S1998E01.Hornblower....mp4
#
# The season is \d{2,4}, NOT \d{2}: the show-id collapse/renumber work (c92c09c)
# files some shows under TVMaze's real year-based seasons, so "S1998E01" is
# genuinely canonical output. A two-digit-only pattern re-flags all 8 Hornblower
# episodes as unfinished work on every single run.
_RE_CANONICAL_STEM = re.compile(r"^.+\.\((?:19|20)\d{2}\)\.S\d{2,4}E\d{2}(?:\..*)?$")

# Clean's own droppings. Journals accumulate in the library root — 3,631 of them
# as of 2026-08-22 — and treating each as a candidate would mean thousands of
# pointless process_file calls per run. fswatch already ignores these two.
_RE_JOURNAL = re.compile(r"^\.clean-.*journal-.*\.jsonl$")


def is_organized_show_dir(name: str) -> bool:
    """True if `name` is a "Show (Year)" destination folder clean created."""
    return bool(_RE_ORGANIZED_DIR.match(name))


def is_canonical_media_name(stem: str) -> bool:
    """True if `stem` has the shape clean gives files it has already placed.

    Deliberately shape-only. A canonical name missing an episode title
    ("Reacher.(2022).S04E01") still counts as placed — backfilling titles is the
    full re-verification pass's job, not this filter's.
    """
    return bool(_RE_CANONICAL_STEM.match(stem))


def is_own_artifact(name: str) -> bool:
    """True for files clean itself writes and must never treat as work."""
    return name == ".DS_Store" or bool(_RE_JOURNAL.match(name))


def needs_processing(rel_path: str | PurePath) -> bool:
    """True if the file at `rel_path` (relative to the library root) needs work.

    Errs toward True. Over-processing is safe and cheap — clean is idempotent and
    logs "OK (already placed)" — whereas under-processing is the failure this
    filter exists to eliminate.

    Args:
        rel_path: Path RELATIVE to the library root. An absolute path would make
            the first component "/" and defeat the tier-1 test, so callers must
            relativize first.

    Returns:
        True if the file should be handed to process_file.
    """
    rel = PurePath(rel_path)
    parts = rel.parts
    if not parts:
        return False

    if is_own_artifact(rel.name):
        return False

    # Tier 1: not inside an organized show folder — release folder or a loose
    # episode at the top level. Always work.
    if not is_organized_show_dir(parts[0]):
        return True

    # Tier 2: inside an organized folder but not something clean placed.
    return not is_canonical_media_name(rel.stem)
