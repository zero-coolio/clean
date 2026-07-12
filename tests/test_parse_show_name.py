"""Regression tests for the empty/year-only show-name bug.

When an episode filename STARTS with SxxExx (the show name lives only in the
parent folder), the parser used to emit a show name of just "(2016)" and file
episodes under a bogus "(2016)" folder. _parse_detail must instead keep the
filename's season/episode and borrow the show name from the parent.
"""
from pathlib import Path

import pytest

from src.service.clean_service import CleanService, _has_real_show_text


# --------------------------------------------------------------------------- #
# _has_real_show_text
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("show,expected", [
    ("Bull", True),
    ("Bull (2016)", True),
    ("(2016)", False),
    (" (2016)", False),
    ("2016", False),
    ("", False),
    ("   ", False),
    ("1883", True),      # 18xx not treated as a release year -> real name
    ("9-1-1", True),
    ("24", True),        # two digits, not a 4-digit year
])
def test_has_real_show_text(show, expected):
    assert _has_real_show_text(show) is expected


# --------------------------------------------------------------------------- #
# _parse_detail — the Bull season pack
# --------------------------------------------------------------------------- #

def test_episode_starting_with_sxxexx_borrows_show_name_from_parent():
    svc = CleanService()
    parent = "Bull - S01 E01-23 (2017) WEBRip 1080p HEVC EAC3 ITA ENG SUB ITA ENG - Lullozzo"
    fname = "S01E08 Bull Troppo Perfetta (2016) WEBRip 1080p HEVC EAC3 ITA ENG SUB ITA ENG - Lullozzo.mkv"
    d = svc._parse_detail(Path(f"/v/seagate-qBittorrent/{parent}/{fname}"))
    assert d is not None
    # Per-file episode number is preserved from the FILENAME (not the parent's E01).
    assert (d.season, d.episode) == ("01", "08")
    # Show name is borrowed from the parent — never the bogus year-only "(2016)".
    assert _has_real_show_text(d.show)
    assert "Bull" in d.show
    assert d.show.strip() != "(2016)"


def test_each_episode_keeps_its_own_number():
    # The whole point: a season pack must not collapse every file onto E01.
    svc = CleanService()
    parent = "Bull - S01 E01-23 (2017) WEBRip - Lullozzo"
    seen = set()
    for ep in ("01", "05", "08", "23"):
        fname = f"S01E{ep} Bull Something (2016) WEBRip - Lullozzo.mkv"
        d = svc._parse_detail(Path(f"/v/{parent}/{fname}"))
        assert d is not None and d.season == "01"
        seen.add(d.episode)
    assert seen == {"01", "05", "08", "23"}


def test_normal_filename_with_name_is_unchanged():
    svc = CleanService()
    d = svc._parse_detail(Path("/v/Bull (2016)/Season 01/Bull.(2016).S01E08.mkv"))
    assert d is not None
    assert (d.season, d.episode) == ("01", "08")
    assert "Bull" in d.show


def test_year_only_with_no_usable_parent_is_skipped():
    # Filename is year-only AND the parent can't supply a name -> skip (None),
    # so we never create a "(2016)" folder.
    svc = CleanService()
    d = svc._parse_detail(Path("/v/(2016)/Season 01/S01E08 (2016).mkv"))
    assert d is None
