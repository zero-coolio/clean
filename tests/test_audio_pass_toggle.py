"""The audio/subtitle track pass is gated by config.AUDIO_TRACKS_ENABLED.

Disabled 2026-08-22 (Plex handles English audio; the subtitle half never worked).
These pin BOTH directions so the flag can be trusted to actually turn the pass
off — and so re-enabling it is a one-line change that stays covered.
"""
from pathlib import Path

import pytest

from src.service.clean_service import CleanService


@pytest.fixture
def spy(monkeypatch):
    """Record whether the per-file track work was reached."""
    calls: list[Path] = []
    monkeypatch.setattr(
        "src.service.base.set_track_defaults",
        lambda path, logger, commit: calls.append(path) or False,
    )
    # Pretend mkvtoolnix is present so the flag is the only thing under test.
    monkeypatch.setattr("src.service.base.check_mkvtoolnix_installed", lambda: True)
    return calls


def _library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    (root / "Show (2020)" / "Season 01").mkdir(parents=True)
    (root / "Show (2020)" / "Season 01" / "Show.S01E01.mkv").write_text("DATA")
    return root


def test_disabled_by_default_skips_the_pass(tmp_path, spy, monkeypatch):
    monkeypatch.setattr("src.config.AUDIO_TRACKS_ENABLED", False, raising=False)
    CleanService()._process_audio_tracks(_library(tmp_path), commit=False)
    assert spy == []


def test_enabled_flag_runs_the_pass(tmp_path, spy, monkeypatch):
    monkeypatch.setattr("src.config.AUDIO_TRACKS_ENABLED", True, raising=False)
    CleanService()._process_audio_tracks(_library(tmp_path), commit=False)
    assert [p.name for p in spy] == ["Show.S01E01.mkv"]


def test_flag_is_read_at_call_time_not_import_time(tmp_path, spy, monkeypatch):
    """Guards the function-local import — a module-level `from ..config import`
    would bind once and make the flag unflippable."""
    root = _library(tmp_path)
    service = CleanService()

    monkeypatch.setattr("src.config.AUDIO_TRACKS_ENABLED", False, raising=False)
    service._process_audio_tracks(root, commit=False)
    assert spy == []

    monkeypatch.setattr("src.config.AUDIO_TRACKS_ENABLED", True, raising=False)
    service._process_audio_tracks(root, commit=False)
    assert len(spy) == 1


def test_default_ships_disabled():
    """The shipped default is OFF — if someone flips it, this test says so."""
    import src.config as config
    assert config.AUDIO_TRACKS_ENABLED is False
