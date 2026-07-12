"""Regression tests for set_track_defaults' mkvpropedit selectors.

The original code selected tracks with `track:@<id>`, which means "track whose
UID equals <id>". mkvmerge's positional `id` (0,1,2…) never matches a real UID,
so mkvpropedit silently edited nothing while still exiting 0 — the audio-default
feature was a no-op even with mkvtoolnix installed. The fix uses type-relative
selectors (track:a1 = first audio track, track:s1 = first subtitle).
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import audio_tracks


def _track(tid, ttype, lang, default, forced=False, name=""):
    return {
        "id": tid,
        "type": ttype,
        "properties": {
            "language": lang,
            "default_track": default,
            "number": tid + 1,
            "forced_track": forced,
            "track_name": name,
        },
    }


def _run_set_defaults(tracks):
    """Run set_track_defaults with mkvmerge/mkvpropedit mocked; return (changed, cmd)."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        return m

    with patch.object(audio_tracks, "get_track_info", return_value={"tracks": tracks}), \
         patch.object(audio_tracks.subprocess, "run", side_effect=fake_run):
        changed = audio_tracks.set_track_defaults(
            Path("/x/foo.mkv"), logging.getLogger("test"), commit=True
        )
    return changed, captured.get("cmd", [])


def test_english_audio_made_default_with_type_relative_selector():
    # ita audio (1st) is default; eng audio (2nd) is not — the Bull case.
    tracks = [
        _track(0, "video", "und", False),
        _track(1, "audio", "ita", True),
        _track(2, "audio", "eng", False),
    ]
    changed, cmd = _run_set_defaults(tracks)
    assert changed is True
    joined = " ".join(cmd)
    # NEVER the broken UID selector
    assert "track:@" not in joined
    # eng is the 2nd audio track -> track:a2 set default; ita (a1) unset
    assert "track:a2" in cmd and "track:a1" in cmd
    i = cmd.index("track:a2")
    assert cmd[i - 1] == "--edit" and cmd[i + 1] == "--set" and cmd[i + 2] == "flag-default=1"
    j = cmd.index("track:a1")
    assert cmd[j + 2] == "flag-default=0"


def test_default_english_audio_is_left_alone():
    # eng audio already default -> no changes needed.
    tracks = [
        _track(0, "video", "und", False),
        _track(1, "audio", "eng", True),
        _track(2, "audio", "ita", False),
    ]
    changed, cmd = _run_set_defaults(tracks)
    assert changed is False and cmd == []


def test_nonforced_default_subtitle_disabled_with_s_selector():
    # eng audio default already; a non-forced eng subtitle is default -> disable it.
    tracks = [
        _track(0, "video", "und", False),
        _track(1, "audio", "eng", True),
        _track(2, "subtitles", "eng", True, forced=False),
    ]
    changed, cmd = _run_set_defaults(tracks)
    assert changed is True
    assert "track:s1" in cmd and "track:@" not in " ".join(cmd)
    i = cmd.index("track:s1")
    assert cmd[i + 2] == "flag-default=0"
