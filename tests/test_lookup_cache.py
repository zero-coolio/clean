"""Tests for the expiring lookup cache (CLEAN-13).

The bug this module exists to kill: a cached "no" that never expires. The real
entry that caused it is used verbatim below, straight out of
`src/service/.tmdb_cache.json`:

    "dr who joy to the world": null

written once and consulted on every run for months, while the file it referred
to sat unidentified. A hit is a fact about the world and keeps; a miss is a
statement about one moment of one API and must not.
"""
from __future__ import annotations

import json

from src.lookup_cache import MISS, LookupCache

# The real key, as it appears on disk today.
STUCK_KEY = "dr who joy to the world"
# The real answer the ladder now gets from the file's own container tag.
REAL_HIT = ["Doctor Who Joy To The World", "2024"]


def test_no_entry_reads_as_go_and_ask(tmp_path):
    c = LookupCache(tmp_path / "c.json")
    assert c.get(STUCK_KEY) is None


def test_a_hit_is_returned(tmp_path):
    c = LookupCache(tmp_path / "c.json")
    c.put(STUCK_KEY, REAL_HIT)
    assert c.get(STUCK_KEY) == REAL_HIT


def test_a_fresh_miss_stops_the_caller(tmp_path):
    c = LookupCache(tmp_path / "c.json")
    c.put(STUCK_KEY, None)
    assert c.get(STUCK_KEY) is MISS


def test_a_stale_miss_is_asked_again(tmp_path):
    c = LookupCache(tmp_path / "c.json", miss_ttl_seconds=0)
    c.put(STUCK_KEY, None)
    # Expired, so it reads as "nothing known" rather than "known to be absent".
    assert c.get(STUCK_KEY) is None


def test_a_hit_never_expires(tmp_path):
    c = LookupCache(tmp_path / "c.json", miss_ttl_seconds=0)
    c.put(STUCK_KEY, REAL_HIT)
    assert c.get(STUCK_KEY) == REAL_HIT


def test_hits_and_misses_survive_a_reload(tmp_path):
    path = tmp_path / "c.json"
    c = LookupCache(path)
    c.put(STUCK_KEY, None)
    c.put("take shelter|2011", ["Take Shelter", "2011"])

    reopened = LookupCache(path)
    assert reopened.get(STUCK_KEY) is MISS
    assert reopened.get("take shelter|2011") == ["Take Shelter", "2011"]


def test_legacy_null_is_retried_exactly_once_more(tmp_path):
    """The format already on disk. A bare null has no timestamp, so it cannot
    be aged; treating it as expired is the whole point of the migration."""
    path = tmp_path / "c.json"
    path.write_text(json.dumps({STUCK_KEY: None}), encoding="utf-8")

    c = LookupCache(path)
    assert c.get(STUCK_KEY) is None


def test_legacy_hit_is_still_a_hit(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"take shelter|2011": ["Take Shelter", "2011"]}),
                    encoding="utf-8")

    c = LookupCache(path)
    assert c.get("take shelter|2011") == ["Take Shelter", "2011"]


def test_unreadable_cache_is_not_fatal(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ this is not json", encoding="utf-8")
    c = LookupCache(path)
    assert c.get(STUCK_KEY) is None
