"""Unit tests for the shared-cache staleness rule.

All hermetic: `needs_refresh` is pure and takes an injected `now`, so nothing
here touches TVMaze or the real cache.
"""
import datetime

import pytest

from src.tvmaze_freshness import CONTINUATION_WINDOW_DAYS, needs_refresh

NOW = datetime.date(2026, 8, 21)


def ep(airdate, season=1, episode=1):
    return {"season": season, "episode": episode, "title": "T", "airdate": airdate}


def days_before(n):
    return (NOW - datetime.timedelta(days=n)).isoformat()


def days_after(n):
    return (NOW + datetime.timedelta(days=n)).isoformat()


# --- condition 1: forward data means the entry is already doing its job -----

def test_unaired_episode_present_is_not_stale():
    episodes = [ep(days_before(30)), ep(days_after(7), episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is False


def test_forward_data_wins_even_when_newest_aired_is_ancient():
    """A show returning after a long hiatus with a scheduled episode is fine."""
    episodes = [ep("2010-01-01"), ep(days_after(1), episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is False


def test_episode_airing_exactly_today_is_not_forward_data():
    """Today has aired. It tells us nothing about what comes next."""
    assert needs_refresh([ep(NOW.isoformat())], None, NOW) is True


# --- condition 2: the continuation window ----------------------------------

def test_all_aired_and_recent_is_stale():
    assert needs_refresh([ep(days_before(200))], None, NOW) is True


def test_reacher_case_512_day_gap_is_stale():
    """The exact case that broke lime — and the reason the window is 2 years.

    Reacher's cached season-3 finale aired 2025-03-27, 512 days before the
    season-4 airing that lime could not see. A one-year window misses it.
    """
    episodes = [ep("2025-03-27", season=3, episode=8)]
    assert needs_refresh(episodes, "2026-06-21T19:21:03Z", NOW) is True
    assert needs_refresh(episodes, None, NOW, window_days=365) is False


def test_ludwig_case_aired_yesterday_is_stale():
    """No lower bound: a show mid-season with no next episode listed is the
    MOST valuable refresh, not something to skip as 'nothing new yet'."""
    assert needs_refresh([ep(days_before(1))], "2026-08-20T09:40:32Z", NOW) is True


def test_show_ended_years_ago_is_not_stale():
    """sons of anarchy, ended 2014 — stays put."""
    assert needs_refresh([ep("2014-12-09", season=7, episode=13)], None, NOW) is False


@pytest.mark.parametrize(
    "age_days, expected",
    [
        (CONTINUATION_WINDOW_DAYS - 1, True),
        (CONTINUATION_WINDOW_DAYS, True),      # inclusive boundary
        (CONTINUATION_WINDOW_DAYS + 1, False),
    ],
)
def test_window_boundary_is_inclusive(age_days, expected):
    assert needs_refresh([ep(days_before(age_days))], None, NOW) is expected


def test_newest_episode_decides_not_the_first():
    """An old pilot must not drag a still-running show out of the window."""
    episodes = [ep("2005-01-01"), ep(days_before(10), season=9, episode=4)]
    assert needs_refresh(episodes, None, NOW) is True


# --- fetchedAt must NOT influence the decision -----------------------------

@pytest.mark.parametrize(
    "fetched_at",
    [None, "", "2026-08-21T00:00:00Z", "2020-01-01T00:00:00Z", "garbage"],
)
def test_fetched_at_never_changes_the_answer(fetched_at):
    """Guards the measured negative result: a fetchedAt TTL does not
    discriminate on the real cache (ages are near-constant, so every threshold
    either re-fetches ~all 358 shows or none). If someone reintroduces one,
    this fails instead of the library.
    """
    stale = [ep(days_before(200))]
    fresh = [ep("2014-12-09")]
    assert needs_refresh(stale, fetched_at, NOW) is True
    assert needs_refresh(fresh, fetched_at, NOW) is False


# --- degenerate entries ----------------------------------------------------

def test_empty_episode_list_is_not_stale():
    """No newest airdate means condition 2 can never hold — and an entry TVMaze
    resolved nothing for would otherwise cost a search + fetch every pass."""
    assert needs_refresh([], "2026-01-01T00:00:00Z", NOW) is False


def test_none_episodes_is_not_stale():
    assert needs_refresh(None, None, NOW) is False


def test_episodes_with_no_airdates_are_not_stale():
    assert needs_refresh([{"season": 1, "episode": 1, "title": "T", "airdate": ""}], None, NOW) is False


def test_unparseable_airdates_are_ignored_not_fatal():
    """The shared cache is co-owned; one bad row must not make a show undecidable."""
    episodes = [ep("not-a-date"), ep(days_before(30), episode=2)]
    assert needs_refresh(episodes, None, NOW) is True


def test_only_unparseable_airdates_is_not_stale():
    assert needs_refresh([ep("not-a-date")], None, NOW) is False


def test_datetime_style_airdate_is_tolerated():
    """lime writes plain dates, but a full timestamp must not crash the rule."""
    assert needs_refresh([{"airdate": days_before(30) + "T20:00:00+00:00"}], None, NOW) is True


# --- replacement guard -----------------------------------------------------

from src.tvmaze_freshness import is_plausible_replacement  # noqa: E402


def titled(*names):
    return [{"season": 1, "episode": i, "title": n, "airdate": "2026-01-01"}
            for i, n in enumerate(names, 1)]


def test_replacement_with_matching_titles_is_plausible():
    assert is_plausible_replacement(titled("A", "B", "C"), titled("A", "B", "C", "D")) is True


def test_avatar_style_downward_revision_is_plausible():
    """TVMaze revising 16 episodes to 15 is a correction, not a wrong show."""
    old = titled(*[f"E{i}" for i in range(16)])
    assert is_plausible_replacement(old, titled(*[f"E{i}" for i in range(15)])) is True


def test_completely_different_show_is_rejected():
    assert is_plausible_replacement(titled("Welcome to Wherever", "Paper"),
                                    titled("Naoki and Kotoko", "First Kiss")) is False


def test_case_differences_still_count_as_matching():
    assert is_plausible_replacement(titled("A Fine Day", "Bee"), titled("a fine day", "BEE")) is True


def test_guard_abstains_when_cached_titles_are_blank():
    """Some cached shows genuinely have no titles — don't block their refresh
    on evidence that doesn't exist."""
    blank = [{"season": 1, "episode": 1, "title": "", "airdate": "2026-01-01"}] * 3
    assert is_plausible_replacement(blank, titled("X", "Y", "Z")) is True


def test_guard_abstains_on_a_single_cached_title():
    assert is_plausible_replacement(titled("Only One"), titled("Totally", "Different")) is True


def test_guard_abstains_when_there_is_nothing_cached():
    assert is_plausible_replacement([], titled("A", "B")) is True
    assert is_plausible_replacement(None, titled("A", "B")) is True


def test_empty_fetch_is_never_a_plausible_replacement():
    assert is_plausible_replacement(titled("A", "B"), []) is False
    assert is_plausible_replacement(titled("A", "B"), None) is False


def test_half_the_titles_surviving_is_the_accepted_boundary():
    old = titled("A", "B", "C", "D")
    assert is_plausible_replacement(old, titled("A", "B", "X", "Y")) is True   # 50%
    assert is_plausible_replacement(old, titled("A", "X", "Y", "Z")) is False  # 25%


def test_lucky_case_placeholder_titles_becoming_real_is_plausible():
    """Observed on the real cache: TVMaze filled in 4 of 7 "Episode N" titles
    between fetches, dropping naive overlap to 43% and blocking a legitimate
    refresh of the same show."""
    old = titled("No Shortcuts", "Make 'em Dance", "Read the Room",
                 "Episode 4", "Episode 5", "Episode 6", "Episode 7")
    new = titled("No Shortcuts", "Make 'em Dance", "Read the Room",
                 "Too Close to See It", "Are We Bad People?",
                 "Wherever You Go, There You Are", "All Good Things")
    assert is_plausible_replacement(old, new) is True


def test_guard_abstains_when_cached_titles_are_all_positional():
    """All-"Episode N" titles are no evidence at all, not evidence of a mismatch."""
    old = titled("Episode 1", "Episode 2", "Episode 3")
    assert is_plausible_replacement(old, titled("Totally", "Different", "Show")) is True


# --- aired-but-still-"TBA" title forces a re-check (Slow Horses S6) ----------

def epT(airdate, title, season=1, episode=1):
    return {"season": season, "episode": episode, "title": title, "airdate": airdate}


def test_aired_placeholder_title_refreshes_despite_forward_data():
    """An aired episode still titled 'TBA' must trigger a refresh even though a
    later episode is unaired (forward data), which normally reads as fresh."""
    episodes = [epT(days_before(4), "TBA"), epT(days_after(7), "Something", episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is True


def test_aired_empty_title_refreshes():
    episodes = [epT(days_before(4), ""), epT(days_after(7), "Next", episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is True


def test_aired_real_title_with_forward_data_not_stale():
    episodes = [epT(days_before(4), "Pilot"), epT(days_after(7), "Next", episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is False


def test_unaired_placeholder_title_not_stale():
    """A 'TBA' title on an episode that hasn't aired yet is normal, not stale."""
    episodes = [epT(days_after(7), "TBA")]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is False


def test_positional_title_on_aired_episode_is_not_a_placeholder():
    """'Episode 4' is a weak real title, not a TBA placeholder; with forward data
    present it must NOT force a refresh (or such shows re-fetch forever)."""
    episodes = [epT(days_before(4), "Episode 1"), epT(days_after(7), "Episode 2", episode=2)]
    assert needs_refresh(episodes, "2026-01-01T00:00:00Z", NOW) is False
