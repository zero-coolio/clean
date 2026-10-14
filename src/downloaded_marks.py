"""Per-episode "was in the library" marks in the shared TVMaze cache (CLEAN-25).

lime's "behind" filter lists episodes that aired in the last four weeks and
were never downloaded. "On disk now" is not the same as "downloaded": Steve
deletes watched episodes (Brothers (2026) S01E01/E02 were downloaded, deleted,
and then listed as missing). The shared cache is the single source of truth for
both projects, so the fact lives there: each cached episode dict may carry

    "downloadedAt": "YYYY-MM-DD"   # earliest day CleanMedia saw it in the library

CleanMedia is the cache's only writer; lime reads it. One job here: record and
preserve those marks. The pure functions hold the rules; `mark`/`flush` do the
I/O through tvmaze's cache helpers, buffered so a run writes the cache once.
"""
from __future__ import annotations

import atexit
import datetime
import logging

from . import tvmaze

_log = logging.getLogger(__name__)

FIELD = "downloadedAt"

# cache key -> {(season, episode): "YYYY-MM-DD"} waiting for flush().
_pending: dict[str, dict[tuple[int, int], str]] = {}


# ----------------------------------------------------------------- pure rules

def _ep_key(ep: dict) -> tuple[int, int] | None:
    try:
        return int(ep["season"]), int(ep["episode"])
    except (KeyError, TypeError, ValueError):
        return None


def apply_marks(episodes: list[dict], marks: dict[tuple[int, int], str]) -> tuple[list[dict], int]:
    """Return `episodes` with `downloadedAt` set from `marks`, and how many changed.

    The earliest date wins, so re-running a backfill or re-seeing a file never
    moves a mark later. Episodes the cache doesn't list are ignored (logged by
    the caller): there is nowhere to put them.
    """
    changed = 0
    out = []
    for ep in episodes:
        k = _ep_key(ep)
        when = marks.get(k) if k else None
        if when and (not ep.get(FIELD) or when < ep[FIELD]):
            ep = {**ep, FIELD: when}
            changed += 1
        out.append(ep)
    return out, changed


def carry_over(old: list[dict] | None, new: list[dict]) -> list[dict]:
    """Copy marks from a cached episode list onto a freshly fetched one.

    A TVMaze refetch rebuilds every episode dict from the API, which knows
    nothing about downloads; without this every refresh would erase the marks.
    Matched by (season, episode).
    """
    if not old:
        return new
    marks = {k: ep[FIELD] for ep in old if ep.get(FIELD) and (k := _ep_key(ep))}
    if not marks:
        return new
    merged, _ = apply_marks(new, marks)
    return merged


# --------------------------------------------------------------------- I/O

def mark(show_name: str, season, episode, when: datetime.date | None = None) -> None:
    """Note that `show_name` S`season`E`episode` is in the library. Buffered;
    call `flush()` (also registered at exit) to write."""
    try:
        k = (int(season), int(episode))
    except (TypeError, ValueError):
        _log.debug("downloaded mark skipped, unparseable episode %r %r %r", show_name, season, episode)
        return
    day = (when or datetime.date.today()).isoformat()
    key = tvmaze._normalize_show_key(show_name)
    slot = _pending.setdefault(key, {})
    if k not in slot or day < slot[k]:
        slot[k] = day


def flush(logger=None) -> int:
    """Write buffered marks into the shared cache. Returns episodes changed.

    Only shows already in the cache get marks (CleanMedia caches a show the
    first time it files one of its episodes, so in practice that's all of
    them). One read-modify-write for the whole run.
    """
    global _pending
    if not _pending:
        return 0
    pending, _pending = _pending, {}
    cache = tvmaze._load_episodes_cache()
    updates: dict[str, dict] = {}
    total = 0
    for key, marks in pending.items():
        entry = cache.get(key)
        if entry is None:
            _log.debug("downloaded marks: %r not in the shared cache, %d mark(s) dropped", key, len(marks))
            continue
        episodes, changed = apply_marks(entry.get("episodes", []), marks)
        unknown = set(marks) - {k for ep in episodes if (k := _ep_key(ep))}
        if unknown:
            _log.debug("downloaded marks: %r has no cached episode for %s", key, sorted(unknown))
        if changed:
            updates[key] = {**entry, "episodes": episodes}
            total += changed
    if updates:
        tvmaze._save_episodes_cache(updates)
    msg = "Downloaded marks: %d new across %d show(s)"
    (logger or _log).info(msg, total, len(updates))
    return total


atexit.register(flush)
