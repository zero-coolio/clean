"""Gather every name a media file has ever been known by, best evidence first.

One job: given a file, return the candidate name strings worth parsing. It does
not parse them, does not decide what they mean, and does not touch the
filesystem beyond reading the file's own container tags.

Why this exists (CLEAN-13). A movie without a date must go looking for one
rather than be ignored. clean-movie used to try the filename, then the folder,
then give up, which froze this file for three days:

    Eater's Guide to the World (2020)/Dr Who Joy To The World.mkv

The filename carries no year so the movie parser returned None; the folder was
correctly refused by the CLEAN-2 guard for naming a different work; and that was
the end of the search. Meanwhile the file's own container tag read
`Doctor.Who.Joy.to.the.World.2024...` and qBittorrent still held the torrent it
arrived in. The answer was open in two places CleanMedia was already reading.

ORDER MATTERS, and it is not "most reliable first". It is "most likely to
reflect a human's intent first":

1. The filename. It travels with the file, and when someone renames a file by
   hand they are correcting it. Their correction must win.
2. The container tag. Durable and original: a rip writes it once at creation
   and no rename CleanMedia performs ever rewrites it. This is the rung that
   survives CleanMedia's own past mistakes, which is exactly why it is here.
3. The torrent name. The name the file arrived under, when qBittorrent still
   knows about it.

DELIBERATELY ABSENT: the containing folder. The folder is handled upstream by
CleanMovieService._folder_fallback_allowed, which refuses it when it contradicts
the filename (CLEAN-2). Re-admitting it here as a candidate would route around
that guard and reinstate the renames it was written to stop.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .video_probe import container_title

logger = logging.getLogger(__name__)

# Video containers worth probing for a title tag. A subtitle or an .nfo has no
# container metadata, so probing one is a wasted subprocess.
PROBEABLE_EXT = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts"})

_RE_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def _dedupe_key(name: str) -> str:
    """Collapse a name to a comparison key, so near-identical rungs parse once."""
    return _RE_NOT_ALNUM.sub("", name.lower())


def candidate_names(
    path: Path,
    *,
    torrent_name: str | None = None,
    probe: bool = True,
    logger_=None,
) -> list[str]:
    """Names worth parsing for `path`, strongest intent first, deduplicated.

    Args:
        path: The media file.
        torrent_name: Name from the qBittorrent torrent this file belongs to,
            when one is known. Callers get it from `find_torrent_for_path`.
        probe: Read the container's title tag. Costs one ffprobe subprocess
            (memoized per process). Pass False to keep this pure and offline.
        logger_: Logger for the probe.

    Returns:
        Candidate name strings. Always non-empty: the filename stem is always
        the first entry, so a caller that parses this list is never doing less
        than it did before. Extensions are stripped from the stem only; the
        other rungs are returned as recorded.
    """
    log = logger_ or logger
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str | None, source: str) -> None:
        if not name or not name.strip():
            return
        key = _dedupe_key(name)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(name.strip())
        if source != "filename":
            log.debug("name_evidence: %s offers %r via %s", path.name, name, source)

    add(path.stem, "filename")

    if probe and path.suffix.lower() in PROBEABLE_EXT:
        add(container_title(path, log), "container tag")

    add(torrent_name, "torrent")

    return out


def describe(path: Path, names: list[str]) -> str:
    """A log-ready summary of what evidence was available for a file."""
    if len(names) <= 1:
        return f"{path.name}: filename only"
    return f"{path.name}: {len(names)} candidate name(s): " + ", ".join(
        repr(n) for n in names
    )
