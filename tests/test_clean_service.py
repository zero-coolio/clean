#!/usr/bin/env python3
"""Tests for CleanService (TV)."""
import os
import time
import pytest
from pathlib import Path

from src.service.clean_service import CleanService, parse_episode_from_string
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
