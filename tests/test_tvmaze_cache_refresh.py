"""Tests for wiring the staleness rule into CleanMedia's cache paths.

Hermetic: every TVMaze network call is monkeypatched. The shared cache path is
redirected to a temp file by the autouse fixture in conftest.py.
"""
import datetime
import json

import pytest

from src import tvmaze
from src.tvmaze_refresh import RefreshReport, refresh_stale_entries, select_stale_keys

NOW = datetime.date(2026, 8, 21)


def ep(season, episode, airdate, title="T"):
    return {"season": season, "episode": episode, "title": title, "airdate": airdate}


def seed(entries):
    """Write entries straight to the (temp) shared cache and clear the memo."""
    tvmaze._SHARED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tvmaze._SHARED_CACHE_PATH.write_text(json.dumps(entries), encoding="utf-8")
    tvmaze._episodes_cache = None


def read_cache():
    return json.loads(tvmaze._SHARED_CACHE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def net(monkeypatch):
    """Fake TVMaze. `net.episodes` is what a fetch returns; `net.fetches` logs ids."""

    class Net:
        def __init__(self):
            self.episodes = []
            self.fetches = []
            self.resolved = []

        def resolve(self, name, logger=None):
            self.resolved.append(name)
            return 1234

        def fetch(self, show_id):
            self.fetches.append(show_id)
            return list(self.episodes)

    n = Net()
    monkeypatch.setattr(tvmaze, "_resolve_show_id", n.resolve)
    monkeypatch.setattr(tvmaze, "_fetch_all_episodes", n.fetch)
    return n


STALE = {"episodes": [ep(3, 8, "2025-03-27")], "fetchedAt": "2026-06-21T19:21:03Z"}
FRESH = {"episodes": [ep(1, 1, "2026-08-01"), ep(1, 2, "2099-01-01")], "fetchedAt": "2026-06-21T19:21:03Z"}
ENDED = {"episodes": [ep(7, 13, "2014-12-09")], "fetchedAt": "2026-07-14T04:30:25Z"}


# --- lazy heal inside _ensure_show_episodes --------------------------------

def test_entry_with_forward_data_is_served_without_fetching(net):
    seed({"live show (2026)": FRESH})
    got = tvmaze._ensure_show_episodes("Live Show (2026)")
    assert len(got) == 2
    assert net.fetches == []


def test_finished_show_outside_window_is_served_without_fetching(net):
    seed({"sons of anarchy (2008)": ENDED})
    tvmaze._ensure_show_episodes("Sons of Anarchy (2008)")
    assert net.fetches == []


def test_stale_entry_is_refetched_and_written_back(net):
    seed({"reacher (2022)": STALE})
    net.episodes = [ep(s, e, "2026-03-0{}".format(e)) for s in (1, 2, 3, 4) for e in (1, 2)]
    got = tvmaze._ensure_show_episodes("Reacher (2022)")
    assert len(got) == 8
    assert net.fetches == [1234]
    assert len(read_cache()["reacher (2022)"]["episodes"]) == 8


def test_stale_entry_refetched_at_most_once_per_process(net):
    """_ensure_show_episodes runs per FILE. A season pack must not fan out into
    one network fetch per file — and a still-stale-after-refresh show (finished
    recently, no forward data) would otherwise never stop re-fetching."""
    seed({"reacher (2022)": STALE})
    net.episodes = [ep(3, 8, "2025-03-27")]  # unchanged: still stale after refresh
    for _ in range(5):
        tvmaze._ensure_show_episodes("Reacher (2022)")
    assert net.fetches == [1234]


def test_failed_refresh_keeps_the_cached_episodes(net):
    """TVMaze unreachable must not blank a good entry."""
    seed({"reacher (2022)": STALE})
    net.episodes = []  # empty fetch == failure
    got = tvmaze._ensure_show_episodes("Reacher (2022)")
    assert got == STALE["episodes"]
    assert read_cache()["reacher (2022)"] == STALE


def test_unresolvable_show_on_refresh_keeps_the_cached_episodes(net, monkeypatch):
    seed({"reacher (2022)": STALE})
    monkeypatch.setattr(tvmaze, "_resolve_show_id", lambda name, logger=None: None)
    assert tvmaze._ensure_show_episodes("Reacher (2022)") == STALE["episodes"]
    assert read_cache()["reacher (2022)"] == STALE


def test_cold_miss_still_fetches_and_stores(net):
    seed({})
    net.episodes = [ep(1, 1, "2026-01-01")]
    assert tvmaze._ensure_show_episodes("New Show (2026)") == net.episodes
    assert "new show (2026)" in read_cache()


def test_refresh_preserves_key_and_schema(net):
    """The on-disk shape is byte-compatible with lime — do not drift it."""
    seed({"reacher (2022)": STALE, "sons of anarchy (2008)": ENDED})
    net.episodes = [ep(4, 1, "2026-08-01", title="Fresh")]
    tvmaze._ensure_show_episodes("Reacher (2022)")
    data = read_cache()
    assert set(data) == {"reacher (2022)", "sons of anarchy (2008)"}
    entry = data["reacher (2022)"]
    assert set(entry) == {"episodes", "fetchedAt"}
    assert set(entry["episodes"][0]) == {"season", "episode", "title", "airdate"}
    assert entry["fetchedAt"] != STALE["fetchedAt"]
    assert data["sons of anarchy (2008)"] == ENDED  # untouched entry preserved


# --- the whole-cache sweep -------------------------------------------------

def test_select_stale_keys_picks_only_stale_and_sorts(net):
    cache = {"zzz (2020)": STALE, "live show (2026)": FRESH, "aaa (2019)": STALE}
    assert select_stale_keys(cache, now=NOW) == ["aaa (2019)", "zzz (2020)"]


def test_sweep_dry_run_fetches_nothing(net):
    seed({"reacher (2022)": STALE, "live show (2026)": FRESH})
    report = refresh_stale_entries(commit=False, now=NOW)
    assert (report.total, report.selected, report.attempted) == (2, 1, 0)
    assert net.fetches == []
    assert read_cache()["reacher (2022)"] == STALE


def test_sweep_commit_refetches_only_stale_entries(net):
    seed({"reacher (2022)": STALE, "live show (2026)": FRESH, "sons of anarchy (2008)": ENDED})
    net.episodes = [ep(4, 1, "2026-08-01"), ep(4, 2, "2026-08-08")]
    report = refresh_stale_entries(commit=True, now=NOW)
    assert (report.total, report.selected, report.attempted) == (3, 1, 1)
    assert report.changed == [("reacher (2022)", 1, 2)]
    assert net.fetches == [1234]
    assert net.resolved == ["reacher (2022)"]  # re-fetched under its year-stamped key


def test_sweep_limit_bounds_the_work(net):
    seed({"aaa (2019)": STALE, "bbb (2020)": STALE, "ccc (2021)": STALE})
    net.episodes = [ep(1, 1, "2026-08-01")]
    report = refresh_stale_entries(commit=True, limit=2, now=NOW)
    assert (report.selected, report.attempted) == (3, 2)
    assert net.resolved == ["aaa (2019)", "bbb (2020)"]  # sorted, so reproducible


def test_sweep_counts_failures_without_losing_data(net):
    seed({"reacher (2022)": STALE})
    net.episodes = []
    report = refresh_stale_entries(commit=True, now=NOW)
    assert (report.attempted, report.failed, report.changed) == (1, 1, [])
    assert read_cache()["reacher (2022)"] == STALE


def test_sweep_counts_unchanged_separately_from_corrected(net):
    seed({"reacher (2022)": STALE})
    net.episodes = list(STALE["episodes"])
    report = refresh_stale_entries(commit=True, now=NOW)
    assert (report.unchanged, report.changed) == (1, [])


def test_report_summary_is_readable():
    r = RefreshReport(total=358, selected=191, attempted=191, unchanged=169, failed=0)
    r.changed = [("reacher (2022)", 24, 32)]
    assert "358 cached" in r.summary() and "191 stale" in r.summary()


def test_refresh_resolving_to_a_different_show_is_discarded(net):
    """A mis-resolved name must never overwrite a good entry in a file lime
    reads and cannot repair."""
    cached = {
        "episodes": [ep(1, 1, "2025-01-01", "Welcome to Wherever"),
                     ep(1, 2, "2025-01-08", "Paper Route")],
        "fetchedAt": "2026-06-21T19:21:03Z",
    }
    seed({"some show (2025)": cached})
    net.episodes = [ep(1, 1, "2013-01-01", "Naoki and Kotoko"),
                    ep(1, 2, "2013-01-08", "The First Kiss")]
    got = tvmaze._ensure_show_episodes("Some Show (2025)")
    assert got == cached["episodes"]
    assert read_cache()["some show (2025)"] == cached


def test_sweep_counts_a_rejected_replacement_as_a_failure(net):
    cached = {
        "episodes": [ep(1, 1, "2025-01-01", "Alpha"), ep(1, 2, "2025-01-08", "Beta")],
        "fetchedAt": "2026-06-21T19:21:03Z",
    }
    seed({"some show (2025)": cached})
    net.episodes = [ep(1, 1, "2013-01-01", "Zulu"), ep(1, 2, "2013-01-08", "Yankee")]
    report = refresh_stale_entries(commit=True, now=NOW)
    assert (report.attempted, report.failed) == (1, 1)
    assert read_cache()["some show (2025)"] == cached


def test_cold_miss_is_not_blocked_by_the_guard(net):
    """Nothing cached means nothing to protect."""
    seed({})
    net.episodes = [ep(1, 1, "2026-01-01", "Anything"), ep(1, 2, "2026-01-08", "At All")]
    assert len(tvmaze._ensure_show_episodes("New Show (2026)")) == 2


def test_title_only_correction_counts_as_changed_not_unchanged(net):
    """TVMaze filling in placeholder titles is a real fix; calling it
    "unchanged" because the count held steady would understate the sweep."""
    seed({"lucky (2026)": {
        "episodes": [ep(1, 1, "2026-07-15", "No Shortcuts"),
                     ep(1, 2, "2026-07-22", "Make 'em Dance"),
                     ep(1, 3, "2026-07-29", "Episode 3")],
        "fetchedAt": "2026-06-21T19:21:03Z",
    }})
    net.episodes = [ep(1, 1, "2026-07-15", "No Shortcuts"),
                    ep(1, 2, "2026-07-22", "Make 'em Dance"),
                    ep(1, 3, "2026-07-29", "Read the Room")]
    report = refresh_stale_entries(commit=True, now=NOW)
    assert report.changed == [("lucky (2026)", 3, 3)]
    assert report.unchanged == 0
    assert report.count_changes == 0
    assert read_cache()["lucky (2026)"]["episodes"][2]["title"] == "Read the Room"


def test_identical_refetch_is_reported_as_unchanged(net):
    seed({"reacher (2022)": STALE})
    net.episodes = list(STALE["episodes"])
    report = refresh_stale_entries(commit=True, now=NOW)
    assert (report.unchanged, report.changed) == (1, [])
