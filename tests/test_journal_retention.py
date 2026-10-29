"""Undo-journal retention: keep 3 days, Trash the rest (2026-10-28)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest
import send2trash as send2trash_module

from src.journal_retention import expired_journals, journal_stamp, prune_journals
from src.PruneJournals import main as prune_main

NOW = datetime(2026, 10, 28, 20, 0, 0)
LOG = logging.getLogger("test-retention")


def name(service: str, stamp: str) -> str:
    return f".{service}-journal-{stamp}.jsonl"


class TestExpiredJournals:
    def test_keeps_inside_window_and_expires_outside(self) -> None:
        names = [
            name("clean-tv", "20261028-195900"),  # a minute old
            name("clean-tv", "20261025-200001"),  # just inside 3 days
            name("clean-tv", "20261025-195959"),  # just outside
            name("clean-tv", "20260310-130854"),  # months old
        ]
        assert expired_journals(names, ["clean-tv"], NOW, 3) == sorted(names[2:])

    def test_only_named_services_and_real_journals(self) -> None:
        names = [
            name("clean-movie", "20260101-000000"),
            ".rename-fix-reversal-20260101-000000.jsonl",
            name("clean-tv", "20261399-000000"),          # malformed date
            "Show.S01E01.mkv",
            ".clean-tv-journal-20260101-000000.jsonl.bak",
            ".DS_Store",
        ]
        assert expired_journals(names, ["clean-tv"], NOW, 3) == []
        assert expired_journals(names, ["clean-tv", "clean-movie"], NOW, 3) == [names[0]]

    def test_zero_days_means_off(self) -> None:
        assert expired_journals([name("clean-tv", "20200101-000000")], ["clean-tv"], NOW, 0) == []

    def test_stamp_reads_the_name_not_the_mtime(self) -> None:
        assert journal_stamp(name("clean-tv", "20261028-200550"), ["clean-tv"]) == datetime(2026, 10, 28, 20, 5, 50)
        assert journal_stamp(name("clean-tv", "20261028-200550"), ["clean-movie"]) is None


@pytest.fixture
def trash_calls(monkeypatch) -> list[str]:
    """Record send2trash calls instead of filling the real Trash."""
    calls: list[str] = []

    def fake(path: str) -> None:
        calls.append(Path(path).name)
        Path(path).unlink()

    monkeypatch.setattr(send2trash_module, "send2trash", fake)
    return calls


def make(root: Path, *names: str) -> None:
    for n in names:
        (root / n).write_text("")


class TestPruneJournals:
    def test_dry_run_touches_nothing(self, tmp_path: Path, trash_calls) -> None:
        old = name("clean-tv", "20260101-000000")
        make(tmp_path, old)
        out = prune_journals(tmp_path, ["clean-tv"], 3, commit=False, logger=LOG, now=NOW)
        assert [p.name for p in out] == [old]
        assert trash_calls == [] and (tmp_path / old).exists()

    def test_commit_trashes_only_expired(self, tmp_path: Path, trash_calls) -> None:
        old, new = name("clean-tv", "20260101-000000"), name("clean-tv", "20261028-100000")
        other = name("clean-movie", "20260101-000000")
        make(tmp_path, old, new, other, "keep.mkv")
        (tmp_path / "Show (2020)").mkdir()
        make(tmp_path / "Show (2020)", name("clean-tv", "20200101-000000"))  # not top level
        prune_journals(tmp_path, ["clean-tv"], 3, commit=True, logger=LOG, now=NOW)
        assert trash_calls == [old]
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([new, other, "keep.mkv", "Show (2020)"])

    def test_one_failure_does_not_stop_the_rest(self, tmp_path: Path, monkeypatch) -> None:
        a, b = name("clean-tv", "20260101-000000"), name("clean-tv", "20260102-000000")
        make(tmp_path, a, b)

        def flaky(path: str) -> None:
            if Path(path).name == a:
                raise OSError("busy")
            Path(path).unlink()

        monkeypatch.setattr(send2trash_module, "send2trash", flaky)
        out = prune_journals(tmp_path, ["clean-tv"], 3, commit=True, logger=LOG, now=NOW)
        assert [p.name for p in out] == [b] and (tmp_path / a).exists()

    def test_missing_root_is_a_warning_not_a_crash(self, tmp_path: Path) -> None:
        assert prune_journals(tmp_path / "nope", ["clean-tv"], 3, commit=True, logger=LOG, now=NOW) == []


class TestRunPrunes:
    @pytest.fixture(autouse=True)
    def _keep_root(self, monkeypatch) -> None:
        # A root holding only hidden journals counts as "empty" and the run's
        # cleanup would remove the temp root itself; real roots hold media.
        import src.service.base as base
        monkeypatch.setattr(base, "cleanup_empty_dirs", lambda *a, **k: None)

    def test_committed_run_trashes_its_own_old_journals(self, tmp_path: Path, trash_calls) -> None:
        from src.service.clean_service import CleanService

        old_tv, old_movie = name("clean-tv", "20200101-000000"), name("clean-movie", "20200101-000000")
        make(tmp_path, old_tv, old_movie)
        CleanService().run(root=tmp_path, commit=True, quarantine=None)
        assert trash_calls == [old_tv]
        left = sorted(p.name for p in tmp_path.glob(".clean-*-journal-*.jsonl"))
        assert old_movie in left and len(left) == 2, "movie journal kept, this run's journal written"

    def test_dry_run_never_prunes(self, tmp_path: Path, trash_calls) -> None:
        from src.service.clean_service import CleanService

        make(tmp_path, name("clean-tv", "20200101-000000"))
        CleanService().run(root=tmp_path, commit=False, plan=True, quarantine=None)
        assert trash_calls == []


class TestCli:
    def test_cli_dry_run_default_and_commit(self, tmp_path: Path, trash_calls) -> None:
        tv, movie = name("clean-tv", "20200101-000000"), name("clean-movie", "20200101-000000")
        make(tmp_path, tv, movie)
        assert prune_main(["-d", str(tmp_path)]) == 0
        assert trash_calls == []
        assert prune_main(["-d", str(tmp_path), "--commit"]) == 0
        assert sorted(trash_calls) == sorted([tv, movie])

    def test_cli_rejects_zero_days(self, tmp_path: Path) -> None:
        assert prune_main(["-d", str(tmp_path), "--days", "0", "--commit"]) == 2
