"""Unit tests for the structural work filter.

Pure path logic — no clock, no filesystem. Every case here is drawn from the
real library, because the whole point of this filter is that it must not
misjudge shapes that actually occur.
"""
import pytest

from src.intake_filter import (
    is_canonical_media_name,
    is_organized_dir,
    is_own_artifact,
    is_placed_movie_file,
    is_season_dir,
    movie_needs_processing,
    tv_needs_processing,
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
    assert tv_needs_processing(rel) is True


def test_loose_episode_at_top_level_needs_processing():
    """A single new episode dropped in the root, destined for an existing show."""
    assert tv_needs_processing("Reacher.S04E05.1080p.WEB.mkv") is True


def test_mtime_is_irrelevant():
    """No clock anywhere — a months-old file in a release folder is still work.

    This is the whole point: qBittorrent moves completed folders in from a temp
    dir, so arrival time and mtime diverge and mtime cannot be trusted.
    """
    assert tv_needs_processing("Some.Old.Release.2019/Show.S01E01.mkv") is True


# --- tier 2: inside an organized folder, but not clean's own output --------

def test_canonical_placed_file_is_done():
    assert tv_needs_processing(
        "Eastbound & Down (2009)/Season 02/Eastbound.&.Down.(2009).S02E05.Chapter.11.mkv"
    ) is False


def test_canonical_without_episode_title_is_still_done():
    """Title backfill is the full re-verification pass's job, not this filter's."""
    assert tv_needs_processing("Reacher (2022)/Season 04/Reacher.(2022).S04E01.mp4") is False


def test_alt_parked_file_is_done():
    """(alt) parking must not be re-flagged — that is the 004071c ping-pong."""
    assert tv_needs_processing(
        "Avenue 5 (2020)/Season 01/Avenue.5.(2020).S01E06.Was.It.Your.Ears (alt).mkv"
    ) is False


def test_four_digit_year_season_is_canonical():
    """Year-based seasons (c92c09c show-id renumber) are real clean output.

    A \\d{2}-only season pattern re-flags all 8 Hornblower episodes every run.
    """
    assert tv_needs_processing(
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
    assert tv_needs_processing(rel) is True


def test_new_episode_dropped_into_an_existing_season_folder():
    """The case _is_recent's docstring cares about — must not be missed."""
    assert tv_needs_processing("Reacher (2022)/Season 04/Reacher.S04E06.1080p.WEB-DL.mkv") is True


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
    assert tv_needs_processing(name) is False


def test_ds_store_inside_a_release_folder_is_not_work():
    assert tv_needs_processing("Spartacus/.DS_Store") is False


# --- predicate units -------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Reacher (2022)", True),
    ("C.S. Forester's Horatio Hornblower (1998)", True),
    ("Avenue 5 (2020) Season 2 S02 (1080p AMZN WEB-DL x265 HEVC 10bit DDP 5.1 Vyndros)", False),
    ("Spartacus", False),
    ("Show (12)", False),
    ("Show (3025)", False),
])
def test_is_organized_dir(name, expected):
    assert is_organized_dir(name) is expected


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
    assert tv_needs_processing("") is False


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


# --- movie layout ----------------------------------------------------------
#
# Every shape below was taken from /Volumes/Seagate/seagate-movie on
# 2026-09-17, for the same reason as the TV cases above: the filter's only job
# is to not misjudge shapes that actually occur.

@pytest.mark.parametrize("rel", [
    # The case that started this: moved in from temp with a 21h-old mtime on
    # 2026-09-15, skipped by the watcher's own 60m window, still loose 2 days on.
    "The.End.of.Oak.Street.2160p.HDR.ITA-ENG.MULTI.WEBRip.x265.AAC-V3SP4EV3R.mkv",
    "The Rick and Morty Playhouse Players Present- Portal People.mp4",
    # A release folder that clean has not consumed yet.
    "Some.Movie.2019.1080p.WEB-DL.x265/Some.Movie.mkv",
    # Organized-looking, but the folder carries no year, so clean did not make it.
    "Wallace and Gromit Film Collection/Wallace and Gromit Collection - Read This.rtf",
])
def test_movie_unplaced_files_need_processing(rel):
    assert movie_needs_processing(rel) is True


@pytest.mark.parametrize("rel", [
    "Ad Astra (2019)/Ad Astra (2019).mkv",
    "Alien: Romulus (2024)/Alien: Romulus (2024).mkv",   # colon survives
    "Black '47 (2018)/Black '47 (2018).mkv",             # apostrophe survives
    "Colossus: The Forbin Project (1970)/Colossus: The Forbin Project (1970).mp4",
])
def test_movie_placed_file_is_done(rel):
    assert movie_needs_processing(rel) is False


@pytest.mark.parametrize("rel", [
    "Psychokinesis (2018)/Psychokinesis (2018).eng.srt",
    "Psychokinesis (2018)/Psychokinesis (2018).fre.srt",
    "Psychokinesis (2018)/Psychokinesis (2018).ger.srt",
    "The Northman (2022)/The Northman (2022).eng.forced.srt",
    "Good Luck Have Fun Dont Die (2025)/Good Luck Have Fun Dont Die (2025).eng.sdh.hi.srt",
])
def test_movie_sidecars_are_done_not_work(rel):
    """The subtitle trap: 60 sidecars sit beside placed movies in the real
    library. Flagging them would mean re-processing them on every single run,
    forever — the same mistake the two-digit Hornblower season pattern made."""
    assert movie_needs_processing(rel) is False


@pytest.mark.parametrize("rel", [
    # Real misfilings the mtime window has been hiding: a movie parked in some
    # other movie's folder. Structural mode surfaces these; --recent never did.
    "Eater's Guide to the World (2020)/Dr Who Joy To The World.mkv",
    "Nanyobi ni umareta no (2023)/the curse of the were-rabbit.avi",
])
def test_movie_misfiled_into_another_folder_needs_processing(rel):
    assert movie_needs_processing(rel) is True


@pytest.mark.parametrize("name", [
    ".clean-movie-journal-20260917-121924.jsonl",
    ".rename-fix-reversal-20260728-190444.jsonl",
    ".DS_Store",
])
def test_movie_own_artifacts_are_never_work(name):
    """209 journals plus the 2026-07-28 reversal journal sit in the movie root.
    Without this the reversal journal alone is flagged as work on every run."""
    assert is_own_artifact(name) is True
    assert movie_needs_processing(name) is False


def test_movie_empty_path_is_not_work():
    assert movie_needs_processing("") is False


@pytest.mark.parametrize("folder,name,expected", [
    ("Ad Astra (2019)", "Ad Astra (2019).mkv", True),
    ("Ad Astra (2019)", "Ad Astra (2019).eng.srt", True),
    ("Ad Astra (2019)", "Ad Astra (2019) extras.mkv", False),   # space, not dot
    ("Ad Astra (2019)", "Ad Astra.mkv", False),
    ("Ad Astra (2019)", "something else.mkv", False),
])
def test_is_placed_movie_file(folder, name, expected):
    assert is_placed_movie_file(folder, name) is expected


def test_tv_filter_would_have_condemned_the_whole_movie_library():
    """Why movies needed their own tier-2 test rather than reusing TV's.

    This is the objection recorded in intake_filter's old scope note, kept as a
    live assertion: the TV predicate keys on an SxxExx stem, which no movie has,
    so pointing it at a movie library marks every correctly-placed film as
    unfinished work on every run.
    """
    placed = "Ad Astra (2019)/Ad Astra (2019).mkv"
    assert tv_needs_processing(placed) is True      # wrong, and why we forked
    assert movie_needs_processing(placed) is False  # right


# --- movie run() wiring ----------------------------------------------------

from src.service.clean_movie_service import CleanMovieService  # noqa: E402


class TestMovieStructuralRun:
    """CleanMovieService.run(structural=True) selects by shape, never by mtime."""

    def _library(self, tmp_path: Path) -> Path:
        """The real 2026-09-15 failure, reproduced with stale mtimes."""
        root = tmp_path / "movies"
        old = time.time() - 7200  # 2h ago: outside any --recent window

        def mk(rel: str, mtime: float) -> None:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("DATA")
            os.utime(p, (mtime, mtime))

        # Moved in from qBittorrent's temp dir wearing an old mtime.
        mk("The.End.of.Oak.Street.2160p.HDR.ITA-ENG.WEBRip.x265.mkv", old)
        # Already placed by clean — must be skipped.
        mk("Ad Astra (2019)/Ad Astra (2019).mkv", old)
        # Its sidecar — must also be skipped.
        mk("Ad Astra (2019)/Ad Astra (2019).eng.srt", old)
        # Misfiled into someone else's folder — must be processed.
        mk("Ad Astra (2019)/Dr Who Joy To The World.mkv", old)
        # clean's own journal — must never be work.
        mk(".clean-movie-journal-20260917-121924.jsonl", old)
        return root

    def _seen(self, root: Path, monkeypatch, **kwargs) -> set:
        service = CleanMovieService()
        seen: set = set()
        monkeypatch.setattr(service, "process_file",
                            lambda path, *a, **k: seen.add(path.name))
        monkeypatch.setattr(service, "_process_audio_tracks", lambda *a, **k: None)
        monkeypatch.setattr(service, "_report_large_files", lambda *a, **k: None,
                            raising=False)
        service.run(root=root, commit=False, **kwargs)
        return seen

    def test_structural_picks_up_the_stale_mtime_arrival(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch, structural=True)
        assert "The.End.of.Oak.Street.2160p.HDR.ITA-ENG.WEBRip.x265.mkv" in seen
        assert "Dr Who Joy To The World.mkv" in seen
        assert "Ad Astra (2019).mkv" not in seen
        assert "Ad Astra (2019).eng.srt" not in seen
        assert ".clean-movie-journal-20260917-121924.jsonl" not in seen

    def test_incremental_misses_it_which_is_the_bug(self, tmp_path, monkeypatch):
        """The regression guard. This is exactly what the watcher logged on
        2026-09-15: 'processed 0 recent file(s), skipped 375 outside window'."""
        seen = self._seen(self._library(tmp_path), monkeypatch, since_seconds=3600)
        assert seen == set()

    def test_structural_overrides_the_window(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch,
                          since_seconds=3600, structural=True)
        assert "The.End.of.Oak.Street.2160p.HDR.ITA-ENG.WEBRip.x265.mkv" in seen

    def test_full_run_still_processes_everything(self, tmp_path, monkeypatch):
        seen = self._seen(self._library(tmp_path), monkeypatch)
        assert "Ad Astra (2019).mkv" in seen


def test_service_without_a_structural_filter_refuses_loudly():
    """Base must not guess a layout. A service that has not declared one and is
    asked for structural mode fails with a message, rather than silently
    inheriting TV's rules and condemning or skipping the wrong files."""
    from src.service.base import BaseCleanService

    # Called unbound: BaseCleanService has eight abstract methods, and none of
    # them is relevant to whether it can answer the structural question.
    with pytest.raises(NotImplementedError, match="no structural intake filter"):
        BaseCleanService._needs_processing(object(), Path("x.mkv"))


@pytest.mark.parametrize("rel", [
    # Organized TV in the shared intake dir: the "Show (Year)" parent passes
    # tier 1 and the TV-shaped filename fails tier 2, so without the season
    # test every one of these is movie work. 6,518 of them on 2026-09-17.
    "Reacher (2022)/Season 04/Reacher.(2022).S04E01.mp4",
    "Avenue 5 (2020)/Season 01/Avenue.5.(2020).S01E01.I.Was.Flying.mkv",
    "C.S. Forester's Horatio Hornblower (1998)/Season 1998/Hornblower.(1998).S1998E01.mp4",
    # Case and spacing variants of the folder name.
    "Reacher (2022)/season 4/whatever.mkv",
    "Reacher (2022)/SEASON  12/whatever.mkv",
])
def test_movie_filter_ignores_tv_territory(rel):
    """watch-tv.sh runs the MOVIE pass over the TV library to route films out to
    seagate-movie. Anything under a Season folder is the TV service's business."""
    assert movie_needs_processing(rel) is False
    # ...and the TV filter still owns them.
    assert tv_needs_processing(rel) in (True, False)  # just: no exception


@pytest.mark.parametrize("name,expected", [
    ("Season 01", True),
    ("Season 1", True),
    ("season 4", True),
    ("SEASON  12", True),
    ("Season 1998", True),
    ("Seasons", False),
    ("Season", False),
    ("S01", False),
    ("Ad Astra (2019)", False),
])
def test_is_season_dir(name, expected):
    assert is_season_dir(name) is expected
