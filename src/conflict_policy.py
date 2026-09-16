"""Decide which of two files claiming one destination survives.

Pure policy: no filesystem, no logging, no side effects. The caller probes and
stats, this decides, the caller acts. Keeping it separate is what makes the rule
testable without building a library on disk — and this is the rule that deletes
things, so it is the one most worth testing.

The rule, in order:

1. **Higher resolution wins.** mtime is a proxy for "better" and it is simply
   wrong whenever a lower-quality release lands after a higher-quality one. A
   full-library preview on 2026-09-16 found 23 of 42 conflicts resolving in
   favour of the *smaller* file, including a 188 MB rip evicting a 697 MB one
   and a 201 MB rip evicting 1.6 GB.
2. **Then newer wins**, which is the stated policy for genuinely comparable
   files: a re-release of the same resolution is assumed to be the better one.
3. **Then larger wins**, the historical tiebreak.

An unknown height (unreadable file, no ffprobe, audio-only) is never treated as
"low quality" — it drops the comparison to step 2 rather than condemning a file
nothing could read.
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


def choose_winner(source: Candidate, dest: Candidate) -> Decision:
    """Pick the survivor of a same-destination conflict between two files.

    Args:
        source: The incoming file being filed.
        dest: The file already sitting at the destination.

    Returns:
        Decision(winner, reason) — `winner` names which candidate to keep.
    """
    if source.height and dest.height and source.height != dest.height:
        if source.height > dest.height:
            return Decision(
                "source",
                f"source is higher resolution ({source.height}p > {dest.height}p)",
            )
        return Decision(
            "dest",
            f"dest is higher resolution ({dest.height}p > {source.height}p)",
        )

    same_res = (
        f"same resolution ({source.height}p)"
        if source.height and dest.height
        else "resolution unknown"
    )

    if source.mtime != dest.mtime:
        if source.mtime > dest.mtime:
            return Decision("source", f"{same_res}, source is newer")
        return Decision("dest", f"{same_res}, dest is newer")

    if source.size > dest.size:
        return Decision("source", f"{same_res}, same mtime, source is larger")
    return Decision("dest", f"{same_res}, same mtime, dest is larger or equal")
