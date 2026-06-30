"""Tests for TVMaze-id collapse + episode renumbering (clean_service).

All offline — TVMaze access is monkeypatched. Covers:
  * parse_episode_detail: poison-strip of a spurious trailing SxxExx, episode
    title-hint extraction, the seasonless flag, media-extension stripping, and
    that normal/correct filenames are left untouched.
  * _remap_episode_via_tvmaze: title-match, sequential-index, flattened-season-1
    remap, and the no-op-when-already-valid case.
  * _canonical_show: two name spellings that resolve to one show id collapse to
    a single canonical folder name.
"""
from __future__ import annotations

import src.tvmaze as tvmaze
from src.service.clean_service import (
    CleanService,
    ParsedEpisode,
    parse_episode_detail,
)

# Canonical TVMaze episode list for show 1632 (year-based seasons).
HORNBLOWER_EPS = [
    {"season": 1998, "episode": 1, "title": "Hornblower: The Even Chance", "airdate": "1998-10-07"},
    {"season": 1998, "episode": 2, "title": "Hornblower: The Examination for Lieutenant", "airdate": ""},
    {"season": 1998, "episode": 3, "title": "Hornblower: The Duchess and the Devil", "airdate": ""},
    {"season": 1999, "episode": 4, "title": "Hornblower: The Frogs and the Lobsters", "airdate": ""},
    {"season": 2001, "episode": 1, "title": "Hornblower: Mutiny", "airdate": ""},
    {"season": 2001, "episode": 2, "title": "Hornblower: Retribution", "airdate": ""},
    {"season": 2003, "episode": 1, "title": "Hornblower: Loyalty", "airdate": ""},
    {"season": 2003, "episode": 2, "title": "Hornblower: Duty", "airdate": ""},
]


# ---------------------------------------------------------------------------
# parse_episode_detail
# ---------------------------------------------------------------------------

class TestParseDetail:
    def test_strips_poison_trailing_sxxexx(self) -> None:
        d = parse_episode_detail(
            "Horatio.Hornblower.03.The.Duchess.And.The.Devil.480P.H.S02E64.mp4"
        )
        assert d is not None
        assert d.show == "Horatio Hornblower"
        assert (d.season, d.episode) == ("01", "03")
        assert d.seasonless is True
        assert d.title_hint == "The Duchess And The Devil"

    def test_media_extension_does_not_leak_into_title(self) -> None:
        d = parse_episode_detail("Horatio.Hornblower.05.Mutiny.480P.H.S02E64.mkv")
        assert d is not None
        assert d.title_hint == "Mutiny"  # not "Mutiny Mkv"

    def test_explicit_sxxexx_with_year_no_title(self) -> None:
        d = parse_episode_detail("C.S.Forester'S.Horatio.Hornblower.(1998).S01E01.mp4")
        assert d is not None
        assert (d.season, d.episode) == ("01", "01")
        assert d.seasonless is False
        assert d.title_hint == ""

    def test_normal_file_untouched(self) -> None:
        # A correctly-numbered release must not be treated as poisoned and must
        # keep its real season/episode; no title hint is invented.
        d = parse_episode_detail("Below.Deck.Mediterranean.S10E06.720p.WEB.H264-SKYFiRE.mkv")
        assert d is not None
        assert d.show == "Below Deck Mediterranean"
        assert (d.season, d.episode) == ("10", "06")
        assert d.seasonless is False

    def test_legit_trailing_sxxexx_not_stripped(self) -> None:
        # No bare-episode number precedes it, so the SxxExx is the real marker.
        d = parse_episode_detail("Severance.720p.S02E03.mkv")
        assert d is not None
        assert (d.season, d.episode) == ("02", "03")

    def test_number_in_title_not_an_episode(self) -> None:
        # "Studio 60" — the 60 must not be read as an episode number.
        d = parse_episode_detail("Studio.60.on.the.Sunset.Strip.S01E03.mkv")
        assert d is not None
        assert d.show == "Studio 60 On The Sunset Strip"
        assert (d.season, d.episode) == ("01", "03")


# ---------------------------------------------------------------------------
# _remap_episode_via_tvmaze
# ---------------------------------------------------------------------------

class TestRenumber:
    def _svc(self, monkeypatch) -> CleanService:
        monkeypatch.setattr(tvmaze, "get_show_episodes", lambda name, logger=None: HORNBLOWER_EPS)
        return CleanService()

    def test_title_match(self, monkeypatch) -> None:
        svc = self._svc(monkeypatch)
        d = ParsedEpisode("Hornblower", "01", "03", "The Duchess And The Devil", True)
        assert svc._remap_episode_via_tvmaze("Hornblower", "01", "03", d) == ("1998", "03")

    def test_title_match_with_punctuation(self, monkeypatch) -> None:
        svc = self._svc(monkeypatch)
        d = ParsedEpisode("Hornblower", "01", "05", "Mutiny", True)
        assert svc._remap_episode_via_tvmaze("Hornblower", "01", "05", d) == ("2001", "01")

    def test_sequential_index_when_title_absent(self, monkeypatch) -> None:
        # "The Wong War" won't title-match "The Frogs and the Lobsters", so the
        # seasonless episode number falls back to the 1-based ordered index.
        svc = self._svc(monkeypatch)
        d = ParsedEpisode("Hornblower", "01", "04", "The Wong War", True)
        assert svc._remap_episode_via_tvmaze("Hornblower", "01", "04", d) == ("1999", "04")

    def test_flattened_season1_no_title_uses_index(self, monkeypatch) -> None:
        # Explicit S01E02 (not seasonless) but TVMaze has no season 1 → index.
        svc = self._svc(monkeypatch)
        d = ParsedEpisode("Hornblower", "01", "02", "", False)
        assert svc._remap_episode_via_tvmaze("Hornblower", "01", "02", d) == ("1998", "02")

    def test_noop_when_pair_is_real(self, monkeypatch) -> None:
        # A pair that genuinely exists in the TVMaze list is left untouched.
        svc = self._svc(monkeypatch)
        d = ParsedEpisode("Hornblower", "2001", "02", "", False)
        assert svc._remap_episode_via_tvmaze("Hornblower", "2001", "02", d) == ("2001", "02")

    def test_no_remap_without_tvmaze_data(self, monkeypatch) -> None:
        monkeypatch.setattr(tvmaze, "get_show_episodes", lambda name, logger=None: None)
        svc = CleanService()
        d = ParsedEpisode("Mystery Show", "01", "07", "Whatever", True)
        assert svc._remap_episode_via_tvmaze("Mystery Show", "01", "07", d) == ("01", "07")

    def test_real_season1_show_not_index_remapped(self, monkeypatch) -> None:
        # A show that genuinely uses season 1: an absent S01E99 must NOT be
        # index-remapped (TVMaze has real season-1 episodes).
        eps = [{"season": 1, "episode": n, "title": f"Ep {n}", "airdate": ""} for n in range(1, 11)]
        monkeypatch.setattr(tvmaze, "get_show_episodes", lambda name, logger=None: eps)
        svc = CleanService()
        d = ParsedEpisode("Normal Show", "01", "99", "", False)
        assert svc._remap_episode_via_tvmaze("Normal Show", "01", "99", d) == ("01", "99")


# ---------------------------------------------------------------------------
# _canonical_show id-collapse
# ---------------------------------------------------------------------------

class TestIdCollapse:
    def test_variant_spellings_collapse_to_one_canonical(self, monkeypatch) -> None:
        # Both spellings resolve to show id 1632 → identical canonical folder.
        def fake_lookup(name, logger=None):
            return ("C.S. Forester's Horatio Hornblower", "1998")

        monkeypatch.setattr(tvmaze, "lookup_show", fake_lookup)
        monkeypatch.setattr(tvmaze, "resolve_show_id", lambda name, logger=None: 1632)

        svc = CleanService()
        a = svc._canonical_show("Horatio Hornblower", "01", "03")
        b = svc._canonical_show("C S Forester'S Horatio Hornblower (1998)", "01", "01")
        assert a == b == "C.S. Forester's Horatio Hornblower (1998)"

    def test_distinct_ids_do_not_collapse(self, monkeypatch) -> None:
        table = {
            "show a": (("Show A", "2001"), 11),
            "show b": (("Show B", "2002"), 22),
        }
        monkeypatch.setattr(tvmaze, "lookup_show", lambda name, logger=None: table[name.lower()][0])
        monkeypatch.setattr(tvmaze, "resolve_show_id", lambda name, logger=None: table[name.lower()][1])

        svc = CleanService()
        assert svc._canonical_show("Show A", "01", "01") == "Show A (2001)"
        assert svc._canonical_show("Show B", "01", "01") == "Show B (2002)"


# ---------------------------------------------------------------------------
# lookup_episode_name: placeholder ("TBA") titles must not become filenames
# ---------------------------------------------------------------------------

class TestPlaceholderTitle:
    """An unannounced episode (TVMaze title "TBA") must yield no title, so the
    filename stays Show.(Year).SxxExx.ext rather than baking in a fake title."""

    # season-based list mixing a real title with TVMaze placeholders
    EPS = [
        {"season": 3, "episode": 1, "title": "A Son Who Bleeds", "airdate": ""},
        {"season": 3, "episode": 2, "title": "TBA", "airdate": ""},
        {"season": 3, "episode": 3, "title": "  tbd ", "airdate": ""},
        {"season": 3, "episode": 4, "title": "To Be Announced", "airdate": ""},
    ]

    def _patch(self, monkeypatch) -> None:
        monkeypatch.setattr(tvmaze, "_ensure_show_episodes", lambda name, logger=None: self.EPS)

    def test_real_title_passes_through(self, monkeypatch) -> None:
        self._patch(monkeypatch)
        assert tvmaze.lookup_episode_name("House of the Dragon", 3, 1) == "A Son Who Bleeds"

    def test_tba_collapses_to_none(self, monkeypatch) -> None:
        self._patch(monkeypatch)
        assert tvmaze.lookup_episode_name("House of the Dragon", 3, 2) is None

    def test_tbd_with_whitespace_and_case_collapses(self, monkeypatch) -> None:
        self._patch(monkeypatch)
        assert tvmaze.lookup_episode_name("House of the Dragon", 3, 3) is None

    def test_to_be_announced_collapses(self, monkeypatch) -> None:
        self._patch(monkeypatch)
        assert tvmaze.lookup_episode_name("House of the Dragon", 3, 4) is None

    def test_real_title_helper_keeps_numbered_episode_titles(self) -> None:
        # "Episode 6" (British numbered shows) is a genuine title, not a placeholder.
        assert tvmaze._real_title("Episode 6") == "Episode 6"
        assert tvmaze._real_title("") is None
        assert tvmaze._real_title(None) is None
