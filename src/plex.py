#!/usr/bin/env python3
"""Tell Plex to rescan the directories a clean run touched.

One job: turn a set of filesystem paths into targeted Plex partial scans. No
filesystem access, no knowledge of what a run did, no opinions about media.

Why this exists. Plex's own auto-update is enabled here
(FSEventLibraryUpdatesEnabled, FSEventLibraryPartialScanEnabled, plus a
scheduled scan every 3600s) and it does sometimes fire. Both libraries live on
an external volume, where FSEvents delivery is unreliable, which is exactly the
intermittent symptom Steve reported on 2026-10-25: "sometimes the autoscan
works, sometimes I have to trigger it manually." When FSEvents misses, the
hourly scheduled scan is the only backstop, so a rename can sit invisible in
Plex for up to an hour.

    GET /library/sections/{id}/refresh?path=<dir>   header: X-Plex-Token

That is a PARTIAL scan of one directory, measured at ~250ms against the live
server, rather than a walk of the whole library.

SAFETY. This module is a side effect of a program that renames and deletes
files on a real media volume, unattended. It is therefore built to be ignorable:

  * Nothing here raises. Every entry point swallows everything, including
    timeouts, bad XML, a moved server and a wrong token, and logs instead.
  * It needs no setup. The token comes from PLEX_TOKEN if set, otherwise from
    Plex's own preferences on this machine, so nothing has to be copied and
    there is no second copy to drift. With neither available it is a no-op.
  * It is time-bounded. A whole notification pass gives up after
    PLEX_NOTIFY_BUDGET seconds no matter how many directories were touched.
  * It reads. The only request it ever issues is a scan trigger; it never
    writes to, edits or deletes anything in Plex.

A failure to notify costs a stale library view until the next scheduled scan.
It must never cost a file, so nothing in a clean run may depend on this
returning, succeeding, or being quick.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePath

from .config import (
    PLEX_BASE_URL,
    PLEX_MAX_TARGETED_SCANS,
    PLEX_NOTIFY_BUDGET,
    PLEX_TIMEOUT,
    PLEX_TOKEN,
    get_logger,
)

_log = get_logger("plex")


def _token_from_plex_prefs() -> str | None:
    """The token Plex itself already stores on this machine, or None.

    Plex keeps it in its own preferences, so there is no reason to copy it into
    cleanMedia/.env and then maintain two copies that can drift. Reading the
    original means a token rotated in Plex is picked up with no action here.

    Narrow by design: this is the Mac that runs the server, the file is the
    user's own, and plistlib reads it directly with no subprocess. If Plex ever
    moves to another host, set PLEX_TOKEN (and PLEX_BASE_URL) explicitly and
    this is never consulted.
    """
    try:
        import plistlib

        prefs = Path.home() / "Library/Preferences/com.plexapp.plexmediaserver.plist"
        if not prefs.exists():
            return None
        return plistlib.loads(prefs.read_bytes()).get("PlexOnlineToken") or None
    except Exception as e:
        _log.debug("Plex: could not read the token from Plex's preferences: %s", e)
        return None


def resolve_token() -> str | None:
    """An explicit PLEX_TOKEN if set, otherwise Plex's own stored token."""
    return PLEX_TOKEN or _token_from_plex_prefs()


def _get(url: str, timeout: float) -> bytes | None:
    """One HTTP GET. Returns the body, or None on any failure whatsoever.

    The single network seam in this module, so tests stub this rather than
    urllib (which conftest blocks outright to keep the suite hermetic).
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        _log.debug("Plex: request failed for %s: %s", url.split("?")[0], e)
        return None


def _url(endpoint: str, token: str, **params: str) -> str:
    """Build a tokened Plex URL. The token rides in the query string because
    _get takes no headers; it never reaches a log, which only sees the part
    before the "?".

    The first argument is `endpoint`, not `path`: callers pass Plex's own
    `path=` scan parameter through **params, and naming it twice made every
    targeted scan raise TypeError. The fail-soft wrapper turned that into a
    warning rather than a crash, which is precisely how it stayed invisible
    until a live run.
    """
    query = dict(params)
    query["X-Plex-Token"] = token
    return f"{PLEX_BASE_URL.rstrip('/')}{endpoint}?{urllib.parse.urlencode(query)}"


def fetch_sections(token: str, timeout: float = PLEX_TIMEOUT) -> list[tuple[str, list[str]]]:
    """Return [(section_id, [library paths])], or [] if Plex cannot be reached.

    Discovered at runtime rather than configured, so adding or moving a Plex
    library needs no change here.
    """
    body = _get(_url("/library/sections", token), timeout)
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        _log.debug("Plex: could not parse /library/sections: %s", e)
        return []

    sections: list[tuple[str, list[str]]] = []
    for directory in root.findall("Directory"):
        key = directory.get("key")
        if not key:
            continue
        locations = [
            loc.get("path") for loc in directory.findall("Location") if loc.get("path")
        ]
        if locations:
            sections.append((key, locations))
    return sections


def section_for(path: str | PurePath, sections: list[tuple[str, list[str]]]) -> str | None:
    """The id of the section whose library contains `path`, or None.

    Picks the LONGEST matching location, so a nested library wins over the
    parent it sits inside rather than the first one listed.
    """
    target = PurePath(path)
    best: tuple[int, str] | None = None
    for key, locations in sections:
        for loc in locations:
            loc_path = PurePath(loc)
            if target == loc_path or loc_path in target.parents:
                depth = len(loc_path.parts)
                if best is None or depth > best[0]:
                    best = (depth, key)
    return best[1] if best else None


def notify_paths(paths, logger=None) -> None:
    """Ask Plex to rescan the directories containing `paths`. Never raises.

    Args:
        paths: Filesystem paths a run touched. Files and directories both
            accepted; a file is reduced to its parent directory. Duplicates and
            paths outside every Plex library are dropped.
        logger: Optional run logger, so the notification is visible in the same
            place as the moves that caused it.
    """
    log = logger or _log
    try:
        _notify(paths, log)
    except Exception as e:
        # The whole point. A clean run has already moved files by the time we
        # get here; nothing this module does is worth failing that run over.
        log.warning("Plex: notification failed, library may be stale: %s", e)


def _notify(paths, log) -> None:
    token = resolve_token()
    if not token:
        log.debug(
            "Plex: no token (set PLEX_TOKEN in cleanMedia/.env, or let Plex's "
            "own preferences supply it), skipping rescan"
        )
        return

    directories = _directories(paths)
    if not directories:
        return

    deadline = time.monotonic() + PLEX_NOTIFY_BUDGET

    sections = fetch_sections(token)
    if not sections:
        log.warning("Plex: no sections returned, skipping rescan")
        return

    by_section: dict[str, list[str]] = {}
    for directory in directories:
        key = section_for(directory, sections)
        if key:
            by_section.setdefault(key, []).append(directory)

    if not by_section:
        log.debug("Plex: nothing touched inside a Plex library")
        return

    for key, dirs in sorted(by_section.items()):
        if time.monotonic() > deadline:
            log.warning("Plex: notification budget spent, section %s not scanned", key)
            return
        _scan_section(key, dirs, token, deadline, log)


def _scan_section(key: str, dirs: list[str], token: str, deadline: float, log) -> None:
    """Scan one section: per-directory while that is cheap, else section-wide.

    A run that reorganizes hundreds of folders would otherwise issue hundreds of
    requests. Past the cap one section scan is both cheaper and more thorough,
    so the fallback is a widening, never a loss of coverage.
    """
    if len(dirs) > PLEX_MAX_TARGETED_SCANS:
        if _get(_url(f"/library/sections/{key}/refresh", token), PLEX_TIMEOUT) is None:
            log.warning("Plex: section %s full scan failed", key)
        else:
            log.info("Plex: section %s full scan (%d directories touched)", key, len(dirs))
        return

    scanned = 0
    for directory in dirs:
        if time.monotonic() > deadline:
            log.warning(
                "Plex: budget spent after %d/%d directories in section %s",
                scanned, len(dirs), key,
            )
            return
        url = _url(f"/library/sections/{key}/refresh", token, path=directory)
        if _get(url, PLEX_TIMEOUT) is None:
            log.warning("Plex: scan failed for %s", directory)
        else:
            scanned += 1
    if scanned:
        log.info("Plex: section %s rescanned %d director%s",
                 key, scanned, "y" if scanned == 1 else "ies")


def _directories(paths) -> list[str]:
    """Distinct parent directories of `paths`, order preserved.

    A path that still exists and is a directory is used as-is; anything else is
    reduced to its parent. That covers a file (scan its folder) and a release
    folder clean has already deleted (scan where it was, so Plex notices the
    removal).
    """
    seen: dict[str, None] = {}
    for raw in paths:
        if not raw:
            continue
        p = Path(raw)
        try:
            directory = p if p.is_dir() else p.parent
        except OSError:
            directory = p.parent
        seen.setdefault(str(directory), None)
    return list(seen)


def paths_from_journal(journal) -> list[str]:
    """Every file path a run's journal says it touched.

    Returns the paths themselves, NOT their directories: notify_paths does that
    reduction, once. Deriving here as well would apply it twice, and the second
    pass is not harmless, because a release folder clean has already deleted no
    longer looks like a directory and would walk up to the library root,
    turning a targeted scan into a scan of everything.

    Both ends of a move are reported: the destination gained a file and the
    source lost one, and Plex has to be told about each or the old location
    keeps advertising a file that is gone. Trash and delete say the same thing
    about one side.
    """
    paths: list[str] = []
    for entry in journal or ():
        op = entry.get("op")
        if op == "move":
            paths.extend(p for p in (entry.get("src"), entry.get("dst")) if p)
        elif op in ("trash", "delete"):
            path = entry.get("path")
            if path:
                paths.append(path)
    return paths
