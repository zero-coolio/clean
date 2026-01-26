#!/usr/bin/env python3
"""Tests for CleanService (TV)."""
import pytest
from pathlib import Path

from src.service.clean_service import CleanService, parse_episode_from_string
from src.utils import is_english_subtitle


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
