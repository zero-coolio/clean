"""Unit tests for filename-over-folder identity.

Every case is drawn from the real libraries, because the cost of getting this
wrong is asymmetric: a wrong refusal costs a log line, a wrong acceptance
renames a file and destroys the only evidence of what it was.
"""
import os
import time
from pathlib import Path

import pytest

from src.title_signal import (
    FALLBACK_OVERLAP_THRESHOLD,
    describe_mismatch,
    folder_may_name_file,
    meaningful_tokens,
)


# --- tokenizing -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Ad.Astra.2019.1080p.BluRay.x264-GROUP", {"ad", "astra"}),
    ("Ad Astra (2019)", {"ad", "astra"}),
    # Lowercase trailing words are title, not a release group. An any-case
    # pattern ate "rabbit" here on the first attempt.
    ("the curse of the were-rabbit", {"curse", "rabbit", "were"}),
    # Quality markers, the release group and both language tags all drop out.
    ("The.End.of.Oak.Street.2160p.HDR.ITA-ENG.MULTI.WEBRip.x265.AAC-V3SP4EV3R",
     {"end", "oak", "street"}),
    # "TS" is a quality marker; unanchored it ate this down to {"v"}, and would
    # reduce "Ghosts" to "Ghos".
    ("Ghosts", {"ghosts"}),
    ("The.Ghosts.2019.HDTV.x264", {"ghosts"}),
    # Claims nothing: generic payload names, language tags, bare numbers.
    ("movie", set()),
    ("2_English", set()),
    ("cd2", set()),
    ("VTS_01_1", set()),
    # Stopwords carry no identity and would otherwise inflate every overlap.
    ("The Guide to the World", {"guide", "world"}),
])
def test_meaningful_tokens(text, expected):
    assert meaningful_tokens(text) == expected


# --- the two real failures --------------------------------------------------

@pytest.mark.parametrize("stem,folder", [
    # A Doctor Who special parked in a Netflix food show's folder. A full run
    # would have renamed it to "Eater'S Guide To The World (2020).mkv".
    ("Dr Who Joy To The World", "Eater's Guide to the World (2020)"),
    # A Wallace & Gromit film parked in a Japanese drama's folder.
    ("the curse of the were-rabbit", "Nanyobi ni umareta no (2023)"),
])
def test_folder_may_not_rename_a_different_film(stem, folder):
    assert folder_may_name_file(stem, folder) is False
    # The refusal must say why, naming both claims.
    reason = describe_mismatch(stem, folder)
    assert "filename claims" in reason and "folder claims" in reason


@pytest.mark.parametrize("stem,folder", [
    # Filename claims no identity, so the folder is the only signal there is.
    ("movie", "Ad.Astra.2019.1080p.BluRay-GROUP"),
    ("2_English", "Ad Astra (2019)"),
    ("VTS_01_1", "Ad.Astra.2019.BluRay-GROUP"),
    # Filename agrees with the folder.
    ("Ad.Astra", "Ad.Astra.2019.1080p.BluRay.x264-GROUP"),
    ("Ad Astra (2019)", "Ad Astra (2019)"),
    ("Ad.Astra.2019.1080p", "Ad.Astra.2019.2160p.REMUX-OTHER"),
])
def test_folder_may_name_file_when_nothing_contradicts_it(stem, folder):
    assert folder_may_name_file(stem, folder) is True


def test_library_root_is_treated_like_any_other_disagreeing_folder():
    """A loose file at the library root compares against the root's own name and
    is refused. Harmless, since a root like "seagate-movie" has no year, so it never
    parses as a movie and the fallback is never reached, but asserted so the
    behaviour is recorded rather than assumed."""
    assert folder_may_name_file("Dr Who Joy To The World", "seagate-movie") is False


def test_threshold_is_a_ratio_of_the_filename_not_the_folder():
    """Half the filename's words must be vouched for by the folder. Anchored so
    a future tweak to the constant cannot silently re-admit the two cases above."""
    assert FALLBACK_OVERLAP_THRESHOLD == 0.5
    # 1 of 2 shared: exactly at the threshold, accepted.
    assert folder_may_name_file("Oak Street", "Oak Meadow (2001)") is True
    # 1 of 3 shared: below, refused.
    assert folder_may_name_file("Oak Street Blues", "Oak Meadow (2001)") is False


# --- service wiring ---------------------------------------------------------

from src.service.clean_movie_service import CleanMovieService  # noqa: E402
from src.service.clean_service import CleanService  # noqa: E402


def test_movie_service_refuses_a_contradicting_folder():
    svc = CleanMovieService()
    p = Path("/lib/Eater's Guide to the World (2020)/Dr Who Joy To The World.mkv")
    assert svc._folder_fallback_allowed(p, p.parent.name) is False


def test_movie_service_allows_an_agreeing_folder():
    svc = CleanMovieService()
    p = Path("/lib/Ad.Astra.2019.1080p.BluRay-GROUP/movie.mkv")
    assert svc._folder_fallback_allowed(p, p.parent.name) is True


def test_tv_service_still_trusts_its_folders():
    """TV must NOT inherit this. An episode title legitimately shares nothing
    with the show name, so the comparison would reject correct fallbacks
    wholesale, which is why the hook defaults to permissive and only the movie
    service overrides it."""
    svc = CleanService()
    p = Path("/lib/Reacher (2022)/Season 04/Reacher.S04E01.City.of.Brotherly.Love.mkv")
    assert svc._folder_fallback_allowed(p, "Reacher (2022)") is True
    # The bare comparison would have refused it, which is the point.
    assert folder_may_name_file(p.stem, "Reacher (2022)") is False


def test_end_to_end_misfiled_movie_is_left_alone(tmp_path, monkeypatch):
    """The whole point, through run(): the file keeps its name and is reported."""
    root = tmp_path / "movies"
    misfiled = root / "Eater's Guide to the World (2020)" / "Dr Who Joy To The World.mkv"
    misfiled.parent.mkdir(parents=True)
    misfiled.write_text("DATA")
    placed = root / "Ad Astra (2019)" / "Ad Astra (2019).mkv"
    placed.parent.mkdir(parents=True)
    placed.write_text("DATA")

    svc = CleanMovieService()
    monkeypatch.setattr(svc, "_process_audio_tracks", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_report_large_files", lambda *a, **k: None, raising=False)
    svc.run(root=root, commit=True, structural=True)

    assert misfiled.exists(), "a misfiled film must not be renamed to its neighbour"
    assert not (misfiled.parent / "Eater'S Guide To The World (2020).mkv").exists()
    assert placed.exists(), "a correctly placed film must be left alone"
