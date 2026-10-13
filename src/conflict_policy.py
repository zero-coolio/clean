"""Decide which of two files claiming one destination survives.

Pure policy: no filesystem, no logging, no side effects. The caller probes and
stats, this decides, the caller acts. Keeping it separate is what makes the rule
testable without building a library on disk, and this is the rule that deletes
things, so it is the one most worth testing.

THE RULE (Steve, 2026-10-13, CLEAN-20): the latest version of an episode
replaces the older one.

1. **Newer wins.** A later mtime is taken as a later release, and a later
   release is the one to keep.
2. **Then larger wins**, the historical tiebreak for identical mtimes.

Resolution does not decide anything. It is still probed, and it still appears
in the reason string, for one purpose: so that a swap which LOSES picture
quality says so in the log instead of happening quietly. `is_downgrade` marks
those, and the caller raises them to WARNING.

This reverses CLEAN-2 (27b5a8c, 2026-09-16), which made resolution the primary
key after a full-library preview found 23 of 42 conflicts resolving in favour
of the smaller file: a 188 MB rip evicting a 697 MB one across all eight
IT - Welcome to Derry episodes, 201 MB evicting 1.6 GB on Mitchell & Webb,
9.7 GB of net loss. That cost is known and accepted; recency is the rule Steve
wants and the one that held for months before CLEAN-2. The downgrade flag
exists so the cost is observable rather than invisible.

CAVEAT worth knowing: mtime is a weak proxy for release order in both
directions. A move preserves it, so "newer" can mean "copied later" rather than
"released later", and a file restored from a backup can look newer than the
release that superseded it.
"""
from __future__ import annotations

from typing import Literal, NamedTuple

Winner = Literal["source", "dest"]


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


def choose_winner(source: Candidate, dest: Candidate) -> Decision:
    """Pick the survivor of a same-destination conflict between two files.

    Args:
        source: The incoming file being filed.
        dest: The file already sitting at the destination.

    Returns:
        Decision(winner, reason, is_downgrade). `winner` names which candidate
        to keep; `is_downgrade` says the survivor is lower resolution than the
        file being discarded, which the caller must log loudly.
    """
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
