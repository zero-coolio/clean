#!/usr/bin/env python3
"""Guard rules for replacing a cached TVMaze show entry.

One job: decide whether a cached entry may be swapped out — `needs_refresh`
answers "should we look again?" and `is_plausible_replacement` answers "may we
write back what came back?". Pure — no network, no filesystem, no clock of its
own (``now`` is injected), so the thresholds are unit-testable without touching
TVMaze or the real cache.

Mirrors lime's ``Core/ScheduleFreshness.swift`` so both projects agree on which
entries in the shared cache are suspect. See ``needs_refresh`` for the rule and
``DO NOT ADD A TTL`` below for the approach that was measured and rejected.
"""
from __future__ import annotations

import datetime
import logging

from .tvmaze_titles import PLACEHOLDER_TITLES, is_identifying_title

_log = logging.getLogger(__name__)

# How recently a show's newest cached episode must have aired for the show to
# count as "plausibly still running". Two years, not one, and the difference is
# not academic: Reacher's gap between its cached season-3 finale (2025-03-27)
# and the season-4 premiere that broke lime is 512 days, so a one-year window
# misses the exact case this exists to fix.
CONTINUATION_WINDOW_DAYS = 730

# DO NOT ADD A TTL ON fetchedAt.
#
# The obvious rule — "re-fetch anything fetched more than N days ago" — was
# measured against the real 358-entry shared cache and does not discriminate.
# CleanMedia warmed almost the whole file in a single pass, so the ages are
# near-constant (median 61 days, range 1-73). Every threshold below 90 days
# re-fetches ~330 of 358 shows; every threshold at 90 days or above re-fetches
# none. There is no useful middle. `fetchedAt` records when WE last looked, and
# carries no signal about whether the SHOW changed — which is the only question
# that matters. The rule below keys off the show's own timeline instead.
#
# `fetched_at` is still a parameter of `needs_refresh` (it matches lime's
# signature and is part of the entry) but it is deliberately NOT consulted.
# tests/test_tvmaze_freshness.py asserts that, so a future "improvement" that
# quietly reintroduces a TTL fails the suite instead of the library.


def _airdates(episodes: list[dict] | None) -> list[datetime.date]:
    """Parse the usable ISO airdates out of a cached episode list.

    Entries with a missing, empty or malformed ``airdate`` are dropped rather
    than raising: the shared cache is written by two projects and one bad row
    must not make an otherwise fine show undecidable.
    """
    dates: list[datetime.date] = []
    for ep in episodes or []:
        raw = (ep or {}).get("airdate") or ""
        if not raw:
            continue
        try:
            dates.append(datetime.date.fromisoformat(raw[:10]))
        except ValueError:
            _log.debug("freshness: unparseable airdate %r, ignoring", raw)
            continue
    return dates


def needs_refresh(
    episodes: list[dict] | None,
    fetched_at: str | None,
    now: datetime.date,
    *,
    window_days: int = CONTINUATION_WINDOW_DAYS,
) -> bool:
    """True when a cached show entry should be re-fetched from TVMaze.

    Re-fetch when BOTH hold:

    1. **No forward data** — every cached episode has already aired. If an
       unaired episode is present the entry already answers "what's next", so
       there is nothing to gain by asking again.
    2. **Newest episode aired within `window_days`** — the show plausibly
       continued rather than ended years ago.

    There is deliberately NO lower bound on that window. The instinct is to skip
    shows that aired very recently as "nothing new yet"; that is backwards. A
    show whose newest cached episode aired *yesterday* with no follow-up listed
    is among the most valuable things to refresh — that is a show mid-season
    whose next episode simply has not been picked up yet.

    An entry with no usable airdates at all (empty episode list, or every
    airdate blank) returns False. Condition 2 cannot be satisfied without a
    newest airdate, and such an entry means TVMaze resolved nothing for the
    show — re-fetching it would cost a search plus a fetch on every pass,
    forever, for a show that will never populate.

    Args:
        episodes: Cached episode dicts (``season``/``episode``/``title``/``airdate``).
        fetched_at: The entry's ``fetchedAt`` stamp. Accepted for parity with
            lime's signature and INTENTIONALLY UNUSED — see the TTL note above.
        now: Today's date, injected so tests are deterministic.
        window_days: Continuation window; defaults to `CONTINUATION_WINDOW_DAYS`.

    Returns:
        True if the entry should be re-fetched.
    """
    dates = _airdates(episodes)
    if not dates:
        return False

    # An episode that has ALREADY aired but still carries a placeholder/empty
    # title ("TBA") should have a real title by now — re-check even if the show
    # has forward data (which otherwise short-circuits to "fresh" below). This
    # is the currently-airing-season blind spot: Slow Horses S6 sat on cached
    # "TBA" titles TVMaze had since filled in, and the no-forward-data rule never
    # fired because S6 still had unaired episodes.
    if _has_aired_placeholder_title(episodes, now):
        return True

    if any(d > now for d in dates):
        # Forward data present — the entry is already doing its job.
        return False

    newest = max(dates)
    return (now - newest).days <= window_days


def _has_aired_placeholder_title(episodes: list[dict] | None, now: datetime.date) -> bool:
    """True if any episode that has already aired still has an empty or
    placeholder ("TBA") title. Positional titles ("Episode 4") are intentionally
    NOT placeholders here: a show TVMaze never titles would otherwise re-fetch
    forever. Mirrors lime's `ScheduleFreshness.isPlaceholderTitle`.
    """
    for ep in episodes or []:
        raw = ((ep or {}).get("airdate") or "").strip()
        if not raw:
            continue
        title = ((ep or {}).get("title") or "").strip().lower()
        if title and title not in PLACEHOLDER_TITLES:
            continue  # a real title — nothing missing here
        try:
            d = datetime.date.fromisoformat(raw[:10])
        except ValueError:
            continue
        if d <= now:
            return True
    return False


# What fraction of a cached entry's episode titles must survive in a re-fetch
# for it to count as the same show. Generous: TVMaze revises episode counts
# downward (Avatar 16 -> 15) and occasionally renames an episode, and neither is
# a fault. A genuinely different show overlaps at roughly zero.
_MIN_TITLE_OVERLAP = 0.5

# Below this many titles on either side, title overlap is noise rather than
# evidence, and the guard abstains instead of guessing.
_MIN_TITLES_TO_JUDGE = 2


def _titles(episodes: list[dict] | None) -> set[str]:
    """Case-folded episode titles that actually identify a show.

    Placeholders and positional titles ("TBA", "Episode 4") are dropped: they
    are not evidence of identity, and TVMaze swaps them for real titles over
    time, which would otherwise read as the titles ceasing to match.
    """
    out = set()
    for ep in episodes or []:
        title = ((ep or {}).get("title") or "").strip()
        if is_identifying_title(title):
            out.add(title.lower())
    return out


def is_plausible_replacement(
    cached: list[dict] | None, fetched: list[dict] | None
) -> bool:
    """True when `fetched` looks like a newer view of the SAME show as `cached`.

    A refresh re-resolves the show by name, and a bad resolution would overwrite
    a good entry with a completely different series — quietly, in a file lime
    reads and cannot repair. (This codebase has done exactly that once: a
    mis-resolved name filed four seasons of X-Men Evolution under an unrelated
    anime.) So a replacement has to look like the show it is replacing.

    Episode titles are the evidence: they are stable across re-fetches for a
    continuing show and effectively disjoint between different shows. Season and
    episode NUMBERS are deliberately not used — every show on earth has an
    S01E01, so numeric overlap proves nothing.

    The guard abstains (returns True) when there is nothing to judge: no cached
    episodes, or fewer than `_MIN_TITLES_TO_JUDGE` real titles on either side.
    Some cached shows genuinely carry blank titles, and blocking their refresh
    on evidence that does not exist would be worse than the risk.

    Args:
        cached: The episode list currently in the shared cache.
        fetched: The episode list just returned by TVMaze.

    Returns:
        False only when there IS title evidence and it says these are different
        shows.
    """
    if not cached:
        return True
    if not fetched:
        return False

    old, new = _titles(cached), _titles(fetched)
    if len(old) < _MIN_TITLES_TO_JUDGE or len(new) < _MIN_TITLES_TO_JUDGE:
        return True

    overlap = len(old & new) / len(old)
    if overlap < _MIN_TITLE_OVERLAP:
        _log.warning(
            "freshness: refusing replacement — only %.0f%% of %d cached titles "
            "survive in the %d fetched (looks like a different show)",
            overlap * 100, len(old), len(new),
        )
        return False
    return True
