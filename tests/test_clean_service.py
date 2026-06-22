#!/usr/bin/env python3
"""Tests for CleanService (TV)."""
import os
import time
import pytest
from pathlib import Path

from src.service.clean_service import (
    CleanService,
    parse_episode_from_string,
    episode_title_suffix,
)
from src.utils import is_english_subtitle, touch_folder, safe_move


class TestParseEpisodeFromString:
    """Tests for episode parsing."""

    def test_sxxeyy_format(self) -> None:
        """Standard SxxExx format."""
        result = parse_episode_from_string("Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee")
        assert result == ("Letterkenny", "05", "01")

    def test_x_pattern(self) -> None:
        """Alternative 1x01 format."""
        result = parse_episode_from_string("Letterkenny - 5x2 - Super Soft Birthday")
        assert result == ("Letterkenny", "05", "02")

    def test_with_noise_prefix(self) -> None:
        """Handles torrent site prefixes."""
        result = parse_episode_from_string("[rartv]Letterkenny.S05E01.1080p.mkv")
        assert result == ("Letterkenny", "05", "01")

    def test_lowercase_season_episode(self) -> None:
        """Case-insensitive parsing."""
        result = parse_episode_from_string("show.name.s01e01.720p.mkv")
        assert result == ("Show Name", "01", "01")

    def test_no_match_returns_none(self) -> None:
        """Returns None for unparseable strings."""
        result = parse_episode_from_string("random_file.mkv")
        assert result is None

    def test_season_episode_spelled_out(self) -> None:
        """Handles 'Season X Episode Y' format."""
        result = parse_episode_from_string("The Artful Dodger (2023) Season 2 Episode 5- TBA - PrimeWir")
        assert result == ("The Artful Dodger", "02", "05")

    def test_season_episode_with_dots(self) -> None:
        """Handles dotted 'Season.X.Episode.Y' format."""
        result = parse_episode_from_string("Some.Show.Season.3.Episode.7.720p.mkv")
        assert result == ("Some Show", "03", "07")

    def test_compact_code_three_digit(self) -> None:
        """Handles scene compact code: 3-digit token = season + 2-digit episode."""
        result = parse_episode_from_string("hawaii.five-0.2010.713.hdtv-lol")
        assert result == ("Hawaii Five 0 (2010)", "07", "13")

    def test_compact_code_four_digit(self) -> None:
        """Handles scene compact code: 4-digit token = 2-digit season + episode."""
        result = parse_episode_from_string("South.Park.1314.HDTV.x264-GROUP")
        assert result == ("South Park", "13", "14")

    def test_compact_code_does_not_match_year_or_resolution(self) -> None:
        """A year + resolution (no episode code) must not be parsed as an episode."""
        assert parse_episode_from_string("The.Dark.Knight.2008.1080p.BluRay.x264-GROUP") is None

    def test_explicit_sxxeyy_wins_over_compact(self) -> None:
        """Explicit SxxExx is preferred even when a year is present."""
        result = parse_episode_from_string("Hawaii.Five-0.2010.S07E13.HDTV.x264-LOL")
        assert result == ("Hawaii Five 0 (2010)", "07", "13")

    def test_bare_episode_number_seasonless(self) -> None:
        """Seasonless miniseries with a leading-zero episode number -> S01Exx."""
        result = parse_episode_from_string("Horatio Hornblower 03 The Duchess And The Devil 480P H")
        assert result == ("Horatio Hornblower", "01", "03")

    def test_bare_episode_requires_leading_zero(self) -> None:
        """A non-zero-padded number in a title must NOT be read as an episode."""
        assert parse_episode_from_string("Studio 60 on the Sunset Strip 1080p") is None
        assert parse_episode_from_string("Apollo 13 1995 1080p") is None


class TestBuildDest:
    """Tests for destination path building."""

    def test_build_dest(self, tmp_path: Path) -> None:
        """Video files placed in correct structure."""
        dest = CleanService.build_dest(tmp_path, "Letterkenny", "05", "01", ".mkv")
        expected = tmp_path / "Letterkenny" / "Season 05" / "Letterkenny.S05E01.mkv"
        assert dest == expected

    def test_build_sidecar_target(self, tmp_path: Path) -> None:
        """Sidecar files use same naming pattern."""
        sidecar = CleanService.build_sidecar_target(tmp_path, "Letterkenny", "05", "01", "subtitle.srt")
        expected = tmp_path / "Letterkenny" / "Season 05" / "Letterkenny.S05E01.srt"
        assert sidecar == expected

    def test_empty_show_name(self, tmp_path: Path) -> None:
        """Handles empty show name gracefully."""
        dest = CleanService.build_dest(tmp_path, "", "01", "01", ".mkv")
        assert "Unknown Show" in str(dest)


class TestCleanServiceIntegration:
    """Integration tests for the TV cleaning process."""

    def test_moves_media_to_expected_dest(self, tmp_path: Path) -> None:
        """Media files are moved to clean structure."""
        root = tmp_path / "intake"
        root.mkdir()

        # Wrapper-style folder
        wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
        wrapper.mkdir()

        src_file = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
        src_file.write_text("FAKE_DATA", encoding="utf-8")

        service = CleanService()
        service.run(root=root, commit=True, plan=False, quarantine=None)

        expected_dest = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")

        assert not src_file.exists()
        assert expected_dest.exists()
        assert expected_dest.read_text(encoding="utf-8") == "FAKE_DATA"

    def test_dry_run_does_not_modify_files(self, tmp_path: Path) -> None:
        """Commit=False doesn't change anything."""
        root = tmp_path / "intake"
        root.mkdir()

        wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
        wrapper.mkdir()

        src_file = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
        src_file.write_text("FAKE_DATA", encoding="utf-8")

        service = CleanService()
        service.run(root=root, commit=False, plan=True, quarantine=None)

        expected_dest = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")

        assert src_file.exists()
        assert not expected_dest.exists()

    def test_non_english_subtitles_in_wrapper_are_deleted(self, tmp_path: Path) -> None:
        """Non-English subtitles in release folders are deleted."""
        root = tmp_path / "intake"
        root.mkdir()

        wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
        wrapper.mkdir()

        video = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
        video.write_text("VIDEO", encoding="utf-8")

        eng_sub = wrapper / "Letterkenny.S05E01.en.srt"
        eng_sub.write_text("ENGLISH SUB", encoding="utf-8")

        fr_sub = wrapper / "Letterkenny.S05E01.fr.srt"
        fr_sub.write_text("FRENCH SUB", encoding="utf-8")

        rar_file = wrapper / "SomeArchive.rar"
        rar_file.write_text("RAR DATA", encoding="utf-8")

        service = CleanService()
        service.run(root=root, commit=True, plan=False, quarantine=None)

        # Video moved
        dest_video = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")
        assert dest_video.exists()
        assert dest_video.read_text(encoding="utf-8") == "VIDEO"

        # English subtitle moved
        dest_eng = CleanService.build_sidecar_target(root, "Letterkenny", "05", "01", eng_sub.name)
        assert dest_eng.exists()
        assert dest_eng.read_text(encoding="utf-8") == "ENGLISH SUB"

        # French subtitle deleted
        assert not fr_sub.exists()

        # Only one .srt in destination
        season_dir = root / "Letterkenny" / "Season 05"
        srt_files = sorted(p.name for p in season_dir.glob("*.srt"))
        assert srt_files == ["Letterkenny.S05E01.srt"]

        # RAR deleted
        assert not rar_file.exists()

    def test_deletes_samples(self, tmp_path: Path) -> None:
        """Sample files are deleted."""
        root = tmp_path / "intake"
        root.mkdir()

        wrapper = root / "Show.S01E01.720p.WEB"
        wrapper.mkdir()

        sample = wrapper / "sample-show.s01e01.mkv"
        sample.write_text("SAMPLE", encoding="utf-8")

        video = wrapper / "Show.S01E01.mkv"
        video.write_text("VIDEO", encoding="utf-8")

        service = CleanService()
        service.run(root=root, commit=True)

        assert not sample.exists()

    def test_quarantine_moves_samples(self, tmp_path: Path) -> None:
        """Samples moved to quarantine instead of deleted."""
        root = tmp_path / "intake"
        root.mkdir()
        quarantine = tmp_path / "quarantine"

        wrapper = root / "Show.S01E01.720p.WEB"
        wrapper.mkdir()

        sample = wrapper / "sample-show.mkv"
        sample.write_text("SAMPLE", encoding="utf-8")
        
        # Add a real episode file so the root doesn't get deleted
        video = wrapper / "Show.S01E01.720p.WEB.mkv"
        video.write_text("VIDEO", encoding="utf-8")

        service = CleanService()
        service.run(root=root, commit=True, quarantine=quarantine)

        assert not sample.exists()
        assert (quarantine / "sample-show.mkv").exists()
        # Video should be moved to clean structure
        assert (root / "Show" / "Season 01" / "Show.S01E01.mkv").exists()


class TestCollisionResolution:
    """When two different episode files map to the same destination, keep newer."""

    @staticmethod
    def _no_tvmaze(monkeypatch) -> None:
        """Stop the canonical-show and episode-title lookups from hitting the network."""
        monkeypatch.setattr("src.tvmaze.lookup_show", lambda name, logger=None: None)
        monkeypatch.setattr(
            "src.tvmaze.lookup_episode_name",
            lambda name, season, episode, logger=None: None,
        )

    def test_newer_source_replaces_older_dest(self, tmp_path: Path, monkeypatch) -> None:
        """A colliding source that is newer than the dest wins."""
        self._no_tvmaze(monkeypatch)
        root = tmp_path / "intake"
        root.mkdir()

        # Pre-existing (older) destination
        dest = CleanService.build_dest(root, "Show", "01", "01", ".mkv")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("OLD", encoding="utf-8")
        old_time = time.time() - 10_000
        os.utime(dest, (old_time, old_time))

        # Newer source with different content (different size -> not a dup)
        wrapper = root / "Show.S01.1080p.WEB-GROUP"
        wrapper.mkdir()
        src = wrapper / "Show.S01E01.1080p.WEB-GROUP.mkv"
        src.write_text("NEWER-CONTENT", encoding="utf-8")  # newer by default mtime

        CleanService().run(root=root, commit=True, quarantine=None)

        assert not src.exists()
        assert dest.read_text(encoding="utf-8") == "NEWER-CONTENT"

    def test_older_source_keeps_newer_dest(self, tmp_path: Path, monkeypatch) -> None:
        """A colliding source that is older than the dest is discarded."""
        self._no_tvmaze(monkeypatch)
        root = tmp_path / "intake"
        root.mkdir()

        # Pre-existing (newer) destination
        dest = CleanService.build_dest(root, "Show", "01", "01", ".mkv")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("NEWER-DEST", encoding="utf-8")

        # Older source with different content
        wrapper = root / "Show.S01.1080p.WEB-GROUP"
        wrapper.mkdir()
        src = wrapper / "Show.S01E01.1080p.WEB-GROUP.mkv"
        src.write_text("OLD", encoding="utf-8")
        old_time = time.time() - 10_000
        os.utime(src, (old_time, old_time))

        CleanService().run(root=root, commit=True, quarantine=None)

        assert not src.exists()
        assert dest.read_text(encoding="utf-8") == "NEWER-DEST"


class TestEpisodeTitleSuffix:
    """Tests for formatting an episode title into a filename segment."""

    def test_basic(self) -> None:
        assert episode_title_suffix("We Don't Fight at Weddings") == "We.Don't.Fight.at.Weddings"

    def test_strips_illegal_chars(self) -> None:
        assert episode_title_suffix("Part 1: The End?") == "Part.1.The.End"

    def test_empty(self) -> None:
        assert episode_title_suffix("") == ""


class TestEpisodeTitleInDest:
    """The episode title (when available) is appended after SxxExx."""

    def test_build_dest_appends_title(self, tmp_path: Path) -> None:
        dest = CleanService.build_dest(
            tmp_path, "Letterkenny (2016)", "05", "01", ".mkv", "We Don't Fight at Weddings"
        )
        expected = (
            tmp_path / "Letterkenny (2016)" / "Season 05"
            / "Letterkenny.(2016).S05E01.We.Don't.Fight.at.Weddings.mkv"
        )
        assert dest == expected

    def test_build_dest_without_title_unchanged(self, tmp_path: Path) -> None:
        dest = CleanService.build_dest(tmp_path, "Letterkenny", "05", "01", ".mkv")
        assert dest == tmp_path / "Letterkenny" / "Season 05" / "Letterkenny.S05E01.mkv"

    def test_title_flows_into_rename(self, tmp_path: Path, monkeypatch) -> None:
        """End-to-end: a resolved title lands in the renamed file."""
        monkeypatch.setattr("src.tvmaze.lookup_show", lambda name, logger=None: None)
        monkeypatch.setattr(
            "src.tvmaze.lookup_episode_name",
            lambda name, season, episode, logger=None: "The Pilot",
        )
        root = tmp_path / "intake"
        root.mkdir()
        wrapper = root / "Show.S01.1080p.WEB-GROUP"
        wrapper.mkdir()
        src = wrapper / "Show.S01E01.1080p.WEB-GROUP.mkv"
        src.write_text("DATA", encoding="utf-8")

        CleanService().run(root=root, commit=True, quarantine=None)

        expected = root / "Show" / "Season 01" / "Show.S01E01.The.Pilot.mkv"
        assert expected.exists()
        assert not src.exists()


class TestIsEnglishSubtitle:
    """Tests for English subtitle detection."""

    def test_eng_suffix(self) -> None:
        assert is_english_subtitle("movie.eng.srt") is True

    def test_en_suffix(self) -> None:
        assert is_english_subtitle("movie.en.srt") is True

    def test_spanish_suffix(self) -> None:
        assert is_english_subtitle("movie.spa.srt") is False

    def test_no_language_tag(self) -> None:
        assert is_english_subtitle("movie.srt") is False

    def test_non_subtitle_file(self) -> None:
        assert is_english_subtitle("movie.eng.txt") is False


class TestTouchFolder:
    """Tests for folder timestamp updates."""

    def test_touch_folder_updates_mtime(self, tmp_path: Path) -> None:
        """touch_folder updates the folder's modification time."""
        folder = tmp_path / "test_folder"
        folder.mkdir()

        # Set an old timestamp
        old_time = time.time() - 3600  # 1 hour ago
        os.utime(folder, (old_time, old_time))

        original_mtime = folder.stat().st_mtime
        time.sleep(0.01)  # Ensure time passes

        touch_folder(folder)

        new_mtime = folder.stat().st_mtime
        assert new_mtime > original_mtime

    def test_touch_folder_nonexistent_does_nothing(self, tmp_path: Path) -> None:
        """touch_folder on nonexistent path doesn't raise."""
        nonexistent = tmp_path / "does_not_exist"
        # Should not raise
        touch_folder(nonexistent)

    def test_touch_folder_on_file_does_nothing(self, tmp_path: Path) -> None:
        """touch_folder on a file (not directory) doesn't update it."""
        file_path = tmp_path / "test_file.txt"
        file_path.write_text("test")

        old_time = time.time() - 3600
        os.utime(file_path, (old_time, old_time))
        original_mtime = file_path.stat().st_mtime

        touch_folder(file_path)

        # File mtime should be unchanged since touch_folder only works on dirs
        assert file_path.stat().st_mtime == original_mtime


class TestSafeMoveTimestampUpdate:
    """Tests for safe_move updating parent folder timestamps."""

    def test_safe_move_updates_show_folder_timestamp(self, tmp_path: Path) -> None:
        """Moving a file updates the show folder (2 levels up) timestamp."""
        root = tmp_path / "media"
        root.mkdir()

        # Create source file
        src = tmp_path / "source.mkv"
        src.write_text("VIDEO DATA")

        # Create destination structure
        show_folder = root / "Show Name"
        season_folder = show_folder / "Season 01"
        season_folder.mkdir(parents=True)

        # Set old timestamps on the show folder
        old_time = time.time() - 3600
        os.utime(show_folder, (old_time, old_time))
        original_mtime = show_folder.stat().st_mtime

        time.sleep(0.01)

        # Move file
        dst = season_folder / "Show.Name.S01E01.mkv"
        journal: list[dict] = []
        safe_move(src, dst, commit=True, journal=journal)

        # Show folder timestamp should be updated
        new_mtime = show_folder.stat().st_mtime
        assert new_mtime > original_mtime

    def test_safe_move_respects_touch_parent_depth(self, tmp_path: Path) -> None:
        """touch_parent_depth controls which folder gets touched."""
        root = tmp_path / "media"
        root.mkdir()

        # Create source file
        src = tmp_path / "source.mkv"
        src.write_text("VIDEO DATA")

        # Create destination structure
        show_folder = root / "Show Name"
        season_folder = show_folder / "Season 01"
        season_folder.mkdir(parents=True)

        # Set old timestamps
        old_time = time.time() - 3600
        os.utime(show_folder, (old_time, old_time))
        os.utime(season_folder, (old_time, old_time))

        show_original_mtime = show_folder.stat().st_mtime
        season_original_mtime = season_folder.stat().st_mtime

        time.sleep(0.01)

        # Move file with depth=1 (touch season folder, not show)
        dst = season_folder / "Show.Name.S01E01.mkv"
        journal: list[dict] = []
        safe_move(src, dst, commit=True, journal=journal, touch_parent_depth=1)

        # Season folder should be updated (depth=1)
        assert season_folder.stat().st_mtime > season_original_mtime
        # Show folder should NOT be updated
        assert show_folder.stat().st_mtime == show_original_mtime

    def test_safe_move_no_touch_when_depth_zero(self, tmp_path: Path) -> None:
        """touch_parent_depth=0 disables explicit folder timestamp updates.

        Note: The filesystem itself will still update the parent directory's
        mtime when a file is added, so we test by checking that we DON'T
        additionally touch a grandparent folder.
        """
        root = tmp_path / "media"
        root.mkdir()
        subdir = root / "subdir"
        subdir.mkdir()

        src = tmp_path / "source.mkv"
        src.write_text("VIDEO DATA")

        dst = subdir / "dest.mkv"

        # Set old timestamps on root (grandparent of file)
        old_time = time.time() - 3600
        os.utime(root, (old_time, old_time))
        original_root_mtime = root.stat().st_mtime

        time.sleep(0.01)

        journal: list[dict] = []
        # With depth=0, we shouldn't touch any parent folders explicitly
        safe_move(src, dst, commit=True, journal=journal, touch_parent_depth=0)

        # Root folder (grandparent) should NOT be touched
        # (filesystem updates immediate parent, but our code shouldn't touch grandparent)
        assert root.stat().st_mtime == original_root_mtime

    def test_safe_move_dry_run_no_touch(self, tmp_path: Path) -> None:
        """Dry run (commit=False) doesn't touch folders."""
        root = tmp_path / "media"
        root.mkdir()

        src = tmp_path / "source.mkv"
        src.write_text("VIDEO DATA")

        dst = root / "dest.mkv"

        old_time = time.time() - 3600
        os.utime(root, (old_time, old_time))
        original_mtime = root.stat().st_mtime

        time.sleep(0.01)

        journal: list[dict] = []
        safe_move(src, dst, commit=False, journal=journal)

        # Folder timestamp should NOT be updated (dry run)
        assert root.stat().st_mtime == original_mtime
        # File should still exist at source
        assert src.exists()


class TestCleanServiceTimestampIntegration:
    """Integration tests for timestamp updates during TV cleaning."""

    def test_cleaning_updates_show_folder_timestamp(self, tmp_path: Path) -> None:
        """Running CleanService updates the show folder's timestamp."""
        root = tmp_path / "intake"
        root.mkdir()

        # Create wrapper folder with episode
        wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip[rartv]"
        wrapper.mkdir()

        src_file = wrapper / "Letterkenny.S05E01.mkv"
        src_file.write_text("FAKE_DATA")

        # Run service to create the show folder structure
        service = CleanService()
        service.run(root=root, commit=True)

        # Show folder should exist
        show_folder = root / "Letterkenny"
        assert show_folder.exists()

        # Add another episode
        wrapper2 = root / "Letterkenny.S05E02.720p.WEB"
        wrapper2.mkdir()
        src_file2 = wrapper2 / "Letterkenny.S05E02.mkv"
        src_file2.write_text("FAKE_DATA_2")

        # Set show folder timestamp to past
        old_time = time.time() - 3600
        os.utime(show_folder, (old_time, old_time))

        time.sleep(0.01)

        # Run service again
        service.run(root=root, commit=True)

        # Show folder timestamp should be updated
        new_mtime = show_folder.stat().st_mtime
        assert new_mtime > old_time


class TestParseDuration:
    """Tests for the human-duration parser used by --since / --recent."""

    def test_seconds_bare_number(self) -> None:
        from src.config import parse_duration
        assert parse_duration("3600") == 3600

    def test_minutes(self) -> None:
        from src.config import parse_duration
        assert parse_duration("30m") == 1800

    def test_hours(self) -> None:
        from src.config import parse_duration
        assert parse_duration("1h") == 3600

    def test_days(self) -> None:
        from src.config import parse_duration
        assert parse_duration("2d") == 2 * 24 * 3600

    def test_explicit_seconds_suffix(self) -> None:
        from src.config import parse_duration
        assert parse_duration("90s") == 90

    def test_decimal_value(self) -> None:
        from src.config import parse_duration
        assert parse_duration("1.5h") == 5400

    def test_whitespace_and_case(self) -> None:
        from src.config import parse_duration
        assert parse_duration(" 2H ") == 7200

    def test_default_window_is_an_hour(self) -> None:
        from src.config import DEFAULT_RECENT_WINDOW, parse_duration
        assert parse_duration(DEFAULT_RECENT_WINDOW) == 3600

    @pytest.mark.parametrize("bad", ["", "abc", "10x", "h", "-5m", None])
    def test_invalid_raises(self, bad) -> None:
        from src.config import parse_duration
        with pytest.raises(ValueError):
            parse_duration(bad)


class TestIsRecent:
    """Tests for the file-mtime cutoff predicate."""

    def test_no_cutoff_accepts_everything(self, tmp_path: Path) -> None:
        f = tmp_path / "anything.mkv"
        f.write_text("x")
        os.utime(f, (0, 0))  # ancient
        assert CleanService._is_recent(f, None) is True

    def test_recent_file_within_window(self, tmp_path: Path) -> None:
        f = tmp_path / "new.mkv"
        f.write_text("x")
        now = time.time()
        os.utime(f, (now, now))
        cutoff = now - 3600
        assert CleanService._is_recent(f, cutoff) is True

    def test_old_file_outside_window(self, tmp_path: Path) -> None:
        f = tmp_path / "old.mkv"
        f.write_text("x")
        now = time.time()
        os.utime(f, (now - 7200, now - 7200))  # 2h old
        cutoff = now - 3600
        assert CleanService._is_recent(f, cutoff) is False

    def test_missing_file_fails_open(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.mkv"  # never created
        cutoff = time.time() - 3600
        assert CleanService._is_recent(f, cutoff) is True


class TestIncrementalRun:
    """run(since_seconds=...) processes only recent files, keyed on FILE mtime."""

    def _build_library(self, tmp_path: Path) -> Path:
        """Create a library mixing old/new files in old/new folders.

        Layout (mtimes relative to now):
          OldShow (2010)/Season 01/OldShow.S01E01.mp4         old file, old folder
          OldShow (2010)/Season 01/OldShow.S01E02.mp4         NEW file, OLD folder  <- must process
          New.Release.1080p.x264-GRP/New.S02E03.mp4           NEW file, NEW folder  <- must process
          Stale.Release.1080p.x264-GRP/Stale.S04E05.mp4       old file, new-ish folder
        """
        root = tmp_path / "lib"
        now = time.time()
        old = now - 7200   # 2h ago
        new = now - 60     # 1m ago

        def mk(rel: str, mtime: float) -> None:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("DATA")
            os.utime(p, (mtime, mtime))

        mk("OldShow (2010)/Season 01/OldShow.S01E01.mp4", old)
        mk("OldShow (2010)/Season 01/OldShow.S01E02.mp4", new)
        mk("New.Release.1080p.x264-GRP/New.Show.S02E03.mp4", new)
        mk("Stale.Release.1080p.x264-GRP/Stale.Show.S04E05.mp4", old)
        return root

    def _run_and_collect(self, root: Path, since_seconds, monkeypatch) -> set[str]:
        """Run with process_file/audio stubbed; return names process_file saw."""
        service = CleanService()
        seen: set[str] = set()

        def fake_process_file(path, *args, **kwargs):
            seen.add(path.name)

        monkeypatch.setattr(service, "process_file", fake_process_file)
        # Avoid mkvtoolnix + filesystem churn unrelated to the filter under test.
        monkeypatch.setattr(service, "_process_audio_tracks", lambda *a, **k: None)
        monkeypatch.setattr(service, "_report_large_files", lambda *a, **k: None)

        service.run(root=root, commit=False, since_seconds=since_seconds)
        return seen

    def test_incremental_skips_old_keeps_new(self, tmp_path: Path, monkeypatch) -> None:
        root = self._build_library(tmp_path)
        seen = self._run_and_collect(root, 3600, monkeypatch)

        # New file in an OLD folder must be processed (filter is per-file).
        assert "OldShow.S01E02.mp4" in seen
        # New file in a new release folder must be processed.
        assert "New.Show.S02E03.mp4" in seen
        # Old files must be skipped regardless of their folder's age.
        assert "OldShow.S01E01.mp4" not in seen
        assert "Stale.Show.S04E05.mp4" not in seen

    def test_full_run_processes_everything(self, tmp_path: Path, monkeypatch) -> None:
        root = self._build_library(tmp_path)
        seen = self._run_and_collect(root, None, monkeypatch)

        assert seen == {
            "OldShow.S01E01.mp4",
            "OldShow.S01E02.mp4",
            "New.Show.S02E03.mp4",
            "Stale.Show.S04E05.mp4",
        }
