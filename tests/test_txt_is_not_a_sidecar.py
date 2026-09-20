"""A .txt file must never become a show (CLEAN-16).

A sidecar is parsed, show-matched and filed exactly like an episode, so it can
create a show folder with no media anywhere near it. Uploaders plant advertising
.txt files inside release folders; one advertising Rosewood was filed as
"Club Friday The Series - Unhappy Birthday (2021) S01E01 Episode 1".

Every .txt on the media volume (56 of them) contained a magnet link and none sat
beside media with a matching stem, so the extension only ever cost phantom shows.
"""
from pathlib import Path

import pytest

from src.config import MOVIE_DELETE_EXT, TV_SIDECAR_EXT
from src.service.clean_service import CleanService


class TestSidecarSet:
    def test_txt_is_not_a_tv_sidecar(self):
        assert ".txt" not in TV_SIDECAR_EXT

    def test_real_sidecars_are_kept(self):
        """Subtitles and .nfo genuinely accompany media and must still file."""
        assert ".nfo" in TV_SIDECAR_EXT
        assert ".srt" in TV_SIDECAR_EXT

    def test_movie_path_still_deletes_txt(self):
        """The movie side always treated .txt as release junk; unchanged."""
        assert ".txt" in MOVIE_DELETE_EXT


class TestServiceDoesNotFileText:
    def test_txt_not_in_service_sidecar_extensions(self):
        assert ".txt" not in CleanService().get_sidecar_extensions()

    def test_spam_txt_is_not_processed(self, tmp_path: Path, monkeypatch):
        """The exact file that became a show must now be left alone."""
        monkeypatch.setattr("src.tvmaze.lookup_show", lambda name, logger=None: None)
        monkeypatch.setattr(
            "src.tvmaze.lookup_episode_name",
            lambda name, season, episode, logger=None: None,
        )
        root = tmp_path / "intake"
        wrapper = root / "BULL - Complete Season 3 S03 (2018-2019) - 720p AMZN Web-DL x264"
        spam_dir = wrapper / "Shows with RELATED Themes, HERE"
        spam_dir.mkdir(parents=True)
        spam = spam_dir / "ROSEWOOD (2005-2017) - Complete TV Series, Seasons 01-02 - 720p Web-DL x264.txt"
        spam.write_text("magnet:?xt=urn:btih:deadbeef", encoding="utf-8")

        CleanService().run(root=root, commit=True, quarantine=None)

        # No show folder may have been invented for a text file.
        created = [p.name for p in root.iterdir() if p.is_dir() and p != wrapper]
        assert created == [], f"a .txt created show folder(s): {created}"
        assert not list(root.rglob("Season 01")), "a .txt created a Season folder"
