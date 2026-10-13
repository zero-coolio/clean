"""Tests for library-root vetting (CLEAN-18).

The real paths are used: seagate-movie and Summer/movie-archive are the two
libraries clean-movie now organizes, and /Volumes is the prefix that makes an
absent volume dangerous rather than merely empty.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.library_roots import check_root, resolve_roots

LOG = logging.getLogger("test")


def test_a_real_directory_passes(tmp_path):
    path, reason = check_root(tmp_path, LOG)
    assert reason is None
    assert path == tmp_path.resolve()


def test_a_missing_directory_is_refused(tmp_path):
    path, reason = check_root(tmp_path / "nope", LOG)
    assert path is None
    assert reason == "does not exist"


def test_a_file_is_not_a_library(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"")
    path, reason = check_root(f, LOG)
    assert path is None
    assert "not a directory" in reason


def test_a_root_on_an_unmounted_volume_is_refused(tmp_path, monkeypatch):
    """The macOS footgun. /Volumes/<name> is an ordinary boot-disk directory
    that the mounter creates and removes, so a leftover one is writable, on the
    wrong disk, and looks like a library that lost every file."""
    fake = tmp_path / "Volumes"
    (fake / "Summer" / "movie-archive").mkdir(parents=True)
    monkeypatch.setattr("src.library_roots._MOUNT_PREFIX", fake)
    monkeypatch.setattr("src.library_roots.os.path.ismount", lambda p: False)

    path, reason = check_root(fake / "Summer" / "movie-archive", LOG)
    assert path is None
    assert "not a mounted volume" in reason


def test_a_root_on_a_mounted_volume_passes(tmp_path, monkeypatch):
    fake = tmp_path / "Volumes"
    archive = fake / "Summer" / "movie-archive"
    archive.mkdir(parents=True)
    monkeypatch.setattr("src.library_roots._MOUNT_PREFIX", fake)
    monkeypatch.setattr("src.library_roots.os.path.ismount", lambda p: True)

    path, reason = check_root(archive, LOG)
    assert reason is None
    assert path == archive.resolve()


def test_a_path_outside_volumes_is_not_mount_checked(tmp_path, monkeypatch):
    def explode(p):
        raise AssertionError("ismount called for a non-/Volumes path")

    monkeypatch.setattr("src.library_roots.os.path.ismount", explode)
    path, reason = check_root(tmp_path, LOG)
    assert reason is None


def test_one_bad_root_does_not_stop_the_other(tmp_path):
    """An unplugged archive must not stop seagate-movie being tidied."""
    good = tmp_path / "seagate-movie"
    good.mkdir()
    roots = resolve_roots([good, tmp_path / "movie-archive"], LOG)
    assert roots == [good.resolve()]


def test_the_same_library_named_twice_is_groomed_once(tmp_path):
    good = tmp_path / "seagate-movie"
    good.mkdir()
    link = tmp_path / "by-another-name"
    link.symlink_to(good)
    assert resolve_roots([good, link, good], LOG) == [good.resolve()]


def test_every_root_bad_returns_empty_so_the_caller_can_refuse(tmp_path):
    assert resolve_roots([tmp_path / "a", tmp_path / "b"], LOG) == []


def test_order_is_preserved(tmp_path):
    first, second = tmp_path / "seagate-movie", tmp_path / "movie-archive"
    first.mkdir()
    second.mkdir()
    assert resolve_roots([first, second], LOG) == [first.resolve(), second.resolve()]
