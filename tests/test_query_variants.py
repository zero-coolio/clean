"""The tail-word fallback must only fire on real author/initial cruft (CLEAN-12).

TVMaze returns nothing for some long release names, so a tail variant is the
only match on offer, which makes a bad tail match especially dangerous: it is
never outvoted. Applied to every long name it absorbed whole shows into
unrelated ones by their generic suffix.
"""
import pytest

from src.tvmaze import _is_author_cruft, _query_variants


class TestAuthorCruftDetection:
    @pytest.mark.parametrize("prefix", [
        ["C", "S", "Forester's"],
        ["Forester's"],
        ["C", "S"],
        ["Terry", "Pratchett's"],
        ["J.", "R.", "R."],
    ])
    def test_cruft(self, prefix):
        assert _is_author_cruft(prefix)

    @pytest.mark.parametrize("prefix", [
        ["Top", "Gear"],
        ["Spider", "Man"],
        ["The", "Perfect"],
        [],
    ])
    def test_not_cruft(self, prefix):
        assert not _is_author_cruft(prefix)


class TestTailFallbackGating:
    def test_author_cruft_still_yields_the_tail(self):
        """The case the fallback was built for must keep working."""
        assert "Horatio Hornblower" in _query_variants("C S Forester's Horatio Hornblower")

    @pytest.mark.parametrize("name,forbidden", [
        ("Spider Man The Animated Series", "The Animated Series"),
        ("Spider Man The Animated Series", "Animated Series"),
        ("Top Gear The Perfect Road Trip", "Road Trip"),
        ("Top Gear The Perfect Road Trip", "Perfect Road Trip"),
    ])
    def test_generic_tails_are_not_offered(self, name, forbidden):
        assert forbidden not in _query_variants(name)

    def test_full_name_is_always_tried_first(self):
        for name in ["Spider Man The Animated Series", "Top Gear The Perfect Road Trip"]:
            assert _query_variants(name)[0] == name

    def test_short_names_never_get_tails(self):
        assert _query_variants("Gotham") == ["Gotham"]
