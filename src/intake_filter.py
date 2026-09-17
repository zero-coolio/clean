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

SCOPE: two layouts, one per service, sharing the tiering and the artifact rules:

  TV     Show (Year)/Season NN/Show.(Year).SxxExx.Title.ext
  Movie  Title (Year)/Title (Year).ext  (+ sidecars: Title (Year).eng.srt)

Both answer the same three tiers:
  0. clean's own artifacts (journals, .DS_Store) — never work.
  1. anything NOT inside an organized "Title (Year)" folder — a release folder
     or a loose file dropped at the top level. Always processed.
  2. inside an organized folder, a file whose name is not one clean placed.
     Always processed.
Everything else is done, and is left to the separate full re-verification pass
that handles episode-title backfill.

The tier-2 test is the only part that differs, because the two services produce
different names: TV emits a dotted stem with SxxExx, movies emit the folder name
verbatim plus an optional dotted sidecar suffix. Use the entry point that
matches the service — `tv_needs_processing` or `movie_needs_processing` — via
BaseCleanService._needs_processing, never by guessing at the call site.
"""
from __future__ import annotations

import re
from pathlib import PurePath

# An organized destination folder clean created: "Reacher (2022)", "Ad Astra
# (2019)". Identical shape for both services, so both tier-1 tests share it.
# Mirrors the fswatch exclusion in watch-tv.sh (`.*/[^/]+ \([0-9]{4}\)$`), which
# has always encoded this same "organized folders are uninteresting" idea.
_RE_ORGANIZED_DIR = re.compile(r"^.+ \((?:19|20)\d{2}\)$")

# A TV filename clean itself produced:
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

# A season folder the TV service created: "Season 01", "Season 1998".
# Movies never live under one, and this is not cosmetic: the qBittorrent intake
# directory doubles as the TV library, and watch-tv.sh runs the MOVIE pass over
# it to route films out to seagate-movie. Without this test, every organized
# episode there is "not inside a Title (Year) folder" and therefore movie work
# — measured at 6,518 files per event-triggered run on 2026-09-17, against a
# handful under the old mtime window. The movie service's process_file returns
# early on these anyway, so all this saves is the pointless call; avoiding that
# call is the entire purpose of incremental selection.
_RE_SEASON_DIR = re.compile(r"^Season\s+\d+$", re.IGNORECASE)

# Clean's own droppings. Journals accumulate in the library root — 3,631 of them
# in the TV library as of 2026-08-22, 209 in the movie library as of 2026-09-17 —
# and treating each as a candidate would mean thousands of pointless
# process_file calls per run. fswatch already ignores these two.
#
# `rename-fix-reversal` is also ours: the one-off reversal journal from the
# 2026-07-28 rename fix still sits in the movie root, and without this it is the
# single file structural mode would flag as work on every run, forever.
_RE_JOURNAL = re.compile(r"^\.(?:clean-.*journal|rename-fix-reversal)-.*\.jsonl$")


def is_organized_dir(name: str) -> bool:
    """True if `name` is a "Title (Year)" destination folder clean created."""
    return bool(_RE_ORGANIZED_DIR.match(name))


def is_canonical_media_name(stem: str) -> bool:
    """True if `stem` has the shape clean gives TV files it has already placed.

    Deliberately shape-only. A canonical name missing an episode title
    ("Reacher.(2022).S04E01") still counts as placed — backfilling titles is the
    full re-verification pass's job, not this filter's.
    """
    return bool(_RE_CANONICAL_STEM.match(stem))


def is_placed_movie_file(folder: str, name: str) -> bool:
    """True if `name` is a file clean placed inside movie folder `folder`.

    The movie service files as "<Title (Year)>/<Title (Year)>.<ext>" and parks
    sidecars beside it, appending language/flag suffixes to that same stem:

        Psychokinesis (2018)/Psychokinesis (2018).mkv
        Psychokinesis (2018)/Psychokinesis (2018).eng.srt
        Psychokinesis (2018)/Psychokinesis (2018).eng.sdh.hi.srt

    So "placed" means the folder name, optionally followed by a dotted suffix
    chain. Testing the stem against a standalone regex instead — the way the TV
    side does it — would re-flag every subtitle as unfinished work on every run,
    which is the Hornblower trap above wearing a different hat. Comparing
    against the parent folder also catches a genuinely misfiled movie, e.g.
    "Eater's Guide to the World (2020)/Dr Who Joy To The World.mkv".
    """
    stem = PurePath(name).stem
    return stem == folder or stem.startswith(f"{folder}.")


def is_season_dir(name: str) -> bool:
    """True if `name` is a "Season NN" folder the TV service created."""
    return bool(_RE_SEASON_DIR.match(name))


def is_own_artifact(name: str) -> bool:
    """True for files clean itself writes and must never treat as work."""
    return name == ".DS_Store" or bool(_RE_JOURNAL.match(name))


def _tier_0_and_1(rel: PurePath) -> bool | None:
    """Shared tiers 0 and 1. Returns a verdict, or None to fall through to 2.

    Tier 0 is clean's own artifacts; tier 1 is anything not yet filed under an
    organized "Title (Year)" folder, which includes a loose file at the root.
    """
    parts = rel.parts
    if not parts:
        return False

    if is_own_artifact(rel.name):
        return False

    # Not inside an organized folder — a release folder, or a loose file at the
    # top level (a stalled download, a manual drop). Always work.
    if len(parts) == 1 or not is_organized_dir(parts[0]):
        return True

    return None


def tv_needs_processing(rel_path: str | PurePath) -> bool:
    """True if the TV file at `rel_path` (relative to the library root) needs work.

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
    verdict = _tier_0_and_1(rel)
    if verdict is not None:
        return verdict

    # Tier 2: inside an organized folder but not something clean placed.
    return not is_canonical_media_name(rel.stem)


def movie_needs_processing(rel_path: str | PurePath) -> bool:
    """True if the movie file at `rel_path` needs work. See `tv_needs_processing`.

    Same tiering and the same err-toward-True bias; only tier 2 differs, because
    the movie service names its output after the containing folder rather than
    with an SxxExx stem. See `is_placed_movie_file`.
    """
    rel = PurePath(rel_path)

    if is_own_artifact(rel.name):
        return False

    # TV territory, never movie work. Must precede tier 1, because an organized
    # episode's "Show (Year)" parent passes the tier-1 test and its TV-shaped
    # filename then fails tier 2. See _RE_SEASON_DIR.
    if any(is_season_dir(part) for part in rel.parts[:-1]):
        return False

    verdict = _tier_0_and_1(rel)
    if verdict is not None:
        return verdict

    # Tier 2: inside an organized folder but not a file clean placed there.
    return not is_placed_movie_file(rel.parts[0], rel.name)
