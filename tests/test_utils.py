"""Tests for src.utils helpers."""
import pytest

from src.utils import safe_move

class TestSafeMoveDryRun:
    """A dry run must survive a destination that a planned delete would clear.

    Regression: safe_move checked dst.exists() BEFORE its not-commit return, so
    a conflict-resolution delete (logged but not executed in a dry run) left
    dst on disk and the follow-up move raised FileExistsError, aborting the
    whole preview at the first replace-conflict.
    """

    def test_dry_run_tolerates_existing_destination(self, tmp_path) -> None:
        src = tmp_path / "src.mkv"
        dst = tmp_path / "dst.mkv"
        src.write_text("SRC", encoding="utf-8")
        dst.write_text("DST", encoding="utf-8")

        journal: list[dict] = []
        safe_move(src, dst, commit=False, journal=journal)  # must not raise

        assert src.read_text(encoding="utf-8") == "SRC"
        assert dst.read_text(encoding="utf-8") == "DST"
        assert journal == []

    def test_commit_run_still_refuses_existing_destination(self, tmp_path) -> None:
        src = tmp_path / "src.mkv"
        dst = tmp_path / "dst.mkv"
        src.write_text("SRC", encoding="utf-8")
        dst.write_text("DST", encoding="utf-8")

        with pytest.raises(FileExistsError):
            safe_move(src, dst, commit=True, journal=[])
