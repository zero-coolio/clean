"""Tests for the same-destination conflict rule.

This is the rule that decides which file gets deleted, so it is tested
exhaustively and without a filesystem.

THE RULE IS PER LIBRARY (Steve, 2026-10-13, CLEAN-21): "for movies keep the
higher quality, newest applies only to tv".

    NEWEST  (TV)      newer -> larger -> incumbent
    QUALITY (movies)  resolution -> newer -> larger -> incumbent

Both halves are tested, and the real-world cases from the 2026-09-16
investigation are kept under BOTH rules, because the point of CLEAN-21 is that
those cases come out differently depending on which library they are in.
"""
import pytest

from src.conflict_policy import Candidate, ConflictRule, choose_winner

TV = ConflictRule.NEWEST
MOVIE = ConflictRule.QUALITY


def c(height=None, mtime=1000.0, size=100):
    return Candidate(height=height, mtime=mtime, size=size)


class TestNewerWins:
    """Recency is the whole rule, regardless of resolution or size."""

    def test_newer_source_wins(self):
        d = choose_winner(c(1080, mtime=200.0), c(1080, mtime=100.0), TV)
        assert d.winner == "source"
        assert "newer" in d.reason

    def test_newer_dest_wins(self):
        d = choose_winner(c(1080, mtime=100.0), c(1080, mtime=200.0), TV)
        assert d.winner == "dest"
        assert "newer" in d.reason

    def test_newer_wins_even_when_lower_resolution(self):
        """A newer 720p now evicts an older 1080p. That is the chosen rule."""
        d = choose_winner(c(720, mtime=999.0), c(1080, mtime=1.0), TV)
        assert d.winner == "source"
        assert d.is_downgrade

    def test_newer_wins_even_when_smaller(self):
        d = choose_winner(c(720, mtime=999.0, size=10), c(1080, mtime=1.0, size=10_000), TV)
        assert d.winner == "source"

    def test_older_higher_resolution_file_is_discarded(self):
        """The mirror of the above: an older 1080p source loses to a newer dest."""
        d = choose_winner(c(1080, mtime=1.0), c(720, mtime=999.0), TV)
        assert d.winner == "dest"
        assert d.is_downgrade

    @pytest.mark.parametrize("height", [480, 720, 1080, 2160])
    def test_resolution_does_not_decide_at_any_rung(self, height):
        assert choose_winner(c(height, mtime=2.0), c(2160, mtime=1.0), TV).winner == "source"


class TestDowngradeIsFlagged:
    """Recency-wins trades picture quality. It must never do so silently."""

    def test_downgrade_is_marked_and_named(self):
        d = choose_winner(c(480, mtime=999.0), c(1080, mtime=1.0), TV)
        assert d.is_downgrade
        assert "QUALITY DOWNGRADE" in d.reason
        assert "480p < 1080p" in d.reason

    def test_an_upgrade_is_not_a_downgrade(self):
        d = choose_winner(c(1080, mtime=999.0), c(480, mtime=1.0), TV)
        assert not d.is_downgrade
        assert "DOWNGRADE" not in d.reason

    def test_same_resolution_is_not_a_downgrade(self):
        d = choose_winner(c(1080, mtime=999.0), c(1080, mtime=1.0), TV)
        assert not d.is_downgrade

    @pytest.mark.parametrize("src_h,dst_h", [(None, 1080), (1080, None), (None, None)])
    def test_unknown_height_is_never_reported_as_a_loss(self, src_h, dst_h):
        """Nothing measured a loss, so nothing may claim one."""
        d = choose_winner(c(src_h, mtime=200.0), c(dst_h, mtime=100.0), TV)
        assert not d.is_downgrade


class TestUnknownHeight:
    """Unknown must never be read as 'low quality'. It just abstains."""

    @pytest.mark.parametrize("src_h,dst_h", [(None, 1080), (1080, None), (None, None)])
    def test_falls_back_to_mtime(self, src_h, dst_h):
        d = choose_winner(c(src_h, mtime=200.0), c(dst_h, mtime=100.0), TV)
        assert d.winner == "source"
        assert "newer" in d.reason

    def test_unreadable_file_is_not_condemned_for_being_unreadable(self):
        d = choose_winner(c(None, mtime=999.0), c(1080, mtime=1.0), TV)
        assert d.winner == "source"


class TestSizeTiebreak:
    def test_same_mtime_larger_source_wins(self):
        d = choose_winner(c(1080, mtime=5.0, size=200), c(1080, mtime=5.0, size=100), TV)
        assert d.winner == "source"
        assert "larger" in d.reason

    def test_same_mtime_larger_dest_wins(self):
        d = choose_winner(c(1080, mtime=5.0, size=100), c(1080, mtime=5.0, size=200), TV)
        assert d.winner == "dest"
        assert "larger" in d.reason

    def test_same_mtime_and_size_keeps_dest(self):
        """Ties favour the incumbent: never churn for nothing."""
        d = choose_winner(c(1080, mtime=5.0, size=100), c(1080, mtime=5.0, size=100), TV)
        assert d.winner == "dest"
        assert "incumbent" in d.reason


class TestRealWorldCases:
    """Real numbers from the 2026-09-16 full-library preview and 2026-10-13."""

    def test_it_welcome_to_derry_now_loses_the_better_rip(self):
        """THE ACCEPTED COST of CLEAN-20, recorded as a test rather than a
        surprise. A 188 MB 480p arrival is newer than the 697 MB 1080p
        incumbent, so under recency-wins it takes the slot. This happened
        across all eight episodes. CLEAN-2 existed to stop exactly this.
        """
        d = choose_winner(c(480, mtime=1788648466, size=188_217_186), c(1080, mtime=1785193979, size=697_007_053), TV)
        assert d.winner == "source"
        assert d.is_downgrade

    def test_dark_matter_genuine_upgrade_still_replaces(self):
        d = choose_winner(c(1080, mtime=1789446027, size=629_652_883), c(720, mtime=1789248446, size=368_608_479), TV)
        assert d.winner == "source"
        assert not d.is_downgrade

    def test_fbi_s09e02_omissions(self):
        """2026-10-13, the case that prompted CLEAN-20. Both rules agree here:
        the 1080p arrival is newer AND better, so it wins either way."""
        d = choose_winner(c(1080, mtime=1792329470, size=2_693_818_799), c(720, mtime=1792318200, size=1_340_104_447), TV)
        assert d.winner == "source"
        assert not d.is_downgrade


class TestMovieRuleKeepsTheHigherQuality:
    """CLEAN-21: for movies, resolution decides and recency is only a tiebreak."""

    def test_higher_resolution_wins_even_when_older(self):
        d = choose_winner(c(1080, mtime=1.0), c(720, mtime=999.0), MOVIE)
        assert d.winner == "source"
        assert "higher resolution" in d.reason
        assert not d.is_downgrade

    def test_higher_resolution_dest_wins_even_when_older(self):
        d = choose_winner(c(720, mtime=999.0), c(1080, mtime=1.0), MOVIE)
        assert d.winner == "dest"
        assert "higher resolution" in d.reason

    def test_higher_resolution_wins_even_when_smaller(self):
        d = choose_winner(c(1080, size=10), c(720, size=10_000), MOVIE)
        assert d.winner == "source"

    @pytest.mark.parametrize("worse,better", [(480, 720), (720, 1080), (1080, 2160)])
    def test_the_whole_ladder(self, worse, better):
        assert choose_winner(c(better), c(worse), MOVIE).winner == "source"
        assert choose_winner(c(worse), c(better), MOVIE).winner == "dest"

    def test_recency_still_breaks_a_resolution_tie(self):
        d = choose_winner(c(1080, mtime=200.0), c(1080, mtime=100.0), MOVIE)
        assert d.winner == "source"
        assert "newer" in d.reason

    def test_a_movie_can_never_be_downgraded_by_this_rule(self):
        """Resolution decides first, so the flag cannot fire."""
        for src_h, dst_h in [(480, 1080), (1080, 480), (720, 1080)]:
            d = choose_winner(c(src_h, mtime=999.0), c(dst_h, mtime=1.0), MOVIE)
            assert not d.is_downgrade

    def test_unknown_height_falls_back_to_recency(self):
        d = choose_winner(c(None, mtime=200.0), c(1080, mtime=100.0), MOVIE)
        assert d.winner == "source"


class TestTheSameCaseResolvesPerLibrary:
    """The point of CLEAN-21, stated as a test."""

    def test_it_welcome_to_derry(self):
        """188 MB 480p arriving after a 697 MB 1080p incumbent. As TV the newer
        file wins and the loss is flagged; as a movie the better rip is kept."""
        src = c(480, mtime=1788648466, size=188_217_186)
        dst = c(1080, mtime=1785193979, size=697_007_053)

        as_tv = choose_winner(src, dst, TV)
        assert as_tv.winner == "source" and as_tv.is_downgrade

        as_movie = choose_winner(src, dst, MOVIE)
        assert as_movie.winner == "dest" and not as_movie.is_downgrade

    def test_a_genuine_upgrade_wins_under_either_rule(self):
        src = c(1080, mtime=1789446027, size=629_652_883)
        dst = c(720, mtime=1789248446, size=368_608_479)
        assert choose_winner(src, dst, TV).winner == "source"
        assert choose_winner(src, dst, MOVIE).winner == "source"


class TestDefaultIsTheConservativeRule:
    def test_omitting_the_rule_keeps_the_better_picture(self):
        """A caller that forgets must not silently trade quality away."""
        d = choose_winner(c(1080, mtime=1.0), c(720, mtime=999.0))
        assert d.winner == "source"
        assert "higher resolution" in d.reason
