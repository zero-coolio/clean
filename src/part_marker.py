"""Spot a name that claims to be one PART of a work, not the whole of it.

One job: given a name, say whether it carries a part marker and which part.
No filesystem, no network.

Why this exists (CLEAN-23). Red Dwarf: The Promised Land shipped as two parts.
Both parsed to the same title and year, so both targeted one destination, and
the conflict rule trashed the second:

    CONFLICT: dest is newer (576p vs 576p), keeping dest, trashing source
              (669905135 vs 625814506 bytes)

Every signal conflict_policy looks at said "duplicate": same title, same year,
same resolution, similar size. Nothing told it these were two halves of one
film. 625 MB of a 1.3 GB feature went to the Trash and the log line read like
routine housekeeping.

THE ASYMMETRY THAT MAKES THIS WORK. By the time a second part arrives, the
first has already been renamed to "Title (Year).mkv" and its own marker is
gone. So the incumbent cannot be asked. Only the ARRIVING file still says
"part.2", and that is enough: a source claiming to be a part, landing on a
destination that is already occupied, must not be resolved by a rule designed
to choose between two copies of the same thing.

SCOPE: detection and refusal only. Carrying the part number into the
destination, so the parts can actually coexist, is the other half of CLEAN-23
and is not done here. Until it is, a multi-part file stays where it is and is
reported, which loses nothing.
"""
from __future__ import annotations

import re

# Written-out numbers seen in real release names ("...Part.Two.2024...").
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# "part 2", "part.2", "part_2", "pt2", "pt.2", "part two".
_RE_PART_WORD = re.compile(
    r"(?<![A-Za-z0-9])(?:part|pt)[\s._\-]*"
    r"(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# "cd1", "cd 2", "disc2", "disk 1". A separate pattern because these never
# spell the number out and must not match a bare "cd".
_RE_PART_DISC = re.compile(
    r"(?<![A-Za-z0-9])(?:cd|disc|disk)[\s._\-]*(\d{1,2})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def part_number(name: str) -> int | None:
    """The part this name claims to be, or None if it claims no part.

    Args:
        name: A filename, stem or release name.

    Returns:
        The part number, or None. Note that None means "says nothing about
        parts", NOT "is part 1": a file named for the whole work and a file
        named "part 1" are different claims, and only the second is detectable.
    """
    for pattern in (_RE_PART_WORD, _RE_PART_DISC):
        m = pattern.search(name)
        if not m:
            continue
        token = m.group(1).lower()
        if token.isdigit():
            n = int(token)
        else:
            n = _WORD_NUMBERS.get(token)
        # Part 0 is not a part; it is a stray zero in release noise.
        if n:
            return n
    return None


def claims_a_part(name: str) -> bool:
    """True when `name` says it is one part of something larger."""
    return part_number(name) is not None
