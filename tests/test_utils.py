"""Tests for src.utils helpers."""
import pytest

from src.utils import safe_move, title_case

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


class TestTitleCase:
    """str.title() breaks a word at every non-alpha character, apostrophes
    included, so "eater's" became "Eater'S" and reached the filesystem as a
    folder named "Eater'S Guide To The World (2020)"."""

    @pytest.mark.parametrize("raw,expected", [
        ("eater's guide to the world", "Eater's Guide To The World"),
        ("ocean's eleven", "Ocean's Eleven"),
        ("the king's speech", "The King's Speech"),
    ])
    def test_possessive_stays_lowercase(self, raw, expected):
        assert title_case(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("don't look up", "Don't Look Up"),
        ("we'll never know", "We'll Never Know"),
        ("they've arrived", "They've Arrived"),
        ("you're next", "You're Next"),
        ("i'm not there", "I'm Not There"),
        ("he'd rather", "He'd Rather"),
        ("it's a wonderful life", "It's A Wonderful Life"),
    ])
    def test_contractions_stay_lowercase(self, raw, expected):
        assert title_case(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A longer run after the apostrophe is part of the name, not a suffix.
        ("o'brien", "O'Brien"),
        ("d'artagnan", "D'Artagnan"),
        ("the o'reilly factor", "The O'Reilly Factor"),
    ])
    def test_names_keep_their_capital(self, raw, expected):
        assert title_case(raw) == expected

    def test_mixed_case_in_one_word(self):
        """Both apostrophes judged independently: 'n is a suffix, 'Roll is not."""
        assert title_case("rock'n'roll high school") == "Rock'n'Roll High School"

    @pytest.mark.parametrize("raw,expected", [
        ("the dark knight", "The Dark Knight"),
        ("spider-man far from home", "Spider-Man Far From Home"),
        ("batman - the animated series", "Batman - The Animated Series"),
    ])
    def test_ordinary_titles_are_unchanged_in_behaviour(self, raw, expected):
        assert title_case(raw) == expected

    def test_short_acronyms_only_when_asked(self):
        assert title_case("FBI movie") == "Fbi Movie"
        assert title_case("FBI movie", preserve_short_acronyms=True) == "FBI Movie"

    def test_whitespace_is_normalized(self):
        assert title_case("  the   dark  knight ") == "The Dark Knight"

    def test_empty(self):
        assert title_case("") == ""
