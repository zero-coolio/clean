#!/usr/bin/env python3
"""Sweep the shared TVMaze cache and re-fetch the entries that look stale.

One job: walk every show in the shared episode cache, ask
`tvmaze_freshness.needs_refresh` about it, and re-fetch the ones that say yes.

This exists because CleanMedia's normal refresh path is file-driven — a show is
only consulted when one of its files moves through a run — so a show with no new
downloads is never re-checked no matter how far behind it falls. That is exactly
how `reacher (2022)` sat at 3 seasons while season 4 aired, which broke lime
(lime reads this file and is not allowed to write it). The sweep is the pass
that heals those shows.

Programmatic entry point: `refresh_stale_entries`. CLI wrapper: `src.RefreshCache`.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from . import tvmaze
from .tvmaze_freshness import needs_refresh

_log = logging.getLogger(__name__)


@dataclass
class RefreshReport:
    """What a sweep looked at and what it changed.

    Every count is reported rather than inferred so a run can be audited from
    its summary line alone.
    """

    total: int = 0
    """Entries present in the shared cache."""

    selected: int = 0
    """Entries the freshness rule flagged as stale."""

    attempted: int = 0
    """Entries actually re-fetched (`selected`, less anything cut by `limit`)."""

    unchanged: int = 0
    """Re-fetched entries whose episode count did not move."""

    failed: int = 0
    """Re-fetches that could not resolve or came back empty; cache left as-is."""

    changed: list[tuple[str, int, int]] = field(default_factory=list)
    """(show key, episodes before, episodes after) for entries whose CONTENT moved.

    Content, not count: TVMaze also corrects titles in place (it replaced four
    "Episode N" placeholders on `lucky (2026)` with real titles while the count
    stayed at 7). Reporting that as "unchanged" would understate what the sweep
    fixed, so before == after in these tuples is expected and meaningful.
    """

    @property
    def count_changes(self) -> int:
        """Corrected entries whose episode COUNT moved, not just their details."""
        return sum(1 for _, before, after in self.changed if before != after)

    def summary(self) -> str:
        return (
            f"{self.total} cached, {self.selected} stale, {self.attempted} re-fetched, "
            f"{len(self.changed)} corrected ({self.count_changes} by episode count), "
            f"{self.unchanged} unchanged, {self.failed} failed"
        )


def select_stale_keys(
    cache: dict[str, dict], now: datetime.date | None = None
) -> list[str]:
    """Return the cache keys the freshness rule flags, in stable sorted order.

    Pure apart from the default clock: pass `now` to make it deterministic.
    Sorted so a `--limit`ed sweep is reproducible instead of dict-order roulette.
    """
    today = now or datetime.date.today()
    return sorted(
        key
        for key, entry in cache.items()
        if needs_refresh((entry or {}).get("episodes"), (entry or {}).get("fetchedAt"), today)
    )


def refresh_stale_entries(
    *,
    commit: bool = False,
    limit: int | None = None,
    now: datetime.date | None = None,
    logger: logging.Logger | None = None,
) -> RefreshReport:
    """Re-fetch every stale entry in the shared TVMaze cache.

    Args:
        commit: When False (the default) nothing is fetched or written — the
            sweep only reports which shows it WOULD refresh. Matches the rest of
            CleanMedia, where dry-run is the default and `--commit` acts.
        limit: Stop after this many re-fetches. Useful for a bounded first pass;
            the selection is sorted, so a limited run is reproducible.
        now: Today's date, injected for deterministic tests.
        logger: Optional logger for per-show progress.

    Returns:
        A `RefreshReport`. Writes go through `tvmaze._save_episodes_cache`, so
        the on-disk file is still merged read-modify-write and replaced
        atomically, and the schema is unchanged (lime-compatible).
    """
    log = logger or _log
    cache = tvmaze._load_episodes_cache()
    report = RefreshReport(total=len(cache))

    stale = select_stale_keys(cache, now=now)
    report.selected = len(stale)
    log.info(
        "TVMaze refresh: %d/%d cached shows are stale%s",
        report.selected, report.total, "" if commit else " (dry-run, nothing will be fetched)",
    )

    if not commit:
        for key in stale:
            log.debug("TVMaze refresh: would re-fetch %r", key)
        return report

    targets = stale[:limit] if limit is not None else stale
    if limit is not None and len(stale) > len(targets):
        log.info("TVMaze refresh: limited to first %d of %d stale shows", len(targets), len(stale))

    for i, key in enumerate(targets, 1):
        cached_episodes = (cache.get(key) or {}).get("episodes") or []
        before = len(cached_episodes)
        report.attempted += 1
        # The cache key IS the normalized show name, already year-stamped by
        # whichever run first cached it. Re-fetching under that same key is what
        # keeps year stamping intact — a fresh lookup by bare name could resolve
        # a differently-keyed (yearless) entry and reintroduce the duplicates
        # that had to be pruned from this file once already.
        episodes = tvmaze._fetch_and_store_episodes(
            key, key, logger=None, replaces=cached_episodes
        )
        if episodes is None:
            report.failed += 1
            log.warning("TVMaze refresh: [%d/%d] %r FAILED (unresolved or empty)", i, len(targets), key)
            continue
        after = len(episodes)
        if episodes != cached_episodes:
            report.changed.append((key, before, after))
            if after != before:
                log.info(
                    "TVMaze refresh: [%d/%d] %r %d → %d episodes", i, len(targets), key, before, after
                )
            else:
                log.info(
                    "TVMaze refresh: [%d/%d] %r episode details corrected (still %d episodes)",
                    i, len(targets), key, after,
                )
        else:
            report.unchanged += 1
            log.debug("TVMaze refresh: [%d/%d] %r unchanged at %d episodes", i, len(targets), key, after)

    log.info("TVMaze refresh: %s", report.summary())
    return report
