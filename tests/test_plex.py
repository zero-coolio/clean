"""Tests for the Plex rescan notification.

Hermetic: every test stubs `src.plex._get`, the module's single network seam.
conftest blocks urllib outright, so a test that forgot to stub would fail
loudly rather than reach the real server.

The sections fixture is the real shape returned by the live server on
2026-10-25, including the movie library spanning three volumes, because the
multi-location case is what makes section matching non-trivial.
"""
import pytest

from src import plex


SECTIONS = [
    ("2", ["/Volumes/Seagate/movie-archive",
           "/Volumes/Summer/movie-archive",
           "/Volumes/Seagate/seagate-movie"]),
    ("3", ["/Volumes/Seagate/temp"]),
    ("1", ["/Volumes/Summer/tv-archive",
           "/Volumes/Seagate/seagate-qBittorrent"]),
]


@pytest.fixture
def calls(monkeypatch):
    """Record every URL the module would request; answer all of them OK."""
    recorded: list[str] = []

    def fake_get(url, timeout):
        recorded.append(url)
        if "/library/sections?" in url:
            return (
                b'<MediaContainer>'
                b'<Directory key="2"><Location path="/Volumes/Seagate/seagate-movie"/></Directory>'
                b'<Directory key="1"><Location path="/Volumes/Seagate/seagate-qBittorrent"/></Directory>'
                b'</MediaContainer>'
            )
        return b""

    monkeypatch.setattr(plex, "_get", fake_get)
    monkeypatch.setattr(plex, "PLEX_TOKEN", "test-token")
    return recorded


def scans(calls):
    """Just the refresh requests, with the token stripped for readability."""
    return [c for c in calls if "/refresh?" in c]


# --- section matching -------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/Volumes/Seagate/seagate-movie/F1 (2025)", "2"),
    ("/Volumes/Seagate/seagate-qBittorrent/Watchmen (2019)/Season 01", "1"),
    ("/Volumes/Seagate/temp/Something", "3"),
    ("/Volumes/Summer/movie-archive/Heat (1995)", "2"),
    # A library root is inside itself.
    ("/Volumes/Seagate/seagate-movie", "2"),
])
def test_section_for(path, expected):
    assert plex.section_for(path, SECTIONS) == expected


@pytest.mark.parametrize("path", [
    "/Users/stephenleonard/somewhere-else",
    "/Volumes/Seagate",                      # the parent of two libraries, not a library
    "/Volumes/Seagate/seagate-movie-other",  # prefix of a library, not inside it
])
def test_paths_outside_every_library_match_nothing(path):
    """A near miss must miss. Matching on a string prefix would put
    "seagate-movie-other" in the movie library."""
    assert plex.section_for(path, SECTIONS) is None


def test_the_longest_matching_location_wins():
    """A library nested inside another belongs to the nested one."""
    nested = [("1", ["/Volumes/Seagate"]), ("9", ["/Volumes/Seagate/seagate-movie"])]
    assert plex.section_for("/Volumes/Seagate/seagate-movie/F1 (2025)", nested) == "9"


# --- what a journal says changed --------------------------------------------

def test_both_ends_of_a_move_are_reported():
    """The destination gained a file and the source lost one. Plex has to be
    told about each, or the old location keeps showing a file that is gone."""
    assert plex.paths_from_journal([
        {"op": "move", "src": "/lib/Old Folder/x.mkv", "dst": "/lib/New Folder/y.mkv"},
    ]) == ["/lib/Old Folder/x.mkv", "/lib/New Folder/y.mkv"]


def test_trash_and_delete_count_as_changes():
    assert plex.paths_from_journal([
        {"op": "trash", "path": "/lib/Show/junk.nfo"},
        {"op": "delete", "path": "/lib/Other/sample.mkv"},
    ]) == ["/lib/Show/junk.nfo", "/lib/Other/sample.mkv"]


def test_entries_without_paths_are_ignored():
    """qbit_remove carries a torrent hash, not a path."""
    assert plex.paths_from_journal([
        {"op": "qbit_remove", "hash": "abc", "name": "Some.Release"},
        {"op": "move", "src": None, "dst": None},
    ]) == []


def test_an_empty_journal_asks_for_nothing():
    assert plex.paths_from_journal([]) == []
    assert plex.paths_from_journal(None) == []


def test_the_journal_is_not_reduced_to_directories_here():
    """paths_from_journal returns paths, not directories. Reducing here as
    well as in notify_paths applies it twice, and a release folder clean has
    already deleted then walks up to the library root, turning a targeted scan
    into a scan of everything."""
    out = plex.paths_from_journal([
        {"op": "move", "src": "/lib/Deleted.Release/x.mkv", "dst": "/lib/Show/y.mkv"},
    ])
    assert out == ["/lib/Deleted.Release/x.mkv", "/lib/Show/y.mkv"]
    # and the reduction happens exactly once, downstream
    assert plex._directories(out) == ["/lib/Deleted.Release", "/lib/Show"]


def test_directories_are_deduped_in_order():
    assert plex._directories(
        ["/lib/A/1.mkv", "/lib/B/1.mkv", "/lib/A/2.mkv", "/lib/B/2.mkv"]
    ) == ["/lib/A", "/lib/B"]


# --- notification -----------------------------------------------------------

def test_a_targeted_scan_passes_the_directory(calls):
    """Regression: _url's first parameter was named `path`, which collided
    with Plex's own `path=` scan parameter and made every targeted scan raise
    TypeError. Fail-soft turned it into a log line, so only a live run caught
    it. Assert the parameter actually arrives."""
    plex.notify_paths(["/Volumes/Seagate/seagate-movie/F1 (2025)"])
    assert len(scans(calls)) == 1
    assert "path=%2FVolumes%2FSeagate%2Fseagate-movie%2FF1+%282025%29" in scans(calls)[0]
    assert "/library/sections/2/refresh?" in scans(calls)[0]


def test_each_section_is_scanned(calls):
    plex.notify_paths([
        "/Volumes/Seagate/seagate-movie/F1 (2025)",
        "/Volumes/Seagate/seagate-qBittorrent/Watchmen (2019)",
    ])
    assert len(scans(calls)) == 2
    assert any("/sections/1/refresh?" in c for c in scans(calls))
    assert any("/sections/2/refresh?" in c for c in scans(calls))


def test_paths_outside_plex_are_not_requested(calls):
    plex.notify_paths(["/Users/stephenleonard/scratch/thing.mkv"])
    assert scans(calls) == []


def test_no_token_means_no_request_at_all(monkeypatch):
    """Self-gating, like TMDB. Landing this module changes nothing until a
    token is set, so it cannot alter the watcher's behaviour by existing."""
    seen = []
    monkeypatch.setattr(plex, "_get", lambda url, timeout: seen.append(url))
    monkeypatch.setattr(plex, "PLEX_TOKEN", None)
    plex.notify_paths(["/Volumes/Seagate/seagate-movie/F1 (2025)"])
    assert seen == []


def test_many_directories_become_one_section_scan(calls, monkeypatch):
    """Past the cap, a single section scan: cheaper than hundreds of requests
    and strictly more thorough, so the fallback widens coverage, never loses
    it."""
    monkeypatch.setattr(plex, "PLEX_MAX_TARGETED_SCANS", 3)
    plex.notify_paths(
        [f"/Volumes/Seagate/seagate-movie/Film {i} (2020)/Film {i} (2020).mkv"
         for i in range(10)]
    )
    assert len(scans(calls)) == 1
    assert "path=" not in scans(calls)[0], "a section scan must not be path-scoped"


# --- it must never break a run ----------------------------------------------

def test_a_raising_transport_is_swallowed(monkeypatch, caplog):
    """The whole point. By the time this runs the files have already moved."""
    monkeypatch.setattr(plex, "PLEX_TOKEN", "test-token")
    monkeypatch.setattr(plex, "_get", lambda url, timeout: (_ for _ in ()).throw(OSError("boom")))
    plex.notify_paths(["/Volumes/Seagate/seagate-movie/F1 (2025)"])  # must not raise


def test_an_unreachable_server_is_swallowed(monkeypatch):
    """_get returns None on any failure, so sections come back empty."""
    monkeypatch.setattr(plex, "PLEX_TOKEN", "test-token")
    monkeypatch.setattr(plex, "_get", lambda url, timeout: None)
    plex.notify_paths(["/Volumes/Seagate/seagate-movie/F1 (2025)"])  # must not raise


def test_malformed_xml_is_swallowed(monkeypatch):
    monkeypatch.setattr(plex, "PLEX_TOKEN", "test-token")
    monkeypatch.setattr(plex, "_get", lambda url, timeout: b"<not-xml")
    plex.notify_paths(["/Volumes/Seagate/seagate-movie/F1 (2025)"])  # must not raise


def test_the_budget_stops_a_slow_server(calls, monkeypatch):
    """A notification may not hold up a finished run. With the budget already
    spent, it gives up instead of working through the backlog."""
    monkeypatch.setattr(plex, "PLEX_NOTIFY_BUDGET", -1.0)
    plex.notify_paths([
        "/Volumes/Seagate/seagate-movie/F1 (2025)",
        "/Volumes/Seagate/seagate-qBittorrent/Watchmen (2019)",
    ])
    assert scans(calls) == []


def test_the_token_never_appears_in_a_log(monkeypatch, caplog):
    """_get logs only the part before the "?", and the token lives after it."""
    import logging
    monkeypatch.setattr(plex, "PLEX_TOKEN", "sup3rs3cr3t")
    monkeypatch.setattr(plex.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    with caplog.at_level(logging.DEBUG, logger="plex"):
        plex._get(plex._url("/library/sections", "sup3rs3cr3t"), 1.0)
    assert "sup3rs3cr3t" not in caplog.text


# --- wiring into a run ------------------------------------------------------

from pathlib import Path  # noqa: E402

from src.service.clean_service import CleanService  # noqa: E402


class TestRunNotifies:
    """run() tells Plex what it changed, and only when it changed something."""

    def _library(self, tmp_path):
        root = tmp_path / "intake"
        wrapper = root / "Reacher.S04.1080p.WEB-GROUP"
        wrapper.mkdir(parents=True)
        (wrapper / "Reacher.S04E01.1080p.WEB-GROUP.mkv").write_text("DATA")
        return root

    def _service(self, monkeypatch, notified):
        svc = CleanService()
        monkeypatch.setattr(svc, "_process_audio_tracks", lambda *a, **k: None)
        monkeypatch.setattr(svc, "_report_large_files", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(plex, "notify_paths",
                            lambda paths, logger=None: notified.extend(paths))
        return svc

    def test_a_commit_run_reports_what_moved(self, tmp_path, monkeypatch):
        notified: list[str] = []
        root = self._library(tmp_path)
        self._service(monkeypatch, notified).run(root=root, commit=True)
        assert notified, "a run that moved files must tell Plex"
        assert any("Reacher" in p for p in notified)

    def test_a_dry_run_tells_plex_nothing(self, tmp_path, monkeypatch):
        """Nothing changed on disk, so there is nothing to rescan."""
        notified: list[str] = []
        root = self._library(tmp_path)
        self._service(monkeypatch, notified).run(root=root, commit=False)
        assert notified == []

    def test_a_run_that_changed_nothing_tells_plex_nothing(self, tmp_path, monkeypatch):
        """A root holding only an unparseable file: nothing moves, so there is
        nothing to rescan. Not an EMPTY root, which crashes a commit run on
        main for unrelated reasons (cleanup_empty_dirs removes the root before
        the journal is written)."""
        notified: list[str] = []
        root = tmp_path / "quiet"
        root.mkdir()
        (root / "notes.txt").write_text("nothing media about this")
        self._service(monkeypatch, notified).run(root=root, commit=True)
        assert notified == []

    def test_a_failing_notification_does_not_fail_the_run(self, tmp_path, monkeypatch):
        """The guarantee that matters, and it is tested by breaking the guard
        itself. notify_paths promises not to raise; this replaces it with one
        that does, which is what an ImportError on the lazy import, or a bug in
        the guard, would look like. The call site must survive that alone."""
        root = self._library(tmp_path)
        svc = CleanService()
        monkeypatch.setattr(svc, "_process_audio_tracks", lambda *a, **k: None)
        monkeypatch.setattr(svc, "_report_large_files", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(plex, "notify_paths",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("plex exploded")))

        with pytest.raises(RuntimeError):
            plex.notify_paths([])          # the stub really does raise
        svc.run(root=root, commit=True)    # and the run still completes

        dest = root / "Reacher" / "Season 04" / "Reacher.S04E01.mkv"
        assert dest.exists(), "the move must survive a broken notifier"
