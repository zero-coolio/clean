"""A JSON-backed memo for external lookups, whose negative answers expire.

One job: remember what TMDB, IMDb or any other external source said about a
query, so repeat runs do not re-hit the network, WITHOUT making a single
failure permanent.

Why the expiry exists (CLEAN-13). Both caches stored a miss as a bare `null`
and never reconsidered it. `.tmdb_cache.json` still holds:

    "dr who joy to the world": null

written once, months ago, and consulted on every run since. The file it refers
to sat unidentified for three days while the lookup that would have identified
it was answered from a cache in microseconds instead of being asked. A cached
"no" is a statement about one moment of one API, not a fact about the world:
databases gain entries, endpoints recover, rate limits lift. A hit is a fact
and keeps forever; a miss is a guess and gets a shelf life.

ON-DISK FORMAT
    {"<key>": {"v": <result or null>, "at": <epoch seconds>}}

Legacy entries written before this module (a bare list, or a bare null) are
still read: a bare list is an ageless hit, a bare null is a miss with no
timestamp, which is treated as already expired so it gets asked exactly once
more. That is the point, not a migration cost.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# A miss is retried after this long. Long enough that a dead endpoint is not
# hammered every run, short enough that a newly-added title is found within a
# week rather than never.
DEFAULT_MISS_TTL_SECONDS = 7 * 24 * 60 * 60

# Sentinel distinguishing "no entry, go ask" from "cached miss, do not ask".
MISS = object()


class LookupCache:
    """Disk-backed lookup memo. Hits are permanent, misses expire."""

    def __init__(
        self,
        path: Path,
        *,
        miss_ttl_seconds: float = DEFAULT_MISS_TTL_SECONDS,
        logger_=None,
    ) -> None:
        self._path = path
        self._ttl = miss_ttl_seconds
        self._log = logger_ or logger
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            self._log.debug("LookupCache: unreadable %s: %s", self._path, e)
            return
        if not isinstance(raw, dict):
            return
        for k, v in raw.items():
            if isinstance(v, dict) and "v" in v:
                self._entries[k] = v
            elif v is None:
                # Legacy miss, no timestamp: expired by definition, ask again.
                self._entries[k] = {"v": None, "at": 0.0}
            else:
                # Legacy hit: a real answer never goes stale.
                self._entries[k] = {"v": v, "at": None}

    def get(self, key: str):
        """Cached value, `MISS` for a live cached miss, or None for no entry.

        Three outcomes, deliberately distinct. `None` means "nothing known,
        go and ask". `MISS` means "we asked recently and the answer was no,
        do not ask again yet". Anything else is the cached answer.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None

        value = entry.get("v")
        if value is not None:
            return value

        at = entry.get("at")
        if at is not None and (time.time() - at) >= self._ttl:
            self._log.debug("LookupCache: miss for %r expired, re-asking", key)
            del self._entries[key]
            self._dirty = True
            return None
        return MISS

    def put(self, key: str, value) -> None:
        """Record an answer. `None` records a miss, which will expire."""
        self._entries[key] = {"v": value, "at": time.time() if value is None else None}
        self._dirty = True
        self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._path.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception as e:
            self._log.debug("LookupCache: cannot write %s: %s", self._path, e)

    def __len__(self) -> int:
        return len(self._entries)
