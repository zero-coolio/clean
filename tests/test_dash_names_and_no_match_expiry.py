"""Two TVMaze name-resolution gaps (2026-10-14).

1. CleanMedia writes TVMaze's "Alien: Earth" as the folder "Alien - Earth"
   and then searched TVMaze for the dash form, which never matches: 15 shows
   (Star Trek - Picard, NCIS - Origins, Leverage - Redemption, ...) never
   resolved. A colon variant is now tried last.
2. A no-match was cached forever. TVMaze adds shows, so Outside (2026) and
   Banksters (2026) stayed "unknown" after they were listed. No-matches now
   carry a date and are re-asked after a week; legacy undated nulls are
   re-asked once.
"""
import datetime
import json

from src import tvmaze


def test_colon_variant_is_added_last():
    v = tvmaze._query_variants("Star Trek - Picard (2020)")
    assert v[0] == "star trek - picard" or v[0].lower() == "star trek - picard"
    assert v[-1].lower() == "star trek: picard"


def test_names_without_a_dash_are_unchanged():
    assert all(":" not in q for q in tvmaze._query_variants("Will Trent (2023)"))


def test_dash_name_resolves_through_the_colon_variant(monkeypatch):
    def search(q):
        if q.lower() == "alien: earth":
            return [{"show": {"id": 1, "name": "Alien: Earth", "premiered": "2025-08-12"}}]
        return []
    monkeypatch.setattr(tvmaze, "_search", search)
    assert tvmaze.lookup_show("Alien - Earth (2025)") == ("Alien - Earth", "2025"), \
        "sanitized back to the existing folder name, so no rename"


def test_no_match_is_saved_with_a_date(monkeypatch):
    monkeypatch.setattr(tvmaze, "_search", lambda q: [])
    assert tvmaze.lookup_show("Nothing Here (2099)") is None
    saved = json.loads(tvmaze._CACHE_PATH.read_text())
    assert saved["nothing here (2099)"] == {"noMatch": datetime.date.today().isoformat()}


def test_fresh_no_match_is_trusted_expired_one_is_reasked(monkeypatch):
    calls = []
    monkeypatch.setattr(tvmaze, "_search", lambda q: calls.append(q) or [])
    key = "outside (2026)"
    tvmaze._cache[key] = None
    tvmaze._no_match_at[key] = datetime.date.today().isoformat()
    assert tvmaze.lookup_show("Outside (2026)") is None and calls == [], "within a week: no request"
    tvmaze._no_match_at[key] = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()
    monkeypatch.setattr(tvmaze, "_search",
                        lambda q: [{"show": {"id": 9, "name": "Outside", "premiered": "2026-09-01"}}])
    assert tvmaze.lookup_show("Outside (2026)") == ("Outside", "2026"), "expired: asked again, now found"


def test_legacy_null_entries_load_as_unknown(monkeypatch):
    tvmaze._CACHE_PATH.write_text(json.dumps({
        "legacy (2020)": None,
        "dated (2020)": {"noMatch": "2026-10-10"},
        "hit (2020)": ["Hit", "2020"],
    }))
    monkeypatch.setattr(tvmaze, "_cache", {})
    tvmaze._load_cache()
    assert "legacy (2020)" not in tvmaze._cache, "undated null is re-asked"
    assert tvmaze._cache["dated (2020)"] is None and tvmaze._no_match_at["dated (2020)"] == "2026-10-10"
    assert tvmaze._cache["hit (2020)"] == ("Hit", "2020")
