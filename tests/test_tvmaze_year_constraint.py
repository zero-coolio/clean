"""An explicit year in a filename constrains the TVMaze match (CLEAN-7).

These build raw TVMaze search payloads rather than hitting the network, so the
rule is pinned without depending on the live API.
"""
import pytest

from src.tvmaze import _best_match


def result(name, premiered, score, sid):
    return {"score": score, "show": {"id": sid, "name": name, "premiered": premiered}}


WONDER = [
    result("Wonder Woman", "1975-11-07", 0.92, 1817),
    result("Wonder Woman '77", "1977-01-01", 0.61, 9999),
]


class TestYearIsAConstraint:
    def test_no_candidate_in_the_stated_year_means_no_match(self):
        """The Wonder Women case: 2019 drama must not become a 1975 series."""
        assert _best_match(WONDER, "2019") is None

    def test_exact_year_still_matches(self):
        sid, name, year = _best_match(WONDER, "1975")
        assert (sid, name, year) == (1817, "Wonder Woman", "1975")

    def test_prefers_year_match_over_higher_score(self):
        sid, name, year = _best_match(WONDER, "1977")
        assert name == "Wonder Woman '77"
        assert year == "1977"

    @pytest.mark.parametrize("off_by", ["1974", "1976", "2019", "1993"])
    def test_any_mismatch_is_refused(self, off_by):
        assert _best_match(WONDER, off_by) is None

    def test_missing_premiere_date_does_not_satisfy_a_year(self):
        undated = [result("Wonder Woman", None, 0.95, 1)]
        assert _best_match(undated, "2019") is None


class TestNoYearSupplied:
    """Without a year the old behaviour stands: highest score wins."""

    def test_highest_score_wins(self):
        sid, name, year = _best_match(WONDER, None)
        assert (sid, name, year) == (1817, "Wonder Woman", "1975")

    def test_empty_results(self):
        assert _best_match([], None) is None
        assert _best_match([], "2019") is None

    def test_skips_entries_missing_id_or_name(self):
        junk = [{"score": 9.0, "show": {"name": "No Id"}},
                {"score": 8.0, "show": {"id": 5}},
                result("Real", "2001-01-01", 0.1, 7)]
        sid, name, _ = _best_match(junk, None)
        assert (sid, name) == (7, "Real")
