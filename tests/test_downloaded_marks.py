"""CLEAN-25: per-episode downloadedAt marks in the shared TVMaze cache.

Hermetic: conftest redirects the shared cache to a temp file and blocks the
network; TVMaze fetches are monkeypatched where a test needs one.
"""
import datetime
import json
from pathlib import Path

import pytest

from src import downloaded_marks as dm
from src import tvmaze
from src.BackfillDownloaded import collect_from_journals, episode_from_library_path
from src.service.clean_service import CleanService


def ep(s, e, airdate="2026-09-23", **extra):
    return {"season": s, "episode": e, "title": "T", "airdate": airdate, **extra}


def seed(entries):
    tvmaze._SHARED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tvmaze._SHARED_CACHE_PATH.write_text(json.dumps(entries), encoding="utf-8")
    tvmaze._episodes_cache = None


def cached(key):
    return json.loads(tvmaze._SHARED_CACHE_PATH.read_text(encoding="utf-8"))[key]["episodes"]


@pytest.fixture(autouse=True)
def _empty_pending():
    dm._pending.clear()
    yield
    dm._pending.clear()


# ---------------------------------------------------------------- pure rules

def test_apply_marks_sets_and_counts_and_ignores_unknown():
    eps, changed = dm.apply_marks([ep(1, 1), ep(1, 2)], {(1, 1): "2026-09-23", (9, 9): "2026-01-01"})
    assert changed == 1
    assert eps[0]["downloadedAt"] == "2026-09-23"
    assert "downloadedAt" not in eps[1]


def test_earliest_date_wins_and_marks_never_move_later():
    eps, changed = dm.apply_marks([ep(1, 1, downloadedAt="2026-09-20")], {(1, 1): "2026-10-01"})
    assert changed == 0 and eps[0]["downloadedAt"] == "2026-09-20"
    eps, changed = dm.apply_marks([ep(1, 1, downloadedAt="2026-09-20")], {(1, 1): "2026-09-01"})
    assert changed == 1 and eps[0]["downloadedAt"] == "2026-09-01"


def test_carry_over_copies_marks_onto_a_refetched_list():
    old = [ep(1, 1, downloadedAt="2026-09-23"), ep(1, 2)]
    new = [ep(1, 1, title="Pilot"), ep(1, 2, title="Two"), ep(1, 3)]
    out = dm.carry_over(old, new)
    assert out[0]["downloadedAt"] == "2026-09-23" and out[0]["title"] == "Pilot"
    assert "downloadedAt" not in out[1] and "downloadedAt" not in out[2]


# ------------------------------------------------------------------ I/O path

def test_mark_and_flush_write_the_shared_cache_once():
    seed({"brothers (2026)": {"episodes": [ep(1, 1), ep(1, 2)], "fetchedAt": "2026-10-01T00:00:00Z"}})
    dm.mark("Brothers (2026)", "01", "01", datetime.date(2026, 9, 23))
    dm.mark("Brothers (2026)", 1, 2, datetime.date(2026, 9, 24))
    assert dm.flush() == 2
    eps = cached("brothers (2026)")
    assert [e.get("downloadedAt") for e in eps] == ["2026-09-23", "2026-09-24"]
    assert dm.flush() == 0, "nothing pending after a flush"


def test_unknown_show_is_dropped_not_created():
    seed({})
    dm.mark("Never Cached (2020)", 1, 1)
    assert dm.flush() == 0
    assert json.loads(tvmaze._SHARED_CACHE_PATH.read_text()) == {}


def test_refetch_keeps_marks(monkeypatch):
    seed({"show (2020)": {"episodes": [ep(1, 1, downloadedAt="2026-01-02")], "fetchedAt": "2026-01-01T00:00:00Z"}})
    monkeypatch.setattr(tvmaze, "_resolve_show_id", lambda name, logger=None: 1)
    monkeypatch.setattr(tvmaze, "_fetch_all_episodes", lambda show_id: [ep(1, 1, title="New"), ep(1, 2)])
    tvmaze._fetch_and_store_episodes("Show (2020)", "show (2020)", replaces=cached("show (2020)"))
    eps = cached("show (2020)")
    assert eps[0]["downloadedAt"] == "2026-01-02" and eps[0]["title"] == "New"
    assert "downloadedAt" not in eps[1]


# ---------------------------------------------------------------- the hook

def test_service_hook_marks_only_in_commit_mode():
    seed({"brothers (2026)": {"episodes": [ep(1, 1)], "fetchedAt": "2026-10-01T00:00:00Z"}})
    svc = CleanService()
    svc._note_in_library(("Brothers (2026)", "01", "01", ""), commit=False)
    assert dm._pending == {}, "a dry run must not mark anything"
    svc._note_in_library(("Brothers (2026)", "01", "01", ""), commit=True)
    assert dm.flush() == 1
    assert cached("brothers (2026)")[0]["downloadedAt"] == datetime.date.today().isoformat()


# ---------------------------------------------------------------- backfill

def test_library_path_parsing(tmp_path):
    root = tmp_path
    good = root / "NCIS - Origins (2024)" / "Season 03" / "NCIS.-.Origins.(2024).S03E02.mkv"
    assert episode_from_library_path(good, root) == ("NCIS - Origins (2024)", 3, 2)
    assert episode_from_library_path(root / "loose.S01E01.mkv", root) is None
    assert episode_from_library_path(root / "No Year" / "Season 01" / "x.S01E01.mkv", root) is None


def test_journals_seed_marks_dated_by_the_journal(tmp_path):
    root = tmp_path
    dst = root / "Brothers (2026)" / "Season 01" / "Brothers.(2026).S01E01.Pilot.mkv"
    lines = [
        {"op": "qbit_remove", "hash": "x", "name": "Brothers 2026 S01E01"},
        {"op": "move", "src": str(root / "Brothers.2026.S01E01.mkv"), "dst": str(dst)},
        {"op": "move", "src": "a.srt", "dst": str(dst.with_suffix(".srt"))},   # sidecar: ignored
        {"op": "trash", "path": str(dst)},
    ]
    (root / ".clean-tv-journal-20260923-120000.jsonl").write_text("\n".join(json.dumps(l) for l in lines))
    marks = {}
    assert collect_from_journals(root, marks) == 1
    assert marks == {"brothers (2026)": {(1, 1): "2026-09-23"}}
