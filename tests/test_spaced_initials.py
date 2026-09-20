"""An initialled title must survive the dots-to-spaces rewrite (CLEAN-17).

`_clean_show_name` turns "R.J.Decker" into the show "R J Decker". TVMaze returns
0 results for that spelling and matches "RJ Decker" instantly, so without
rejoining the initials the show is simply unfindable and keeps an unverified,
yearless name. Real case: R.J.Decker.S02E01 was filed as "R J Decker/Season 02"
instead of joining "R.J. Decker (2026)".
"""
import pytest

from src.tvmaze import _join_initials, _query_variants


class TestJoinInitials:
    @pytest.mark.parametrize("name,expected", [
        ("R J Decker", "RJ Decker"),
        ("S W A T", "SWAT"),
        ("C S Forester's Horatio Hornblower", "CS Forester's Horatio Hornblower"),
        ("A B C D", "ABCD"),
        ("Decker R J", "Decker RJ"),
    ])
    def test_runs_are_merged(self, name, expected):
        assert _join_initials(name) == expected

    @pytest.mark.parametrize("name", [
        "Gotham", "Letterkenny", "The Road Trip", "Top Gear", "Banshee",
    ])
    def test_ordinary_names_untouched(self, name):
        assert _join_initials(name) == name

    def test_single_letter_alone_is_not_a_run(self):
        """One initial has nothing to join to, so the name is unchanged."""
        assert _join_initials("M Squad") == "M Squad"


class TestQueryVariants:
    def test_joined_form_is_offered(self):
        assert "RJ Decker" in _query_variants("R J Decker")

    def test_full_name_still_tried_first(self):
        assert _query_variants("R J Decker")[0] == "R J Decker"

    def test_joined_form_precedes_the_tail_fallback(self):
        """A real name must be tried before any generic-suffix guess."""
        variants = _query_variants("C S Forester's Horatio Hornblower")
        assert variants.index("CS Forester's Horatio Hornblower") < variants.index("Horatio Hornblower")

    def test_no_duplicate_variants(self):
        for name in ["R J Decker", "Gotham", "C S Forester's Horatio Hornblower"]:
            v = _query_variants(name)
            assert len(v) == len(set(v)), f"duplicate variants for {name!r}: {v}"
