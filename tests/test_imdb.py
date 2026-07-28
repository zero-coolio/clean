"""Tests for the IMDb movie resolver's strict gate (offline — _fetch mocked).

The whole point of this module is that a movie can NEVER be renamed onto the
wrong title (the failure that lost files), so the tests focus on rejection:
TV types, non-exact titles, and off-by-year candidates must all return None.
"""
from __future__ import annotations

import pytest

import src.imdb as imdb


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # No disk cache, fresh in-memory cache, no network, no rate-limit sleeps.
    monkeypatch.setattr(imdb, "_cache", {})
    monkeypatch.setattr(imdb, "_save_cache", lambda: None)
    monkeypatch.setattr(imdb, "_MIN_INTERVAL", 0.0)


def _mock(entries):
    return lambda title: entries


# Realistic IMDb suggestion payloads (id/l/y/qid as the endpoint returns them).
SHELTER = [
    {"id": "tt32357218", "l": "Shelter", "y": 2026, "qid": "movie"},
    {"id": "tt1675192", "l": "Take Shelter", "y": 2011, "qid": "movie"},
    {"id": "tt0942384", "l": "Shelter", "y": 2007, "qid": "movie"},
    {"id": "tt15483276", "l": "Harlan Coben's Shelter", "y": 2023, "qid": "tvMiniSeries"},
]


def test_exact_title_and_year_matches(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(SHELTER))
    assert imdb.resolve_movie("Shelter", "2026") == ("Shelter", "2026")


def test_year_disambiguates_same_title(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(SHELTER))
    # Two "Shelter" movies exist; the 2007 one is picked for a 2007 folder.
    assert imdb.resolve_movie("Shelter", "2007") == ("Shelter", "2007")


def test_year_within_one_accepted(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(
        [{"id": "tt27681354", "l": "In the Grey", "y": 2026, "qid": "movie"}]))
    assert imdb.resolve_movie("In the Grey", "2025") == ("In the Grey", "2026")


def test_year_off_by_more_than_one_rejected(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(SHELTER))
    # Folder says 2015 but only 2026/2007 exist → ambiguous → None.
    assert imdb.resolve_movie("Shelter", "2015") is None


def test_tv_series_never_matches_a_movie(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(
        [{"id": "tt15483276", "l": "Shelter", "y": 2023, "qid": "tvSeries"}]))
    assert imdb.resolve_movie("Shelter", "2023") is None


def test_non_exact_title_rejected(monkeypatch):
    # "Take Shelter" must not match a bare "Shelter" query, and vice-versa.
    monkeypatch.setattr(imdb, "_fetch", _mock(
        [{"id": "tt1", "l": "Gray Shelter", "y": 2024, "qid": "movie"},
         {"id": "tt2", "l": "The Sheltering Sky", "y": 1990, "qid": "movie"}]))
    assert imdb.resolve_movie("Shelter", "2024") is None


def test_person_entries_ignored(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(
        [{"id": "nm0733427", "l": "Shelter Somebody", "y": None, "qid": None},
         {"id": "tt9", "l": "Shelter", "y": 2026, "qid": "movie"}]))
    assert imdb.resolve_movie("Shelter", "2026") == ("Shelter", "2026")


def test_no_year_takes_top_exact_movie(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(SHELTER))
    assert imdb.resolve_movie("Shelter", None) == ("Shelter", "2026")


def test_article_and_punctuation_folding(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock(
        [{"id": "tt5", "l": "Wallace & Gromit: Vengeance Most Fowl", "y": 2024, "qid": "tvMovie"}]))
    # "Wallace and Gromit Vengeance Most Fowl" ↔ "Wallace & Gromit: Vengeance…"
    assert imdb.resolve_movie(
        "Wallace and Gromit Vengeance Most Fowl", "2024"
    ) == ("Wallace & Gromit: Vengeance Most Fowl", "2024")


def test_empty_results_returns_none(monkeypatch):
    monkeypatch.setattr(imdb, "_fetch", _mock([]))
    assert imdb.resolve_movie("Whatever", "2020") is None
