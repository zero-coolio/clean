"""Unit tests for the qBittorrent remove-before-rename policy.

These exercise the PURE logic (path matching, completeness, reaper decisions)
with an in-memory fake client — no network, no live qBittorrent.
"""
import logging

import pytest

from src.qbittorrent import (
    QbitReaper,
    find_torrent_for_path,
    torrent_is_complete,
    REMOVED,
    ZOMBIE,
    NONE,
)


def _torrent(**kw):
    """A torrent dict with sensible defaults; override per test."""
    base = {
        "hash": "h1",
        "name": "Some.Show.S01E01",
        "content_path": "/data/Some.Show.S01E01.mkv",
        "state": "stalledUP",
        "progress": 1.0,
        "amount_left": 0,
    }
    base.update(kw)
    return base


class FakeClient:
    """Stand-in for QbitClient: records delete calls, returns a fixed result."""

    def __init__(self, delete_ok=True):
        self.delete_ok = delete_ok
        self.deleted = []  # list of (hash, delete_files)

    def delete_torrent(self, torrent_hash, delete_files=False):
        self.deleted.append((torrent_hash, delete_files))
        return self.delete_ok


# --------------------------------------------------------------------------- #
# torrent_is_complete
# --------------------------------------------------------------------------- #

def test_complete_when_amount_left_zero():
    assert torrent_is_complete(_torrent(amount_left=0, progress=0.4)) is True


def test_incomplete_when_amount_left_positive():
    assert torrent_is_complete(_torrent(amount_left=123, progress=1.0)) is False


def test_complete_falls_back_to_progress_when_amount_left_missing():
    t = {"progress": 1.0}
    assert torrent_is_complete(t) is True
    assert torrent_is_complete({"progress": 0.99}) is False


def test_incomplete_when_no_signals():
    assert torrent_is_complete({}) is False


# --------------------------------------------------------------------------- #
# find_torrent_for_path
# --------------------------------------------------------------------------- #

def test_match_single_file_exact():
    t = _torrent(content_path="/data/Show.S01E01.mkv")
    assert find_torrent_for_path([t], "/data/Show.S01E01.mkv") is t


def test_match_file_under_multifile_content_path():
    # Multi-file torrent: content_path is the root FOLDER.
    t = _torrent(content_path="/data/Season Pack")
    found = find_torrent_for_path([t], "/data/Season Pack/Show.S01E03.mkv")
    assert found is t


def test_no_match_returns_none():
    t = _torrent(content_path="/data/Other.mkv")
    assert find_torrent_for_path([t], "/data/Show.S01E01.mkv") is None


def test_no_match_on_sibling_prefix():
    # "/data/Show" must NOT match "/data/ShowExtra.mkv" (prefix-but-not-path).
    t = _torrent(content_path="/data/Show")
    assert find_torrent_for_path([t], "/data/ShowExtra.mkv") is None


def test_empty_content_path_skipped():
    t = _torrent(content_path="")
    assert find_torrent_for_path([t], "/data/anything.mkv") is None


# --------------------------------------------------------------------------- #
# QbitReaper.decide (pure)
# --------------------------------------------------------------------------- #

def _reaper(torrents, delete_ok=True):
    return QbitReaper(FakeClient(delete_ok=delete_ok), torrents, logger=logging.getLogger("test"))


def test_decide_removed_when_complete():
    t = _torrent(amount_left=0)
    outcome, matched = _reaper([t]).decide(t["content_path"])
    assert outcome == REMOVED and matched is t


def test_decide_zombie_when_incomplete():
    t = _torrent(amount_left=500, progress=0.5)
    outcome, matched = _reaper([t]).decide(t["content_path"])
    assert outcome == ZOMBIE and matched is t


def test_decide_none_when_no_torrent():
    outcome, matched = _reaper([]).decide("/data/orphan.mkv")
    assert outcome == NONE and matched is None


def test_decide_none_when_complete_but_empty_content_path():
    # Observed live: a completed torrent can have content_path == "" when
    # qBittorrent has lost track of its files. We can't locate a file for it,
    # so it must resolve to NONE and never be removed (safe — no false delete).
    t = _torrent(amount_left=0, content_path="")
    outcome, matched = _reaper([t]).decide("/data/Some.Show.S01E01.mkv")
    assert outcome == NONE and matched is None


def test_decide_none_after_already_removed():
    t = _torrent(amount_left=0)
    reaper = _reaper([t])
    reaper._removed.add(t["hash"])
    outcome, _ = reaper.decide(t["content_path"])
    assert outcome == NONE


# --------------------------------------------------------------------------- #
# QbitReaper.clear_to_move (side effects)
# --------------------------------------------------------------------------- #

def test_clear_removes_completed_torrent_on_commit():
    t = _torrent(amount_left=0)
    client = FakeClient()
    reaper = QbitReaper(client, [t], logger=logging.getLogger("test"))
    journal = []
    should_move, reason = reaper.clear_to_move(t["content_path"], commit=True, journal=journal)
    assert should_move is True and reason is None
    assert client.deleted == [(t["hash"], False)]           # data kept
    assert journal == [{"op": "qbit_remove", "hash": t["hash"],
                        "name": t["name"], "delete_files": False}]
    assert t["hash"] in reaper._removed


def test_clear_dry_run_does_not_delete():
    t = _torrent(amount_left=0)
    client = FakeClient()
    reaper = QbitReaper(client, [t], logger=logging.getLogger("test"))
    journal = []
    should_move, reason = reaper.clear_to_move(t["content_path"], commit=False, journal=journal)
    assert should_move is True and reason is None
    assert client.deleted == []        # nothing removed in dry-run
    assert journal == []


def test_clear_zombie_blocks_move():
    t = _torrent(amount_left=999, progress=0.3, state="downloading")
    client = FakeClient()
    reaper = QbitReaper(client, [t], logger=logging.getLogger("test"))
    should_move, reason = reaper.clear_to_move(t["content_path"], commit=True, journal=[])
    assert should_move is False
    assert "zombie" in reason
    assert client.deleted == []        # never touch an incomplete torrent


def test_clear_blocks_move_when_delete_fails():
    t = _torrent(amount_left=0)
    client = FakeClient(delete_ok=False)
    reaper = QbitReaper(client, [t], logger=logging.getLogger("test"))
    journal = []
    should_move, reason = reaper.clear_to_move(t["content_path"], commit=True, journal=journal)
    assert should_move is False
    assert "removal failed" in reason
    assert journal == []               # no journal entry on failure


def test_clear_passes_through_orphan_file():
    should_move, reason = _reaper([]).clear_to_move("/data/orphan.mkv", commit=True, journal=[])
    assert should_move is True and reason is None


def test_multifile_torrent_removed_once_then_siblings_pass():
    # One multi-file torrent, two episodes underneath it.
    t = _torrent(content_path="/data/Pack", amount_left=0)
    client = FakeClient()
    reaper = QbitReaper(client, [t], logger=logging.getLogger("test"))
    journal = []
    a = reaper.clear_to_move("/data/Pack/E01.mkv", commit=True, journal=journal)
    b = reaper.clear_to_move("/data/Pack/E02.mkv", commit=True, journal=journal)
    assert a == (True, None) and b == (True, None)
    assert client.deleted == [(t["hash"], False)]   # removed exactly once
    assert len(journal) == 1
