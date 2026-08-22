#!/usr/bin/env python3
"""What counts as a usable TVMaze episode title.

One job: classify a title string. Shared by the two places that care and would
otherwise each keep their own copy of the placeholder list — the filename
builder in `tvmaze.py` and the cache-replacement guard in `tvmaze_freshness.py`.

They ask DIFFERENT questions, deliberately:

* `real_title` — "may this be baked into a filename?" Rejects only TVMaze's
  unannounced-episode placeholders (TBA/TBD). A numbered title like
  "Episode 6" is genuinely all TVMaze has for some shows and IS used in
  filenames; see tests/test_tvmaze_collapse_renumber.py.
* `is_identifying_title` — "does this title identify WHICH show this is?"
  Stricter: "Episode 6" appears in thousands of shows and identifies none of
  them, so it is rejected here even though it is filename-worthy.
"""
from __future__ import annotations

import re

# TVMaze placeholders for episodes that exist but have no announced title yet.
PLACEHOLDER_TITLES = frozenset({"tba", "tbd", "to be announced", "to be determined"})

# Auto-generated positional titles: "Episode 4", "Ep. 12", "Episode #7".
# Common on shows TVMaze has not fully titled yet — and routinely replaced by
# real titles later, which is exactly why they must not count as show identity.
_RE_GENERIC_TITLE = re.compile(r"^ep(?:isode)?\.?\s*#?\s*\d+$", re.IGNORECASE)


def real_title(title: str | None) -> str | None:
    """Return a title safe to write into a filename, or None.

    TVMaze lists unannounced episodes with a placeholder like "TBA". Treating
    that as a real title bakes a fake name into the filename (e.g.
    ``House.of.the.Dragon.(2022).S03E02.TBA.avi``), so placeholders collapse to
    None and no title suffix is appended.
    """
    if not title:
        return None
    if title.strip().lower() in PLACEHOLDER_TITLES:
        return None
    return title


def is_identifying_title(title: str | None) -> bool:
    """True if this title is evidence of WHICH show an episode belongs to.

    Rejects empties, TBA-style placeholders, and positional titles like
    "Episode 4". The last one matters: a show sitting on placeholder titles gets
    them replaced with real ones as they are announced, and counting that
    replacement as "the titles no longer match" would make a legitimate refresh
    look like a mis-resolved show (observed on `lucky (2026)`, where 4 of 7
    "Episode N" titles became real titles between fetches).
    """
    if not title:
        return False
    stripped = title.strip()
    if not stripped:
        return False
    if stripped.lower() in PLACEHOLDER_TITLES:
        return False
    return not _RE_GENERIC_TITLE.match(stripped)
