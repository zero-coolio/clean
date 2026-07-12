#!/usr/bin/env python3
"""Tests for same_content — the duplicate guard on the delete path.

same_content gates a near-irreversible deletion (the caller trashes the source
when it returns True), so the critical property is NO FALSE POSITIVES: two
different files that merely share a size and a header must never be reported as
duplicates. The previous 1 MB-only hash could not distinguish them.
"""
import pytest

from src.utils import same_content


def _write(path, data: bytes):
    path.write_bytes(data)
    return path


def test_identical_files_are_duplicates(tmp_path):
    a = _write(tmp_path / "a.mkv", b"the quick brown fox" * 100000)
    b = _write(tmp_path / "b.mkv", b"the quick brown fox" * 100000)
    assert same_content(a, b) is True


def test_different_size_is_not_duplicate(tmp_path):
    a = _write(tmp_path / "a.mkv", b"x" * 1000)
    b = _write(tmp_path / "b.mkv", b"x" * 1001)
    assert same_content(a, b) is False


def test_same_size_matching_header_but_differing_tail_is_not_duplicate(tmp_path):
    """The exact false-dedup case the old 1 MB-prefix hash could not catch.

    Both files share an identical 2 MB header and the same total size; they
    differ only in the final bytes — like two episodes from one encoder.
    """
    header = b"\x00\xff" * (1024 * 1024)  # 2 MB identical prefix (> old 1 MB window)
    a = _write(tmp_path / "a.mkv", header + b"AAAA")
    b = _write(tmp_path / "b.mkv", header + b"BBBB")
    assert a.stat().st_size == b.stat().st_size  # same size
    assert same_content(a, b) is False  # must NOT be deleted as a duplicate


def test_missing_file_is_not_duplicate(tmp_path):
    a = _write(tmp_path / "a.mkv", b"data")
    missing = tmp_path / "gone.mkv"
    assert same_content(a, missing) is False


def test_empty_files_are_duplicates(tmp_path):
    a = _write(tmp_path / "a.mkv", b"")
    b = _write(tmp_path / "b.mkv", b"")
    assert same_content(a, b) is True
