"""Tests for title identity comparison and the no-identity guard (CLEAN-19).

Every string here is real: the stems come off /Volumes/Summer/movie-archive and
the candidate titles are what TMDB actually returned for them in the
2026-09-27 preview. Per CLAUDE.md, invented names encode what we already
believe, which is the assumption under test.
"""
from __future__ import annotations

import pytest

from src.title_match import is_substantive, normalize, titles_match


class TestIsSubstantive:
    """A query that cannot identify a film must not be sent to a database."""

    @pytest.mark.parametrize("stem", [
        "Untitled",          # sat inside "The Thing (1982)"
        "Extra-1", "Extra-2", "Extra-4", "Extra-5",   # Green Lantern extras
        "Deleted Scenes", "Bonus Features", "Featurette",
        "movie", "Feature", "01", "1", "",
    ])
    def test_placeholder_stems_are_refused(self, stem):
        assert not is_substantive(stem)

    @pytest.mark.parametrize("stem", [
        "Snatch", "Watchmen", "Monolith", "Untitled Horror Movie",
        "spider-man", "Pitch.Black", "The Thing", "300", "13 Assassins",
    ])
    def test_real_titles_are_allowed_through(self, stem):
        assert is_substantive(stem)

    def test_a_short_title_is_not_a_placeholder(self):
        """Disqualification is by vocabulary, never by length."""
        assert is_substantive("Up")
        assert is_substantive("It")

    def test_a_placeholder_plus_a_real_word_is_substantive(self):
        """"Untitled Horror Movie" is a real film; refuse only pure noise."""
        assert is_substantive("Untitled Horror Movie")


class TestTitlesMatch:
    """The answer must be the question. Fuzzy is not evidence."""

    @pytest.mark.parametrize("query,candidate", [
        ("spider-man", "Spider-Man: Brand New Day"),   # an unreleased film
        ("Extra-1", "His Cat: Extra Chapter 1"),
        ("Extra-2", "Initial D: Extra Stage 2 - Green Departure"),
        ("Extra-5", "The Gendarme and the Creatures from Outer Space"),
        ("far from home", "Spider-Man: Far From Home"),
        ("Cliffy", "Fluffy Paradise"),
        ("Take Shelter", "Hello Kitty's Furry Tale Theater"),
    ])
    def test_near_misses_are_rejected(self, query, candidate):
        assert not titles_match(query, candidate)

    @pytest.mark.parametrize("query,candidate", [
        ("Pitch.Black", "Pitch Black"),
        ("The.Mummy.Returns", "The Mummy Returns"),
        ("R.I.P.D.2.Rise.of.The.Damned", "R.I.P.D. 2: Rise of the Damned"),
        ("Matrix", "The Matrix"),                      # article-insensitive
        ("watchmen", "Watchmen"),
    ])
    def test_true_matches_are_accepted(self, query, candidate):
        assert titles_match(query, candidate)

    @pytest.mark.parametrize("query,candidate", [
        ("Millers Crossing", "Miller's Crossing"),
        ("Eaters Guide to the World", "Eater's Guide to the World"),
        ("Oceans Eleven", "Ocean's Eleven"),
    ])
    def test_an_apostrophe_is_deleted_not_blanked(self, query, candidate):
        """Blanking it split "Miller's" into "miller s" and lost the match."""
        assert titles_match(query, candidate)

    def test_ampersand_folds_to_and(self):
        assert titles_match("Wallace & Gromit", "Wallace and Gromit")

    def test_an_empty_query_never_matches(self):
        assert not titles_match("", "Anything")


class TestNormalize:
    def test_strips_a_leading_article(self):
        assert normalize("The Matrix") == normalize("Matrix") == "matrix"

    def test_is_idempotent(self):
        once = normalize("The  Dark.Knight!")
        assert normalize(once) == once
