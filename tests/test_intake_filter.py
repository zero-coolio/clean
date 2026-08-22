"""Unit tests for the structural work filter.

Pure path logic — no clock, no filesystem. Every case here is drawn from the
real library, because the whole point of this filter is that it must not
misjudge shapes that actually occur.
"""
import pytest

from src.intake_filter import (
    is_canonical_media_name,
    is_organized_show_dir,
    is_own_artifact,
    needs_processing,
)


# --- tier 1: not inside an organized show folder ---------------------------

@pytest.mark.parametrize("rel", [
    # The case that started this: a completed season pack moved in from temp.
    "Avenue 5 (2020) Season 2 S02 (1080p AMZN WEB-DL x265 HEVC 10bit DDP 5.1 Vyndros)/"
    "Avenue.5.S02E01.No.One.Wants.an.Argument.About.Reality.1080p.mkv",
    "Eastbound And Down 2009 S01-S04 1080p WEB-DL HEVC x265 BONE/S01/Eastbound.S01E04.mkv",
    "Lexx.1997.S01.AMZN.WEBRip.DDP2.0.x264-CasStudio[rartv]/Lexx.S01E01.mkv",
    "[Torrentcouch Com] Gotham/Season 04/[Torrentcouch.Com].Gotham.S04E14.mp4",
    "Spartacus/whatever.mkv",
])
def test_release_folders_always_need_processing(rel):
    assert needs_processing(rel) is True


def test_loose_episode_at_top_level_needs_processing():
    """A single new episode dropped in the root, destined for an existing show."""
    assert needs_processing("Reacher.S04E05.1080p.WEB.mkv") is True


def test_mtime_is_irrelevant():
    """No clock anywhere — a months-old file in a release folder is still work.

    This is the whole point: qBittorrent moves completed folders in from a temp
    dir, so arrival time and mtime diverge and mtime cannot be trusted.
    """
    assert needs_processing("Some.Old.Release.2019/Show.S01E01.mkv") is True


# --- tier 2: inside an organized folder, but not clean's own output --------

def test_canonical_placed_file_is_done():
    assert needs_processing(
        "Eastbound & Down (2009)/Season 02/Eastbound.&.Down.(2009).S02E05.Chapter.11.mkv"
    ) is False


def test_canonical_without_episode_title_is_still_done():
    """Title backfill is the full re-verification pass's job, not this filter's."""
    assert needs_processing("Reacher (2022)/Season 04/Reacher.(2022).S04E01.mp4") is False


def test_alt_parked_file_is_done():
    """(alt) parking must not be re-flagged — that is the 004071c ping-pong."""
    assert needs_processing(
        "Avenue 5 (2020)/Season 01/Avenue.5.(2020).S01E06.Was.It.Your.Ears (alt).mkv"
    ) is False


def test_four_digit_year_season_is_canonical():
    """Year-based seasons (c92c09c show-id renumber) are real clean output.

    A \\d{2}-only season pattern re-flags all 8 Hornblower episodes every run.
    """
    assert needs_processing(
        "C.S. Forester's Horatio Hornblower (1998)/Season 1998/"
        "C.S.Forester's.Horatio.Hornblower.(1998).S1998E01.Hornblower.The.Even.Chance.mp4"
    ) is False


@pytest.mark.parametrize("rel", [
    # Real strays that have been warning on every run for weeks.
    "Scrubs (2001)/Season 05/Scrubs - S05E21 - My Fallen Idol.rmvb",
    "The Mighty Boosh (2003)/Series 1 DVD Commentary Outtakes.mkv",
    "Top Gear (2002)/Greatest Movie Chases Ever [2007].mp4",
])
def test_non_canonical_inside_organized_folder_needs_processing(rel):
    assert needs_processing(rel) is True


def test_new_episode_dropped_into_an_existing_season_folder():
    """The case _is_recent's docstring cares about — must not be missed."""
    assert needs_processing("Reacher (2022)/Season 04/Reacher.S04E06.1080p.WEB-DL.mkv") is True


# --- tier 0: clean's own artifacts -----------------------------------------

@pytest.mark.parametrize("name", [
    ".clean-tv-journal-20260822-141520.jsonl",
    ".clean-movie-journal-20260822-171507.jsonl",
    ".DS_Store",
])
def test_own_artifacts_are_never_work(name):
    """3,631 journals had accumulated in the root; each would otherwise be a
    process_file call on every run."""
    assert is_own_artifact(name) is True
    assert needs_processing(name) is False


def test_ds_store_inside_a_release_folder_is_not_work():
    assert needs_processing("Spartacus/.DS_Store") is False


# --- predicate units -------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Reacher (2022)", True),
    ("C.S. Forester's Horatio Hornblower (1998)", True),
    ("Avenue 5 (2020) Season 2 S02 (1080p AMZN WEB-DL x265 HEVC 10bit DDP 5.1 Vyndros)", False),
    ("Spartacus", False),
    ("Show (12)", False),
    ("Show (3025)", False),
])
def test_is_organized_show_dir(name, expected):
    assert is_organized_show_dir(name) is expected


@pytest.mark.parametrize("stem,expected", [
    ("Reacher.(2022).S04E01", True),
    ("Reacher.(2022).S04E01.City.of.Brotherly.Love", True),
    ("X-Men.'97.(2024).S02E03.Rise.of.Apocalypse.Part.1", True),
    ("Scrubs - S05E21 - My Fallen Idol", False),
    ("Reacher.S04E01", False),          # no (year)
    ("Reacher.(2022).E01", False),      # no season
])
def test_is_canonical_media_name(stem, expected):
    assert is_canonical_media_name(stem) is expected


def test_empty_path_is_not_work():
    assert needs_processing("") is False


# --- run() wiring ----------------------------------------------------------

import os  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from src.service.clean_service import CleanService  # noqa: E402


class TestStructuralRun:
    """run(structural=True) selects by shape, never by mtime."""

    def _library(self, tmp_path: Path) -> Path:
        """A library reproducing today's real failure, with stale mtimes."""
        root = tmp_path / "lib"
        old = time.time() - 7200  # 2h ago: outside any --recent window

        def mk(rel: str, mtime: float) -> None:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("DATA")
            os.utime(p, (mtime, mtime))

        # Arrived from temp with stale mtimes — must STILL be processed.
        mk("Avenue 5 (2020) Season 2 S02 (1080p x265 Vyndros)/Avenue.5.S02E01.x.mkv", old)
        # Already placed by clean — must be skipped.
        mk("Avenue 5 (2020)/Season 01/Avenue.5.(2020).S01E01.I.Was.Flying.mkv", old)
        # A stray in an organized folder — must be processed.
        mk("Scrubs (2001)/Season 05/Scrubs - S05E21 - My Fallen Idol.rmvb", old)
        # clean's own journal — must never be work.
        mk(".clean-tv-journal-20260822-141520.jsonl", old)
        return root

    def _seen(self, root: Path, monkeypatch, **kwargs) -> set:
        service = CleanService()
        seen: set = set()
        monkeypatch.setattr(service, "process_file",
                            lambda path, *a, **k: seen.add(path.name))
        monkeypatch.setattr(service, "_process_audio_tracks", lambda *a, **k: None)
        monkeypatch.setattr(service, "_report_large_files", lambda *a, **k: None)
        service.run(root=root, commit=False, **kwargs)
        return seen

    def test_structural_picks_up_stale_mtime_arrivals(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch, structural=True)
        assert "Avenue.5.S02E01.x.mkv" in seen
        assert "Scrubs - S05E21 - My Fallen Idol.rmvb" in seen
        assert "Avenue.5.(2020).S01E01.I.Was.Flying.mkv" not in seen
        assert ".clean-tv-journal-20260822-141520.jsonl" not in seen

    def test_incremental_misses_them_which_is_the_bug(self, tmp_path, monkeypatch):
        """Documents the failure structural mode replaces: every file here is
        older than the window, so --recent sees nothing at all."""
        seen = self._seen(self._library(tmp_path), monkeypatch, since_seconds=3600)
        assert seen == set()

    def test_structural_overrides_the_window(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch,
                          since_seconds=3600, structural=True)
        assert "Avenue.5.S02E01.x.mkv" in seen

    def test_full_run_still_processes_everything(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch)
        assert "Avenue.5.(2020).S01E01.I.Was.Flying.mkv" in seen
