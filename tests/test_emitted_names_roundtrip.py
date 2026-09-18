"""Every name CleanMedia writes must be readable by CleanMedia (CLEAN-11).

`tests/fixtures/emitted_names.json` is 3,195 real output names taken from the
`dst` fields of the undo journals on the media volume, covering 930 distinct
shows. Like the original-release corpus, these are real names off the disk, not
invented ones. The two suites answer different questions:

  test_original_release_names  - can we read what trackers deliver?
  this one                     - can we read what we ourselves wrote?

The second matters because a name we emit and cannot re-parse freezes that file
permanently: it can never be re-verified, re-titled, moved, or repaired by any
later fix, and it logs as SKIP (unparsed media) on every run forever. Eight
Horatio Hornblower files sat in exactly that state because the TVMaze renumber
wrote year-seasons (`S2001E01`) that `RE_SXXEYY` would only match to two digits.
"""
import json
import re
from pathlib import Path

import pytest

from src.service.clean_service import CleanService

FIXTURE = Path(__file__).parent / "fixtures" / "emitted_names.json"
FAKE_ROOT = Path("/volume/intake")


def _norm(v: str) -> str:
    return str(int(v))


# Names CleanMedia wrote in the past that it still cannot round-trip. Listed
# explicitly, with the reason, so the count cannot creep upward unnoticed. This
# is a record of existing damage, not a licence to add more.
KNOWN_BAD = {
    # Emitted with an EMPTY show name: only a year survived. The parser refuses
    # a year-only show (`_has_real_show_text`) rather than creating a "(2016)"
    # folder, which is right -- the bug was writing these at all.
    "(2016).S01E01.mkv", "(2016).S01E02.mkv",
    "(2016).S01E03.mkv", "(2016).S01E04.mkv",
    # A spurious SxxExx appended AFTER quality tags by an early renumber bug.
    # `_RE_TRAILING_SXXEXX` strips it and recovers the real episode from the
    # bare number, so the PARSE is correct and the NAME is the wrong half. They
    # are listed here because the literal name disagrees with the parse.
    "Horatio.Hornblower.03.The.Duchess.And.The.Devil.480P.H.S02E64.mp4",
    "Horatio.Hornblower.04.The.Wong.War.480P.H.S02E64.mp4",
    "Horatio.Hornblower.05.Mutiny.480P.H.S02E64.mp4",
    "Horatio.Hornblower.06.Retribution.H.S02E64.mp4",
    "Horatio.Hornblower.07.Loyalty.480P.H.S02E64.mp4",
    "Horatio.Hornblower.08.Duty.480P.H.S02E64.mp4",
    # Season-pack name: "Paradise.2025.Season.02.Complete..." parses to S01E02
    # instead of S02E01. A genuine mis-parse, tracked with the season-pack work.
    "Paradise.2025.Season.02.Complete.1080P.Web.Dl.H.S02E01.mkv",
    "Paradise.2025.Season.02.Complete.1080P.Web.Dl.H.S02E02.mkv",
    "Paradise.2025.Season.02.Complete.1080P.Web.Dl.H.S02E03.mkv",
    "Paradise.2025.Season.02.Complete.1080P.Web.Dl.H.S02E04.mkv",
}


@pytest.fixture(scope="module")
def corpus():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def failures(corpus):
    svc = CleanService()
    bad = []
    for parent, filename, season, episode in corpus:
        detail = svc._parse_detail(FAKE_ROOT / parent / filename)
        if detail is None:
            bad.append(("unparsed", filename))
        elif _norm(detail.season) != _norm(season) or _norm(detail.episode) != _norm(episode):
            bad.append((f"S{detail.season}E{detail.episode} vs S{season}E{episode}", filename))
    return bad


class TestCorpusIntegrity:
    def test_corpus_is_substantial(self, corpus):
        assert len(corpus) > 3000

    def test_every_entry_looks_like_our_own_output(self, corpus):
        shape = re.compile(r"^.+\.S\d{1,4}E\d{1,2}(\.|$)")
        assert all(shape.match(f) for _, f, _, _ in corpus)


class TestRoundTrip:
    def test_no_new_round_trip_failures(self, failures):
        unexpected = [(why, f) for why, f in failures if f not in KNOWN_BAD]
        assert not unexpected, (
            f"{len(unexpected)} name(s) CleanMedia wrote can no longer be read back: "
            f"{unexpected[:5]}"
        )

    def test_known_bad_list_has_not_grown(self, failures):
        assert len(failures) <= len(KNOWN_BAD), (
            f"round-trip failures rose to {len(failures)} "
            f"(known: {len(KNOWN_BAD)})"
        )

    def test_known_bad_entries_are_still_real(self, failures):
        """Prune the list when a fix lands, so it never rots into a lie."""
        still_failing = {f for _, f in failures}
        stale = KNOWN_BAD - still_failing
        assert not stale, (
            f"these now round-trip and must be removed from KNOWN_BAD: {sorted(stale)}"
        )


class TestYearSeasonsRoundTrip:
    """The CLEAN-11 case: year-seasons written by the TVMaze renumber."""

    @pytest.mark.parametrize("filename,season,episode", [
        ("C.S.Forester's.Horatio.Hornblower.(1998).S2001E01.Hornblower.Mutiny.mp4", "2001", "01"),
        ("C.S.Forester's.Horatio.Hornblower.(1998).S1998E01.Even.Chance.mp4", "1998", "01"),
        ("Show.Name.(1998).S2003E02.Title.mkv", "2003", "02"),
    ])
    def test_four_digit_season_parses(self, filename, season, episode):
        svc = CleanService()
        detail = svc._parse_detail(FAKE_ROOT / "Season 2001" / filename)
        assert detail is not None, f"{filename!r} did not parse"
        assert (detail.season, detail.episode) == (season, episode)

    def test_ordinary_two_digit_seasons_unaffected(self):
        svc = CleanService()
        detail = svc._parse_detail(FAKE_ROOT / "Season 05" / "Letterkenny.(2016).S05E01.Title.mkv")
        assert (detail.season, detail.episode) == ("05", "01")
