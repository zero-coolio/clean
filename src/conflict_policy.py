"""Decide which of two files claiming one destination survives.

Pure policy: no filesystem, no logging, no side effects. The caller probes and
stats, this decides, the caller acts. Keeping it separate is what makes the rule
testable without building a library on disk, and this is the rule that deletes
things, so it is the one most worth testing.

THE RULE IS PER LIBRARY (Steve, 2026-10-13, CLEAN-21): "for movies keep the
higher quality, newest applies only to tv".

    ConflictRule.NEWEST   (TV)      newer -> larger -> incumbent
    ConflictRule.QUALITY  (movies)  resolution -> newer -> larger -> incumbent

That difference is not a compromise between CLEAN-2 and CLEAN-20; both were
right about their own library, which is why each kept producing a case that
embarrassed the other.

A second copy of a TV EPISODE is almost always a re-release of the same
broadcast: a fixed sync, a corrected audio track, a proper encode. Later means
better, so recency decides. This is also the rule that held for months before
CLEAN-2.

A second copy of a MOVIE is almost always a different rip of different quality,
arriving in whatever order the trackers happened to seed it. Recency there
means nothing at all, and following it cost real data: a full-library preview
on 2026-09-16 found 23 of 42 conflicts resolving in favour of the SMALLER file,
a 188 MB rip evicting a 697 MB one across all eight IT - Welcome to Derry
episodes, 201 MB evicting 1.6 GB on Mitchell & Webb, 9.7 GB of net loss.

Under NEWEST, resolution is still probed and still appears in the reason, for
one purpose: so a swap that LOSES picture quality says so instead of happening
quietly. `is_downgrade` marks those and the caller raises them to WARNING.
Under QUALITY a resolution downgrade cannot occur, because resolution is what
decides.

CAVEAT worth knowing: mtime is a weak proxy for release order in both
directions. A move preserves it, so "newer" can mean "copied later" rather than
"released later", and a file restored from a backup can look newer than the
release that superseded it.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, NamedTuple

Winner = Literal["source", "dest"]


class ConflictRule(Enum):
    """Which library's rule to apply. Services declare theirs; see CLEAN-21."""

    NEWEST = "newest"    # TV: a later episode file is a later release
    QUALITY = "quality"  # movies: a bigger picture beats an earlier arrival


class Candidate(NamedTuple):
    """One side of a destination conflict."""
    height: int | None   # pixel height, None when it could not be probed
    mtime: float
    size: int


class Decision(NamedTuple):
    winner: Winner
    reason: str          # short, log-ready explanation of which rule fired
    is_downgrade: bool   # the survivor is measurably lower resolution


def _downgrade(winner: Candidate, loser: Candidate) -> bool:
    """True when the surviving file is definitely the lower-resolution one.

    Both heights must be known. An unreadable file, a missing ffprobe or an
    audio-only track leaves this False: unknown is never reported as a loss,
    because nothing measured a loss.
    """
    return bool(winner.height and loser.height and winner.height < loser.height)


def choose_winner(
    source: Candidate,
    dest: Candidate,
    rule: ConflictRule = ConflictRule.QUALITY,
) -> Decision:
    """Pick the survivor of a same-destination conflict between two files.

    Args:
        source: The incoming file being filed.
        dest: The file already sitting at the destination.
        rule: Which library's rule to apply. Defaults to QUALITY, the
            conservative one: a caller that forgets to say cannot silently
            trade picture quality away.

    Returns:
        Decision(winner, reason, is_downgrade). `winner` names which candidate
        to keep; `is_downgrade` says the survivor is lower resolution than the
        file being discarded, which the caller must log loudly.
    """
    if (
        rule is ConflictRule.QUALITY
        and source.height and dest.height
        and source.height != dest.height
    ):
        if source.height > dest.height:
            return Decision(
                "source",
                f"source is higher resolution ({source.height}p > {dest.height}p)",
                False,
            )
        return Decision(
            "dest",
            f"dest is higher resolution ({dest.height}p > {source.height}p)",
            False,
        )

    if source.mtime != dest.mtime:
        if source.mtime > dest.mtime:
            winner, loser, label = source, dest, ("source", "source is newer")
        else:
            winner, loser, label = dest, source, ("dest", "dest is newer")
    elif source.size != dest.size:
        if source.size > dest.size:
            winner, loser, label = source, dest, (
                "source", "same mtime, source is larger")
        else:
            winner, loser, label = dest, source, (
                "dest", "same mtime, dest is larger")
    else:
        # Identical mtime and identical size: nothing distinguishes them, so
        # keep what is already in place rather than churn the library.
        winner, loser, label = dest, source, (
            "dest", "same mtime and size, keeping the incumbent")

    name, reason = label
    down = _downgrade(winner, loser)
    if down:
        reason = (
            f"{reason} but LOWER RESOLUTION "
            f"({winner.height}p < {loser.height}p): QUALITY DOWNGRADE"
        )
    elif winner.height and loser.height:
        reason = f"{reason} ({winner.height}p vs {loser.height}p)"

    return Decision(name, reason, down)
