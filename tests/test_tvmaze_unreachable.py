"""A network failure must not be cached as "no such show".

Before: _search swallowed every exception as [] and lookup_show cached
None for the name, so one TLS/DNS/VPN blip made a show permanently
unmatchable (2026-10-14: a Python without CA certificates "failed to match"
55 shows, The Pitt and Will Trent among them).
"""
import logging

from src import downloaded_marks as dm
from src import tvmaze


def test_unreachable_tvmaze_is_not_cached_as_no_match(monkeypatch, caplog):
    monkeypatch.setattr(tvmaze, "_search", lambda q: None)
    with caplog.at_level(logging.WARNING):
        assert tvmaze.lookup_show("Will Trent (2023)") is None
    assert "will trent (2023)" not in tvmaze._cache, "a blip must not become a permanent no-match"
    assert "could not reach TVMaze" in caplog.text


def test_a_real_empty_answer_is_still_cached(monkeypatch):
    monkeypatch.setattr(tvmaze, "_search", lambda q: [])
    assert tvmaze.lookup_show("Definitely Not A Show (2099)") is None
    assert tvmaze._cache["definitely not a show (2099)"] is None


def test_one_failed_variant_then_a_hit_still_matches(monkeypatch):
    # Needs a name with two query variants ("Will Trent" has only one).
    name = "The Royals - Uncensored (2026)"
    assert len(tvmaze._query_variants(name)) >= 2
    answers = iter([None, [{"show": {"id": 7, "name": "The Royals: Uncensored", "premiered": "2026-02-01"}}]])
    monkeypatch.setattr(tvmaze, "_search", lambda q: next(answers, []))
    canonical, year = tvmaze.lookup_show(name)
    assert year == "2026" and "Royals" in canonical


def test_search_reports_failure_as_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("certificate verify failed")
    monkeypatch.setattr(tvmaze.urllib.request, "urlopen", boom)
    assert tvmaze._search("anything") is None


def test_flush_logs_its_count_through_the_given_logger(caplog):
    tvmaze._SHARED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tvmaze._SHARED_CACHE_PATH.write_text('{"x (2020)": {"episodes": [{"season": 1, "episode": 1}], "fetchedAt": "z"}}')
    tvmaze._episodes_cache = None
    dm.mark("X (2020)", 1, 1)
    log = logging.getLogger("clean-tv-test")
    with caplog.at_level(logging.INFO, logger="clean-tv-test"):
        assert dm.flush(logger=log) == 1
    assert "Downloaded marks: 1 new across 1 show(s)" in caplog.text
