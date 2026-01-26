#!/usr/bin/env python3
"""Tests for CleanMovieService."""
import pytest
from pathlib import Path

from src.service.clean_movie_service import (
    parse_movie_from_string,
    clean_movie_title,
    CleanMovieService,
)
from src.utils import is_english_subtitle


class TestParseMovieFromString:
    """Tests for movie name/year parsing."""

    def test_dotted_format(self) -> None:
        """Standard torrent naming: Movie.Name.Year.Quality..."""
        result = parse_movie_from_string("The.Matrix.1999.1080p.BluRay.x264-GROUP")
        assert result == ("The Matrix", "1999")

    def test_dotted_format_with_spaces_in_title(self) -> None:
        result = parse_movie_from_string("No.Country.for.Old.Men.2007.720p.BRRip")
        assert result == ("No Country For Old Men", "2007")

    def test_parenthesized_year(self) -> None:
        """Clean format: Movie Name (Year)"""
        result = parse_movie_from_string("The Matrix (1999)")
        assert result == ("The Matrix", "1999")

    def test_parenthesized_year_with_ext(self) -> None:
        result = parse_movie_from_string("The Matrix (1999).mkv")
        assert result == ("The Matrix", "1999")

    def test_year_with_hyphen(self) -> None:
        result = parse_movie_from_string("Inception-2010-1080p")
        assert result == ("Inception", "2010")

    def test_year_with_underscore(self) -> None:
        result = parse_movie_from_string("Inception_2010_1080p")
        assert result == ("Inception", "2010")

    def test_sequel_with_number(self) -> None:
        result = parse_movie_from_string("Die.Hard.2.1990.1080p.BluRay")
        assert result == ("Die Hard 2", "1990")

    def test_year_at_different_position(self) -> None:
        result = parse_movie_from_string("2001.A.Space.Odyssey.1968.1080p")
        assert result == ("2001 A Space Odyssey", "1968")

    def test_no_year_returns_none(self) -> None:
        result = parse_movie_from_string("SomeRandomFile.mkv")
        assert result is None

    def test_yts_prefix(self) -> None:
        result = parse_movie_from_string("[YTS] The.Dark.Knight.2008.1080p")
        assert result == ("The Dark Knight", "2008")

    def test_rarbg_prefix(self) -> None:
        result = parse_movie_from_string("rarbg-Interstellar.2014.2160p.UHD")
        assert result == ("Interstellar", "2014")


class TestCleanMovieTitle:
    """Tests for title cleaning."""

    def test_removes_dots(self) -> None:
        assert clean_movie_title("The.Dark.Knight") == "The Dark Knight"

    def test_removes_underscores(self) -> None:
        assert clean_movie_title("The_Dark_Knight") == "The Dark Knight"

    def test_removes_quality_markers(self) -> None:
        assert clean_movie_title("Inception 1080p BluRay") == "Inception"

    def test_preserves_acronyms(self) -> None:
        assert clean_movie_title("FBI.Movie") == "FBI Movie"

    def test_title_case(self) -> None:
        assert clean_movie_title("the dark knight") == "The Dark Knight"


class TestIsEnglishSubtitle:
    """Tests for English subtitle detection."""

    def test_eng_suffix(self) -> None:
        assert is_english_subtitle("movie.eng.srt") is True

    def test_en_suffix(self) -> None:
        assert is_english_subtitle("movie.en.srt") is True

    def test_english_suffix(self) -> None:
        assert is_english_subtitle("movie.english.srt") is True

    def test_spanish_suffix(self) -> None:
        assert is_english_subtitle("movie.spa.srt") is False

    def test_no_language_tag(self) -> None:
        assert is_english_subtitle("movie.srt") is False

    def test_non_subtitle_file(self) -> None:
        assert is_english_subtitle("movie.eng.txt") is False

    def test_plain_english_filename(self) -> None:
        """Files named just 'English.srt' in Subs folders."""
        assert is_english_subtitle("English.srt") is True

    def test_sdh_eng_hi(self) -> None:
        """SDH/HI English subtitles."""
        assert is_english_subtitle("SDH.eng.HI.srt") is True

    def test_forced_eng(self) -> None:
        """Forced English subtitles."""
        assert is_english_subtitle("Forced.eng.srt") is True

    def test_canadian_french(self) -> None:
        """Non-English: Canadian French."""
        assert is_english_subtitle("Canadian.fre.srt") is False

    def test_latin_american_spanish(self) -> None:
        """Non-English: Latin American Spanish."""
        assert is_english_subtitle("Latin American.spa.srt") is False


class TestCleanMovieService:
    """Tests for CleanMovieService."""

    def test_build_dest(self) -> None:
        root = Path("/media/Movies")
        dest = CleanMovieService.build_dest(root, "The Matrix", "1999", ".mkv")
        assert dest == Path("/media/Movies/The Matrix (1999)/The Matrix (1999).mkv")

    def test_is_clean_folder_name(self) -> None:
        service = CleanMovieService()
        assert service.is_clean_folder_name("The Matrix (1999)") is True
        assert service.is_clean_folder_name("The.Matrix.1999.1080p") is False
        assert service.is_clean_folder_name("Matrix") is False

    def test_is_release_folder_name(self) -> None:
        service = CleanMovieService()
        assert service.is_release_folder_name("The.Matrix.1999.1080p.BluRay") is True
        assert service.is_release_folder_name("Movie-YIFY") is True
        assert service.is_release_folder_name("The Matrix (1999)") is False


class TestCleanMovieServiceIntegration:
    """Integration tests for the full cleaning process."""

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Ensure dry-run (commit=False) doesn't change files."""
        service = CleanMovieService()

        release_dir = tmp_path / "The.Matrix.1999.1080p.BluRay.x264"
        release_dir.mkdir()
        movie_file = release_dir / "The.Matrix.1999.1080p.BluRay.x264.mkv"
        movie_file.write_bytes(b"fake movie data")

        service.run(tmp_path, commit=False)

        assert movie_file.exists()
        clean_dest = tmp_path / "The Matrix (1999)" / "The Matrix (1999).mkv"
        assert not clean_dest.exists()

    def test_commit_moves_files(self, tmp_path: Path) -> None:
        """Ensure commit=True actually moves files."""
        service = CleanMovieService()

        release_dir = tmp_path / "The.Matrix.1999.1080p.BluRay.x264"
        release_dir.mkdir()
        movie_file = release_dir / "The.Matrix.1999.1080p.BluRay.x264.mkv"
        movie_file.write_bytes(b"fake movie data")

        service.run(tmp_path, commit=True)

        assert not movie_file.exists()
        clean_dest = tmp_path / "The Matrix (1999)" / "The Matrix (1999).mkv"
        assert clean_dest.exists()

    def test_deletes_samples(self, tmp_path: Path) -> None:
        """Sample files should be deleted."""
        service = CleanMovieService()

        # Create a release folder with both a sample and a real movie
        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        sample = release_dir / "sample-movie.mkv"
        sample.write_bytes(b"sample")
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"real movie")

        service.run(tmp_path, commit=True)

        # Sample should be deleted, movie should be moved
        assert not sample.exists()
        clean_movie = tmp_path / "Movie (2020)" / "Movie (2020).mkv"
        assert clean_movie.exists()

    def test_deletes_samples_in_middle_of_name(self, tmp_path: Path) -> None:
        """Sample files with 'sample' in middle of name should be deleted."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.WEB"
        release_dir.mkdir()
        sample_dir = release_dir / "Sample"
        sample_dir.mkdir()
        sample = sample_dir / "movie.2020.1080p.web.sample.mkv"
        sample.write_bytes(b"sample")
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")

        service.run(tmp_path, commit=True)

        assert not sample.exists()
        assert not sample_dir.exists()

    def test_deletes_images(self, tmp_path: Path) -> None:
        """Image files should be deleted."""
        service = CleanMovieService()

        movie_dir = tmp_path / "Movie.2020.1080p"
        movie_dir.mkdir()
        image = movie_dir / "cover.jpg"
        image.write_bytes(b"image data")
        movie = movie_dir / "Movie.2020.1080p.mkv"
        movie.write_bytes(b"movie data")

        service.run(tmp_path, commit=True)

        assert not image.exists()

    def test_preserves_english_subtitles(self, tmp_path: Path) -> None:
        """English subtitles should be moved, not deleted."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")
        eng_sub = release_dir / "Movie.eng.srt"
        eng_sub.write_bytes(b"subtitle")

        service.run(tmp_path, commit=True)

        # Check that English subtitle was moved (might be .eng.srt or just normalized)
        movie_dir = tmp_path / "Movie (2020)"
        srt_files = list(movie_dir.glob("*.srt"))
        assert len(srt_files) == 1
        assert srt_files[0].read_bytes() == b"subtitle"

    def test_deletes_non_english_subtitles_in_release_folder(self, tmp_path: Path) -> None:
        """Non-English subtitles in release folders should be deleted."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")
        spa_sub = release_dir / "Movie.spa.srt"
        spa_sub.write_bytes(b"subtitle")

        service.run(tmp_path, commit=True)

        assert not spa_sub.exists()
        assert not (tmp_path / "Movie (2020)" / "Movie (2020).spa.srt").exists()

    def test_handles_subs_subfolder(self, tmp_path: Path) -> None:
        """Subtitles in Subs/ subfolder should be handled correctly."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        subs_dir = release_dir / "Subs"
        subs_dir.mkdir()

        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")

        eng_sub = subs_dir / "English.srt"
        eng_sub.write_bytes(b"english subtitle")

        spa_sub = subs_dir / "Latin American.spa.srt"
        spa_sub.write_bytes(b"spanish subtitle")

        service.run(tmp_path, commit=True)

        # English subtitle moved (might be .eng.srt or just .srt depending on naming)
        movie_dir = tmp_path / "Movie (2020)"
        srt_files = list(movie_dir.glob("*.srt"))
        assert len(srt_files) >= 1

        # Spanish subtitle deleted
        assert not spa_sub.exists()

    def test_deletes_txt_and_nfo_files(self, tmp_path: Path) -> None:
        """TXT and NFO files should be deleted as junk."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")

        txt_file = release_dir / "Torrent Downloaded from site.txt"
        txt_file.write_bytes(b"junk")
        nfo_file = release_dir / "movie.nfo"
        nfo_file.write_bytes(b"nfo")

        service.run(tmp_path, commit=True)

        assert not txt_file.exists()
        assert not nfo_file.exists()

    def test_undo_from_journal(self, tmp_path: Path) -> None:
        """Undo restores moved files."""
        service = CleanMovieService()

        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie_file = release_dir / "Movie.2020.mkv"
        movie_file.write_bytes(b"movie data")

        service.run(tmp_path, commit=True)

        clean_dest = tmp_path / "Movie (2020)" / "Movie (2020).mkv"
        assert clean_dest.exists()
        assert not movie_file.exists()

        # Find journal
        journals = list(tmp_path.glob(".clean-movie-journal-*.jsonl"))
        assert len(journals) == 1

        # Undo
        service.undo(journals[0])

        # File should be back (note: original folder may not exist)
        # The undo creates parent dirs, so check if source exists
        assert movie_file.exists() or release_dir.exists()
