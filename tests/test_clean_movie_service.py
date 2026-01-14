#!/usr/bin/env python3
"""Tests for CleanMovieService."""
import pytest
from pathlib import Path

from src.service.clean_movie_service import (
    parse_movie_from_string,
    clean_movie_title,
    is_english_subtitle,
    CleanMovieService,
    SUBTITLE_EXT,
)


class TestParseMovieFromString:
    """Tests for movie name/year parsing."""

    def test_dotted_format(self):
        """Standard torrent naming: Movie.Name.Year.Quality..."""
        result = parse_movie_from_string("The.Matrix.1999.1080p.BluRay.x264-GROUP")
        assert result == ("The Matrix", "1999")

    def test_dotted_format_with_spaces_in_title(self):
        result = parse_movie_from_string("No.Country.for.Old.Men.2007.720p.BRRip")
        assert result == ("No Country For Old Men", "2007")

    def test_parenthesized_year(self):
        """Clean format: Movie Name (Year)"""
        result = parse_movie_from_string("The Matrix (1999)")
        assert result == ("The Matrix", "1999")

    def test_parenthesized_year_with_ext(self):
        result = parse_movie_from_string("The Matrix (1999).mkv")
        assert result == ("The Matrix", "1999")

    def test_year_with_hyphen(self):
        result = parse_movie_from_string("Inception-2010-1080p")
        assert result == ("Inception", "2010")

    def test_year_with_underscore(self):
        result = parse_movie_from_string("Inception_2010_1080p")
        assert result == ("Inception", "2010")

    def test_sequel_with_number(self):
        result = parse_movie_from_string("Die.Hard.2.1990.1080p.BluRay")
        assert result == ("Die Hard 2", "1990")

    def test_year_at_different_position(self):
        result = parse_movie_from_string("2001.A.Space.Odyssey.1968.1080p")
        assert result == ("2001 A Space Odyssey", "1968")

    def test_no_year_returns_none(self):
        result = parse_movie_from_string("SomeRandomFile.mkv")
        assert result is None

    def test_yts_prefix(self):
        result = parse_movie_from_string("[YTS] The.Dark.Knight.2008.1080p")
        assert result == ("The Dark Knight", "2008")

    def test_rarbg_prefix(self):
        result = parse_movie_from_string("rarbg-Interstellar.2014.2160p.UHD")
        assert result == ("Interstellar", "2014")


class TestCleanMovieTitle:
    """Tests for title cleaning."""

    def test_removes_dots(self):
        assert clean_movie_title("The.Dark.Knight") == "The Dark Knight"

    def test_removes_underscores(self):
        assert clean_movie_title("The_Dark_Knight") == "The Dark Knight"

    def test_removes_quality_markers(self):
        assert clean_movie_title("Inception 1080p BluRay") == "Inception"

    def test_preserves_acronyms(self):
        assert clean_movie_title("FBI.Movie") == "FBI Movie"

    def test_title_case(self):
        assert clean_movie_title("the dark knight") == "The Dark Knight"


class TestIsEnglishSubtitle:
    """Tests for English subtitle detection."""

    def test_eng_suffix(self):
        assert is_english_subtitle("movie.eng.srt") is True

    def test_en_suffix(self):
        assert is_english_subtitle("movie.en.srt") is True

    def test_english_suffix(self):
        assert is_english_subtitle("movie.english.srt") is True

    def test_spanish_suffix(self):
        assert is_english_subtitle("movie.spa.srt") is False

    def test_no_language_tag(self):
        assert is_english_subtitle("movie.srt") is False

    def test_non_subtitle_file(self):
        assert is_english_subtitle("movie.eng.txt") is False

    def test_plain_english_filename(self):
        """Files named just 'English.srt' in Subs folders."""
        assert is_english_subtitle("English.srt") is True

    def test_sdh_eng_hi(self):
        """SDH/HI English subtitles."""
        assert is_english_subtitle("SDH.eng.HI.srt") is True

    def test_forced_eng(self):
        """Forced English subtitles."""
        assert is_english_subtitle("Forced.eng.srt") is True

    def test_canadian_french(self):
        """Non-English: Canadian French."""
        assert is_english_subtitle("Canadian.fre.srt") is False

    def test_latin_american_spanish(self):
        """Non-English: Latin American Spanish."""
        assert is_english_subtitle("Latin American.spa.srt") is False


class TestCleanMovieService:
    """Tests for CleanMovieService."""

    def test_build_dest(self):
        service = CleanMovieService()
        root = Path("/media/Movies")
        dest = service.build_dest(root, "The Matrix", "1999", ".mkv")
        assert dest == Path("/media/Movies/The Matrix (1999)/The Matrix (1999).mkv")

    def test_build_sidecar_dest_with_lang(self):
        service = CleanMovieService()
        root = Path("/media/Movies")
        dest = service.build_sidecar_dest(root, "The Matrix", "1999", "matrix.eng.srt")
        assert dest == Path("/media/Movies/The Matrix (1999)/The Matrix (1999).eng.srt")

    def test_build_sidecar_dest_no_lang(self):
        service = CleanMovieService()
        root = Path("/media/Movies")
        dest = service.build_sidecar_dest(root, "The Matrix", "1999", "matrix.srt")
        assert dest == Path("/media/Movies/The Matrix (1999)/The Matrix (1999).srt")

    def test_is_clean_folder_name(self):
        assert CleanMovieService._is_clean_folder_name("The Matrix (1999)") is True
        assert CleanMovieService._is_clean_folder_name("The.Matrix.1999.1080p") is False
        assert CleanMovieService._is_clean_folder_name("Matrix") is False

    def test_is_release_folder_name(self):
        assert CleanMovieService._is_release_folder_name("The.Matrix.1999.1080p.BluRay") is True
        assert CleanMovieService._is_release_folder_name("Movie-YIFY") is True
        assert CleanMovieService._is_release_folder_name("The Matrix (1999)") is False

    def test_unique_path(self, tmp_path):
        service = CleanMovieService()
        
        # Non-existent path returns as-is
        p = tmp_path / "movie.mkv"
        assert service.unique_path(p) == p
        
        # Existing path gets (alt) suffix
        p.touch()
        alt = service.unique_path(p)
        assert alt == tmp_path / "movie (alt).mkv"
        
        # Multiple alts increment
        alt.touch()
        alt2 = service.unique_path(p)
        assert alt2 == tmp_path / "movie (alt 2).mkv"

    def test_same_content(self, tmp_path):
        service = CleanMovieService()
        
        # Create two files with same content
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"hello world")
        b.write_bytes(b"hello world")
        
        assert service.same_content(a, b) is True
        
        # Different content
        b.write_bytes(b"different")
        assert service.same_content(a, b) is False


class TestCleanMovieServiceIntegration:
    """Integration tests for the full cleaning process."""

    def test_dry_run_does_not_modify(self, tmp_path):
        """Ensure dry-run (commit=False) doesn't change files."""
        service = CleanMovieService()
        
        # Create a movie file in release folder format
        release_dir = tmp_path / "The.Matrix.1999.1080p.BluRay.x264"
        release_dir.mkdir()
        movie_file = release_dir / "The.Matrix.1999.1080p.BluRay.x264.mkv"
        movie_file.write_bytes(b"fake movie data")
        
        # Run without commit
        service.run(tmp_path, commit=False)
        
        # Original should still exist
        assert movie_file.exists()
        
        # Clean destination should NOT exist
        clean_dest = tmp_path / "The Matrix (1999)" / "The Matrix (1999).mkv"
        assert not clean_dest.exists()

    def test_commit_moves_files(self, tmp_path):
        """Ensure commit=True actually moves files."""
        service = CleanMovieService()
        
        # Create a movie file
        release_dir = tmp_path / "The.Matrix.1999.1080p.BluRay.x264"
        release_dir.mkdir()
        movie_file = release_dir / "The.Matrix.1999.1080p.BluRay.x264.mkv"
        movie_file.write_bytes(b"fake movie data")
        
        # Run with commit
        service.run(tmp_path, commit=True)
        
        # Original should be gone
        assert not movie_file.exists()
        
        # Clean destination should exist
        clean_dest = tmp_path / "The Matrix (1999)" / "The Matrix (1999).mkv"
        assert clean_dest.exists()

    def test_deletes_samples(self, tmp_path):
        """Sample files should be deleted."""
        service = CleanMovieService()
        
        movie_dir = tmp_path / "Movie (2020)"
        movie_dir.mkdir()
        sample = movie_dir / "sample-movie.mkv"
        sample.write_bytes(b"sample")
        
        service.run(tmp_path, commit=True)
        
        assert not sample.exists()

    def test_deletes_samples_in_middle_of_name(self, tmp_path):
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

    def test_deletes_images(self, tmp_path):
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

    def test_preserves_english_subtitles(self, tmp_path):
        """English subtitles should be moved, not deleted."""
        service = CleanMovieService()
        
        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")
        eng_sub = release_dir / "Movie.eng.srt"
        eng_sub.write_bytes(b"subtitle")
        
        service.run(tmp_path, commit=True)
        
        # English subtitle should be moved
        clean_sub = tmp_path / "Movie (2020)" / "Movie (2020).eng.srt"
        assert clean_sub.exists()

    def test_deletes_non_english_subtitles_in_release_folder(self, tmp_path):
        """Non-English subtitles in release folders should be deleted."""
        service = CleanMovieService()
        
        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")
        spa_sub = release_dir / "Movie.spa.srt"
        spa_sub.write_bytes(b"subtitle")
        
        service.run(tmp_path, commit=True)
        
        # Spanish subtitle should be deleted
        assert not spa_sub.exists()
        assert not (tmp_path / "Movie (2020)" / "Movie (2020).spa.srt").exists()

    def test_handles_subs_subfolder(self, tmp_path):
        """Subtitles in Subs/ subfolder should be handled correctly."""
        service = CleanMovieService()
        
        release_dir = tmp_path / "Movie.2020.1080p.BluRay"
        release_dir.mkdir()
        subs_dir = release_dir / "Subs"
        subs_dir.mkdir()
        
        movie = release_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie")
        
        # English subtitle in Subs folder
        eng_sub = subs_dir / "English.srt"
        eng_sub.write_bytes(b"english subtitle")
        
        # Non-English subtitle in Subs folder
        spa_sub = subs_dir / "Latin American.spa.srt"
        spa_sub.write_bytes(b"spanish subtitle")
        
        service.run(tmp_path, commit=True)
        
        # English subtitle should be moved
        clean_eng = tmp_path / "Movie (2020)" / "Movie (2020).eng.srt"
        assert clean_eng.exists() or (tmp_path / "Movie (2020)" / "Movie (2020).srt").exists()
        
        # Spanish subtitle should be deleted
        assert not spa_sub.exists()

    def test_deletes_txt_and_nfo_files(self, tmp_path):
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
        
        # Both should be deleted
        assert not txt_file.exists()
        assert not nfo_file.exists()
