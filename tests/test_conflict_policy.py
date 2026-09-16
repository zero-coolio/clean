"""Tests for the same-destination conflict rule.

This is the rule that decides which file gets deleted, so it is tested
exhaustively and without a filesystem.
"""
import pytest

from src.conflict_policy import Candidate, choose_winner


def c(height=None, mtime=1000.0, size=100):
    return Candidate(height=height, mtime=mtime, size=size)


class TestResolutionWins:
    """Resolution outranks recency — the whole point of the rule."""

    def test_higher_resolution_source_wins_even_when_older(self):
        d = choose_winner(c(1080, mtime=1.0), c(720, mtime=999.0))
        assert d.winner == "source"
        assert "higher resolution" in d.reason

    def test_higher_resolution_dest_wins_even_when_older(self):
        """The Neagley case: a newer 720p must not evict an older 1080p."""
        d = choose_winner(c(720, mtime=999.0), c(1080, mtime=1.0))
        assert d.winner == "dest"
        assert "higher resolution" in d.reason

    def test_higher_resolution_wins_even_when_smaller(self):
        d = choose_winner(c(1080, size=10), c(720, size=10_000))
        assert d.winner == "source"

    @pytest.mark.parametrize("worse,better", [(480, 720), (720, 1080), (1080, 2160)])
    def test_ladder(self, worse, better):
        assert choose_winner(c(better), c(worse)).winner == "source"
        assert choose_winner(c(worse), c(better)).winner == "dest"


class TestNewerBreaksResolutionTies:
    """Steve's stated policy, applied among genuinely comparable files."""

    def test_same_resolution_newer_source_wins(self):
        d = choose_winner(c(1080, mtime=200.0), c(1080, mtime=100.0))
        assert d.winner == "source"
        assert "newer" in d.reason

    def test_same_resolution_newer_dest_wins(self):
        d = choose_winner(c(1080, mtime=100.0), c(1080, mtime=200.0))
        assert d.winner == "dest"
        assert "newer" in d.reason


class TestUnknownHeight:
    """Unknown must never be read as 'low quality' — it just abstains."""

    @pytest.mark.parametrize("src_h,dst_h", [(None, 1080), (1080, None), (None, None)])
    def test_falls_back_to_mtime(self, src_h, dst_h):
        d = choose_winner(c(src_h, mtime=200.0), c(dst_h, mtime=100.0))
        assert d.winner == "source"
        assert "newer" in d.reason

    def test_unreadable_file_is_not_condemned_for_being_unreadable(self):
        """A file nothing can probe still wins if it is the newer one."""
        d = choose_winner(c(None, mtime=999.0), c(1080, mtime=1.0))
        assert d.winner == "source"


class TestSizeTiebreak:
    def test_same_mtime_larger_source_wins(self):
        d = choose_winner(c(1080, mtime=5.0, size=200), c(1080, mtime=5.0, size=100))
        assert d.winner == "source"
        assert "larger" in d.reason

    def test_same_mtime_and_size_keeps_dest(self):
        """Ties favour the incumbent: never churn for nothing."""
        d = choose_winner(c(1080, mtime=5.0, size=100), c(1080, mtime=5.0, size=100))
        assert d.winner == "dest"


class TestRealWorldCases:
    """Drawn from the 2026-09-16 full-library preview."""

    def test_it_welcome_to_derry(self):
        """188 MB 480p arrival must not evict a 697 MB 1080p incumbent."""
        d = choose_winner(c(480, mtime=1788648466, size=188_217_186),
                          c(1080, mtime=1785193979, size=697_007_053))
        assert d.winner == "dest"

    def test_dark_matter_genuine_upgrade_still_replaces(self):
        """A real upgrade must still win — the rule is not merely conservative."""
        d = choose_winner(c(1080, mtime=1789446027, size=629_652_883),
                          c(720, mtime=1789248446, size=368_608_479))
        assert d.winner == "source"
