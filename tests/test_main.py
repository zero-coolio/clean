#!/usr/bin/env python3
"""Tests for main entry points."""
import sys
from pathlib import Path

import pytest

from src.Main import main as tv_main
from src.MovieMain import main as movie_main


class TestTVMain:
    """Tests for Clean-TV main entry point."""

    def test_runs_with_empty_directory(self, tmp_path: Path, monkeypatch) -> None:
        """Should run without errors on an empty directory."""
        root = tmp_path / "intake"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["clean-tv", "--directory", str(root)])
        tv_main()

    def test_dry_run_creates_no_journal(self, tmp_path: Path, monkeypatch) -> None:
        """Dry-run without --plan should not create journal."""
        root = tmp_path / "intake"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["clean-tv", "--directory", str(root)])
        tv_main()

        journals = list(root.glob(".clean-tv-journal-*.jsonl"))
        assert len(journals) == 0

    def test_plan_creates_journal(self, tmp_path: Path, monkeypatch) -> None:
        """--plan flag should create journal even in dry-run."""
        root = tmp_path / "intake"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["clean-tv", "--directory", str(root), "--plan"])
        tv_main()

        journals = list(root.glob(".clean-tv-journal-*.jsonl"))
        assert len(journals) == 1


class TestMovieMain:
    """Tests for Clean-Movie main entry point."""

    def test_runs_with_empty_directory(self, tmp_path: Path, monkeypatch) -> None:
        """Should run without errors on an empty directory."""
        root = tmp_path / "movies"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["clean-movie", "--directory", str(root)])
        movie_main()

    def test_dry_run_creates_no_journal(self, tmp_path: Path, monkeypatch) -> None:
        """Dry-run without --plan should not create journal."""
        root = tmp_path / "movies"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["clean-movie", "--directory", str(root)])
        movie_main()

        journals = list(root.glob(".clean-movie-journal-*.jsonl"))
        assert len(journals) == 0

    def test_commit_creates_journal(self, tmp_path: Path, monkeypatch) -> None:
        """--commit flag should create journal."""
        root = tmp_path / "movies"
        root.mkdir()
        
        # Add a movie file so the directory doesn't get deleted
        movie_dir = root / "Movie.2020.1080p"
        movie_dir.mkdir()
        movie = movie_dir / "Movie.2020.mkv"
        movie.write_bytes(b"movie data")

        monkeypatch.setattr(sys, "argv", ["clean-movie", "--directory", str(root), "--commit"])
        movie_main()

        journals = list(root.glob(".clean-movie-journal-*.jsonl"))
        assert len(journals) == 1
