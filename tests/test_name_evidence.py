"""Tests for the name-evidence ladder (CLEAN-13).

Every name here is real. The stuck file and its container tag are read off
seagate-movie; the torrent name is a `src` from an undo journal. Per CLAUDE.md,
invented names encode what we already believe the format is, which is the
assumption under test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import src.name_evidence as ne
from src.name_evidence import candidate_names
from src.service.clean_movie_service import parse_movie_from_string

# The file that started CLEAN-13, exactly as it sits on the volume.
STUCK = Path(
    "/Volumes/Seagate/seagate-movie/Eater's Guide to the World (2020)/"
    "Dr Who Joy To The World.mkv"
)
# Its real Matroska tag, read with ffprobe.
STUCK_TAG = "Doctor.Who.Joy.to.the.World.2024.1080p.WEBRip.x264.Dual YG"
# A real torrent name, from .clean-tv-journal-*.jsonl.
REAL_TORRENT = (
    "www.UIndex.org    -    Doctor Who 2023 S02E05 The Story and the Engine "
    "1080p DSNP WEB-DL DDP5 1 H 264-Kitsune"
)


@pytest.fixture
def no_probe(monkeypatch):
    """Default to no container tag, so each test opts in to the rung it means."""
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: None)


def test_filename_is_always_first(no_probe):
    assert candidate_names(STUCK)[0] == "Dr Who Joy To The World"


def test_filename_only_is_still_a_list(no_probe):
    assert candidate_names(STUCK) == ["Dr Who Joy To The World"]


def test_container_tag_supplies_the_year_the_filename_lost(monkeypatch):
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: STUCK_TAG)
    names = candidate_names(STUCK)

    assert parse_movie_from_string(names[0]) is None
    assert parse_movie_from_string(names[1]) == ("Doctor Who Joy To The World", "2024")


def test_human_correction_outranks_the_tag(monkeypatch):
    """A renamed file is someone correcting us. Their name is tried first."""
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: STUCK_TAG)
    assert candidate_names(STUCK)[0] == "Dr Who Joy To The World"


def test_torrent_name_is_the_last_rung(monkeypatch):
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: STUCK_TAG)
    names = candidate_names(STUCK, torrent_name=REAL_TORRENT)
    assert names == ["Dr Who Joy To The World", STUCK_TAG, REAL_TORRENT]


def test_identical_rungs_are_parsed_once(monkeypatch):
    """A tag that merely restates the filename adds no evidence."""
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: "dr.who.joy.to.the.world")
    assert candidate_names(STUCK) == ["Dr Who Joy To The World"]


def test_the_containing_folder_is_never_a_candidate(monkeypatch):
    """The folder is refused upstream by CLEAN-2. Re-admitting it here would
    route around that guard and reinstate the rename it exists to stop."""
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: STUCK_TAG)
    names = candidate_names(STUCK, torrent_name=REAL_TORRENT)
    assert not any("Eater" in n for n in names)


def test_a_subtitle_is_not_probed(monkeypatch):
    def explode(p, log=None):
        raise AssertionError("ffprobe called on a non-video file")

    monkeypatch.setattr(ne, "container_title", explode)
    srt = STUCK.with_suffix(".srt")
    assert candidate_names(srt) == ["Dr Who Joy To The World"]


def test_probe_can_be_turned_off(monkeypatch):
    def explode(p, log=None):
        raise AssertionError("probed despite probe=False")

    monkeypatch.setattr(ne, "container_title", explode)
    assert candidate_names(STUCK, probe=False) == ["Dr Who Joy To The World"]


def test_blank_rungs_are_dropped(monkeypatch):
    monkeypatch.setattr(ne, "container_title", lambda p, log=None: "   ")
    assert candidate_names(STUCK, torrent_name="") == ["Dr Who Joy To The World"]
