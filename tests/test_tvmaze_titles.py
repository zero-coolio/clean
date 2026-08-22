"""Unit tests for TVMaze episode-title classification.

The two predicates answer different questions on purpose — see the module
docstring. These tests pin that difference so neither drifts into the other.
"""
import pytest

from src.tvmaze_titles import is_identifying_title, real_title


@pytest.mark.parametrize("title", ["TBA", "tbd", " To Be Announced ", "TO BE DETERMINED"])
def test_placeholders_are_neither_filename_worthy_nor_identifying(title):
    assert real_title(title) is None
    assert is_identifying_title(title) is False


@pytest.mark.parametrize("title", ["", None])
def test_empty_titles_are_rejected_by_both(title):
    assert real_title(title) is None
    assert is_identifying_title(title) is False


@pytest.mark.parametrize("title", ["Episode 6", "episode 12", "Ep 4", "Ep. 4", "Episode #7"])
def test_positional_titles_are_filename_worthy_but_not_identifying(title):
    """"Episode 6" is all TVMaze has for some shows, so it still goes in the
    filename — but it appears in thousands of shows and identifies none."""
    assert real_title(title) == title
    assert is_identifying_title(title) is False


@pytest.mark.parametrize(
    "title",
    ["We Don't Fight at Weddings", "Episode of the Year", "The Episode", "Episode Four", "1x06"],
)
def test_genuine_titles_pass_both(title):
    assert real_title(title) == title
    assert is_identifying_title(title) is True
