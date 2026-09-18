"""Leading tracker/site prefixes must not become part of the show name (CLEAN-10).

`NOISE_PREFIX_PATTERNS` was an allowlist of six site names, so any new tracker
silently poisoned the parse: "[Torrentcouch.Com].Gotham.S04E19.mp4" parsed to the
show "[Torrentcouch Com] Gotham", which TVMaze cannot match, so 22 Gotham season
4 episodes were filed under that junk name and looked "already placed" forever.
"""
import pytest

from src.service.clean_service import parse_episode_detail
from src.utils import strip_noise_prefix


class TestDomainLikeBracketStripped:
    @pytest.mark.parametrize("name,expected", [
        ("[Torrentcouch.Com].Gotham.S04E19.mp4", "Gotham.S04E19.mp4"),
        ("[Torrentcouch Com] Gotham", "Gotham"),
        ("[www.Site.org] Show.S01E01.mkv", "Show.S01E01.mkv"),
        ("[Some.Tracker.net]_Show.S01E01.mkv", "Show.S01E01.mkv"),
        ("[tracker.to] Show.S01E01.mkv", "Show.S01E01.mkv"),
    ])
    def test_stripped(self, name, expected):
        assert strip_noise_prefix(name) == expected

    def test_known_tags_still_stripped(self):
        assert strip_noise_prefix("[rartv] Thing.S01E01.mkv") == "Thing.S01E01.mkv"
        assert strip_noise_prefix("[YTS] Thing.S01E01.mkv") == "Thing.S01E01.mkv"


class TestNonDomainBracketsLeftAlone:
    """Only domain-like brackets go. A bracket is not automatically noise."""

    @pytest.mark.parametrize("name", [
        "[2019] Some Show S01E01.mkv",
        "[DXO] Thing.S01E01.mkv",
        "[Complete Series] Thing.S01E01.mkv",
    ])
    def test_preserved(self, name):
        assert strip_noise_prefix(name) == name


class TestGothamParsesToTheRealShow:
    def test_show_name_is_clean(self):
        d = parse_episode_detail("[Torrentcouch.Com].Gotham.S04E19.mp4")
        assert d.show == "Gotham"
        assert (d.season, d.episode) == ("04", "19")

    def test_every_stranded_episode_parses(self):
        """All 22 season 4 files, not just the one that was eyeballed."""
        for ep in range(1, 23):
            d = parse_episode_detail(f"[Torrentcouch.Com].Gotham.S04E{ep:02d}.mp4")
            assert d.show == "Gotham"
            assert (d.season, d.episode) == ("04", f"{ep:02d}")
