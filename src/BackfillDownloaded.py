#!/usr/bin/env python3
"""
One-time (re-runnable) seed of per-episode "downloadedAt" marks (CLEAN-25).

Going forward CleanMedia marks episodes as it files them. This backfills the
history from what already exists, without inventing a new list:
  * every `move` in the `.clean-tv-journal-*.jsonl` files under each TV root
    (an episode CleanMedia filed and Steve may since have deleted), dated by
    the journal's timestamp;
  * every episode file on disk now, dated by its modification time.
Earliest date wins, and an existing mark is never moved later, so re-running
is harmless.

Usage:
  python -m src.BackfillDownloaded -d /Volumes/Seagate/seagate-qBittorrent           # dry run
  python -m src.BackfillDownloaded -d ROOT [-d ROOT2] --commit                        # write
  python -m src.BackfillDownloaded -d ROOT --show brothers --show "ncis origins"      # inspect
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import logging
import re
import sys
from pathlib import Path

from . import tvmaze
from .config import VIDEO_EXT
from .downloaded_marks import apply_marks, flush, mark

_RE_SXXEYY = re.compile(r"[Ss](\d{1,4})[Ee](\d{1,3})")
_RE_JOURNAL_STAMP = re.compile(r"journal-(\d{8})-\d{6}\.jsonl$")
_RE_SHOW_FOLDER = re.compile(r".+\(\d{4}\)$")

log = logging.getLogger("backfill-downloaded")

Marks = dict[str, dict[tuple[int, int], str]]
# cache key -> a show folder name it came from, so --commit can fetch a
# schedule for shows the cache has never seen.
_folder_for_key: dict[str, str] = {}


def episode_from_library_path(path: Path, root: Path) -> tuple[str, int, int] | None:
    """(show folder name, season, episode) for `<root>/<Show (Year)>/Season NN/<..SxxEyy..>`."""
    try:
        rel = path.relative_to(root).parts
    except ValueError:
        return None
    if len(rel) != 3 or not _RE_SHOW_FOLDER.match(rel[0]) or not rel[1].lower().startswith("season"):
        return None
    m = _RE_SXXEYY.search(rel[2])
    if not m:
        return None
    return rel[0], int(m.group(1)), int(m.group(2))


def _add(marks: Marks, show: str, season: int, episode: int, day: str) -> None:
    key = tvmaze._normalize_show_key(show)
    _folder_for_key.setdefault(key, show)
    slot = marks.setdefault(key, {})
    k = (season, episode)
    if k not in slot or day < slot[k]:
        slot[k] = day


def collect_from_journals(root: Path, marks: Marks) -> int:
    n = 0
    for jf in sorted(root.glob(".clean-tv-journal-*.jsonl")):
        m = _RE_JOURNAL_STAMP.search(jf.name)
        if not m:
            continue
        day = datetime.datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
        for line in jf.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                op = json.loads(line)
            except ValueError:
                continue
            if op.get("op") != "move" or Path(op.get("dst", "")).suffix.lower() not in VIDEO_EXT:
                continue
            hit = episode_from_library_path(Path(op["dst"]), root)
            if hit:
                _add(marks, *hit, day)
                n += 1
    return n


def collect_from_disk(root: Path, marks: Marks) -> int:
    n = 0
    for show_dir in root.iterdir():
        if not show_dir.is_dir() or not _RE_SHOW_FOLDER.match(show_dir.name):
            continue
        for f in show_dir.glob("*/*"):
            if f.suffix.lower() not in VIDEO_EXT:
                continue
            hit = episode_from_library_path(f, root)
            if hit:
                day = datetime.date.fromtimestamp(f.stat().st_mtime).isoformat()
                _add(marks, *hit, day)
                n += 1
    return n


def preview(marks: Marks) -> tuple[int, int, list[str]]:
    """(new marks, shows touched, cache keys not found) against the live cache."""
    cache = tvmaze._load_episodes_cache()
    new = shows = 0
    missing = []
    for key, eps in marks.items():
        entry = cache.get(key)
        if entry is None:
            missing.append(key)
            continue
        _, changed = apply_marks(copy.deepcopy(entry.get("episodes", [])), eps)
        if changed:
            new += changed
            shows += 1
    return new, shows, sorted(missing)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Seed downloadedAt marks in the shared TVMaze cache")
    ap.add_argument("-d", "--directory", action="append", required=True, help="TV library root (repeatable)")
    ap.add_argument("--commit", action="store_true", help="Write the marks (omit for a dry run)")
    ap.add_argument("--show", action="append", default=[], help="Print what's known for this show (repeatable)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    marks: Marks = {}
    for raw in args.directory:
        root = Path(raw)
        if not root.is_dir():
            log.error("not a directory: %s", root)
            return 2
        j = collect_from_journals(root, marks)
        d = collect_from_disk(root, marks)
        log.info("%s: %d episode move(s) in journals, %d episode file(s) on disk", root, j, d)

    new, shows, missing = preview(marks)
    total = sum(len(v) for v in marks.values())
    log.info("%d show(s), %d distinct episode(s) seen; %d new mark(s) across %d show(s)",
             len(marks), total, new, shows)
    if missing:
        log.info("%d show folder(s) have no cache entry (no schedule to mark): %s",
                 len(missing), ", ".join(missing[:25]) + (" ..." if len(missing) > 25 else ""))
    for name in args.show:
        key_prefix = tvmaze._normalize_show_key(name)
        for key in sorted(k for k in marks if k.startswith(key_prefix)):
            eps = " ".join(f"S{s:02d}E{e:02d}@{d}" for (s, e), d in sorted(marks[key].items()))
            print(f"{key}: {eps}")

    if not args.commit:
        log.info("Dry run: nothing written. Rerun with --commit to write "
                 "(it also fetches schedules for the %d uncached show(s)).", len(missing))
        return 0
    fetched = 0
    for key in missing:
        name = _folder_for_key.get(key, key)
        try:
            if tvmaze.get_show_episodes(name, logger=log):
                fetched += 1
        except Exception as e:  # network or resolution failure: skip that show
            log.warning("could not fetch a schedule for %r: %s", name, e)
    log.info("Fetched schedules for %d of %d uncached show(s).", fetched, len(missing))
    for key, eps in marks.items():
        for (s, e), day in eps.items():
            mark(key, s, e, datetime.date.fromisoformat(day))
    written = flush(logger=log)
    log.info("Wrote %d mark(s).", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
