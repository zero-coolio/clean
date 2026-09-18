"""Parse real original release names, not CleanMedia's own output.

`tests/fixtures/original_release_names.json` is sampled from the undo journals
on the media volume, where each move records the source path as the tracker
actually delivered it. Post-clean names were excluded when building it: feeding
the parser a name it produced itself proves nothing about the job it has to do.

1,571 entries covering 1,009 distinct release folders, so the corpus spans many
naming conventions rather than one show repeated.

The invariant that matters here is NOT "everything parses". Bonus features,
featurettes and extras have no episode identity and should be skipped. What must
never happen is a name parsing to a SHOW that carries release noise: that is how
22 Gotham episodes ended up filed under "[Torrentcouch Com] Gotham" (CLEAN-10)
and a 2019 drama under "Wonder Woman (1975)" (CLEAN-7). A junk show name is
silent: the files land in a plausible-looking folder and every later run treats
them as already placed.
"""
import json
import re
from pathlib import Path

import pytest

from src.service.clean_service import CleanService, _has_real_show_text

FIXTURE = Path(__file__).parent / "fixtures" / "original_release_names.json"
FAKE_ROOT = Path("/volume/intake")

# Anything that is release metadata rather than part of a programme's title.
SHOW_NOISE = re.compile(
    r"(?i)(\[|\]|www\.|\.com\b|\.org\b|\b\d{3,4}p\b|x26[45]|hevc|web[-. ]?dl"
    r"|webrip|hdtv|bluray|bdrip|brrip|dvdrip|amzn|hulu|ddp?\d|aac\d?|ac3|dts"
    r"|repack|proper|internal|remux|complete|season \d|s\d{2}e\d{2})"
)

# Pinned just under the measured rate (98.2% at the time of writing) so a real
# regression fails the build. A loose floor here is worthless: the point is to
# catch the parser going backwards, not to be easy to satisfy. Raise it if the
# parser improves; never quietly lower it to make a failure go away.
MIN_PARSE_RATE = 0.97


@pytest.fixture(scope="module")
def corpus() -> list[tuple[str, str]]:
    return [tuple(row) for row in json.loads(FIXTURE.read_text())]


@pytest.fixture(scope="module")
def parsed(corpus):
    svc = CleanService()
    out = []
    for parent, filename in corpus:
        detail = svc._parse_detail(FAKE_ROOT / parent / filename)
        out.append((parent, filename, detail))
    return out


class TestCorpusIntegrity:
    def test_fixture_is_present_and_substantial(self, corpus):
        assert len(corpus) > 1000, "corpus shrank; was it rebuilt from fewer journals?"

    def test_fixture_holds_no_post_clean_names(self, corpus):
        """Guard the corpus itself: these must be tracker names, not our output."""
        cleaned = re.compile(r"^.+\.\((?:19|20)\d{2}\)\.S\d{2}E\d{2}(\.|$)")
        offenders = [f for p, f in corpus if re.match(r"^Season \d{2}$", p) and cleaned.match(f)]
        assert not offenders, f"post-clean names leaked into the corpus: {offenders[:5]}"


class TestNoJunkShowNames:
    """The load-bearing assertion. A wrong show name is a silent mis-file."""

    def test_no_show_name_carries_release_noise(self, parsed):
        offenders = [
            (detail.show, filename)
            for _, filename, detail in parsed
            if detail is not None and SHOW_NOISE.search(detail.show)
        ]
        assert not offenders, (
            f"{len(offenders)} release names parsed to a noisy show name, "
            f"e.g. {offenders[:5]}"
        )

    def test_no_show_name_is_empty_or_year_only(self, parsed):
        offenders = [
            (detail.show, filename)
            for _, filename, detail in parsed
            if detail is not None and not _has_real_show_text(detail.show)
        ]
        assert not offenders, f"show names with no real text: {offenders[:5]}"


class TestParseRateDoesNotRegress:
    def test_most_real_releases_parse(self, parsed):
        ok = sum(1 for _, _, d in parsed if d is not None)
        rate = ok / len(parsed)
        assert rate >= MIN_PARSE_RATE, (
            f"parse rate fell to {rate:.1%} (floor {MIN_PARSE_RATE:.0%}); "
            "a parser change has made real releases unreadable"
        )


class TestKnownRegressions:
    """Specific names that caused real damage, kept as named cases."""

    @pytest.mark.parametrize("parent,filename,expected_show", [
        # CLEAN-10: tracker prefix became the show name, stranding Gotham S4.
        ("[Torrentcouch Com] Gotham", "[Torrentcouch.Com].Gotham.S04E19.mp4", "Gotham"),
        ("Season 04", "[Torrentcouch.Com].Gotham.S04E01.mp4", "Gotham"),
        # CLEAN-7: an explicit year must survive parsing.
        ("Wonder Women", "Wonder Women S01E02 2019 1080p Hami WEB-DL H264 AAC.mkv",
         "Wonder Women (2019)"),
        # Ordinary scene names must keep working.
        ("Neagley.S01.1080p.HEVC.x265-MeGusta",
         "Neagley.S01E03.1080p.HEVC.x265-MeGusta.mkv", "Neagley"),
    ])
    def test_show_name(self, parent, filename, expected_show):
        svc = CleanService()
        detail = svc._parse_detail(FAKE_ROOT / parent / filename)
        assert detail is not None, f"{filename!r} did not parse at all"
        assert detail.show == expected_show
