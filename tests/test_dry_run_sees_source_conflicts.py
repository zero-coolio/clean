"""A preview must report the same deletions the commit run performs (CLEAN-22).

The bug, measured on /Volumes/Summer/movie-archive on 2026-10-13:

    dry run   : 214 moves,   2 CONFLICT
    --commit  : 207 moves,  48 CONFLICT

Nothing is placed during a dry run, so two SOURCE files resolving to one
destination never met and no conflict was reported. A preview that
under-reports deletions is worse than no preview, because it is trusted: that
sweep was approved on "2 conflicts".

The real names here are from the archive. Red Dwarf is also the CLEAN-23 case,
so it is used to assert the part refusal fires in both modes too.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.config import get_logger
from src.service.clean_movie_service import CleanMovieService


class _Collector(logging.Handler):
    """Capture the service's own logger.

    caplog hooks the root logger, and get_logger sets propagate=False, so a
    caplog-based assertion here silently passes on zero records no matter what
    the service does. That is exactly the kind of test that looks green while
    proving nothing, so the handler is attached directly.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def count(self, needle: str) -> int:
        return sum(1 for m in self.messages if needle in m)


@pytest.fixture
def logs():
    # Force config.get_logger to configure "clean-movie" BEFORE attaching.
    # Its first-time branch calls logger.handlers.clear(), so a handler added
    # earlier is silently removed by the service constructor. That made this
    # suite order-dependent: it passed whenever another test had already
    # configured the logger, and captured nothing when it ran first.
    get_logger("clean-movie")

    handler = _Collector()
    logger = logging.getLogger("clean-movie")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous)


def _two_rips_of_one_film(root: Path) -> None:
    """Two different files that both resolve to 'Pitch Black (2000)'."""
    (root / "Pitch.Black.2000.480p.WEBRip.x264.mkv").write_bytes(b"x" * 1000)
    (root / "Pitch.Black.2000.1080p.BluRay.x264.mkv").write_bytes(b"y" * 5000)


class TestPreviewMatchesCommit:
    def test_a_dry_run_reports_the_source_vs_source_conflict(self, tmp_path, logs):
        _two_rips_of_one_film(tmp_path)
        CleanMovieService().run(tmp_path, commit=False)
        assert logs.count("CONFLICT:") == 1

    def test_dry_run_and_commit_report_the_same_count(self, tmp_path, logs):
        """The acceptance test for CLEAN-22, stated directly."""
        dry = tmp_path / "dry"
        wet = tmp_path / "wet"
        dry.mkdir()
        wet.mkdir()
        _two_rips_of_one_film(dry)
        _two_rips_of_one_film(wet)

        CleanMovieService().run(dry, commit=False)
        dry_conflicts = logs.count("CONFLICT:")
        logs.messages.clear()
        CleanMovieService().run(wet, commit=True)
        wet_conflicts = logs.count("CONFLICT:")

        assert dry_conflicts == wet_conflicts == 1

    def test_a_dry_run_still_moves_nothing(self, tmp_path):
        """Modelling placement must not start performing it."""
        _two_rips_of_one_film(tmp_path)
        CleanMovieService().run(tmp_path, commit=False)
        assert (tmp_path / "Pitch.Black.2000.480p.WEBRip.x264.mkv").exists()
        assert not (tmp_path / "Pitch Black (2000)").exists()

    def test_one_file_alone_is_not_a_conflict(self, tmp_path, logs):
        (tmp_path / "Pitch.Black.2000.1080p.BluRay.x264.mkv").write_bytes(b"y" * 5000)
        CleanMovieService().run(tmp_path, commit=False)
        assert logs.count("CONFLICT:") == 0


class TestPartCollisionIsRefusedInBothModes:
    """CLEAN-23: two halves of one work must never be resolved as duplicates."""

    @pytest.mark.parametrize("commit", [False, True])
    def test_red_dwarf_parts_are_both_kept(self, tmp_path, logs, commit):
        a = tmp_path / "red.dwarf.the.promised.land.2020.part.1.web.h264-brexit.mkv"
        b = tmp_path / "red.dwarf.the.promised.land.2020.part.2.web.h264-brexit.mkv"
        a.write_bytes(b"a" * 4000)
        b.write_bytes(b"b" * 3000)

        CleanMovieService().run(tmp_path, commit=commit)

        assert logs.count("REFUSE PART COLLISION") >= 1
        assert logs.count("CONFLICT:") == 0
        # Whichever part moved first, the other is still on disk, not trashed.
        survivors = list(tmp_path.rglob("*.mkv"))
        assert len(survivors) == 2, [str(s) for s in survivors]
