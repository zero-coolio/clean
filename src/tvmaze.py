#!/usr/bin/env python3
"""TVMaze API lookup for show name and year verification.

Ported from lime/TVMazeService.swift.

Usage:
    from .tvmaze import lookup_show, lookup_movie

    result = lookup_show("Top Gear (2002)")
    # → ("Top Gear", "2002") or None

    result = lookup_movie("The Matrix (1999)")
    # → ("The Matrix", "1999") or None
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to",
    "for", "is", "are", "not", "but", "with", "its", "it",
}

_RE_YEAR = re.compile(r"\s*\(((?:19|20)\d{2})\)\s*$")

# CleanMedia-local cache of show name/year verification — sits next to this file.
_CACHE_PATH = Path(__file__).parent / ".tvmaze_cache.json"

# SHARED episode cache, co-owned with the lime project. Keyed by normalized
# show name (see _normalize_show_key) so a Swift app and this Python tool can
# both read/write it without sharing internal ids. Value schema matches lime's
# CachedShowEpisodes: {"episodes": [{season, episode, title, airdate}],
# "fetchedAt": ISO8601}. Lives in user-space app support, resolved via $HOME so
# there is no repo coupling or hardcoded username.
#   ~/Library/Application Support/nulleffect/tvmaze-cache.json
# Overridable via NULLEFFECT_TVMAZE_CACHE (tests and lime honor the same var).
_SHARED_CACHE_PATH = Path(
    os.environ.get(
        "NULLEFFECT_TVMAZE_CACHE",
        str(Path.home() / "Library" / "Application Support" / "nulleffect" / "tvmaze-cache.json"),
    )
)

# In-process cache: query_key → (canonical_name, year) | None
_cache: dict[str, tuple[str, str] | None] = {}
_cache_dirty = False

# query_key → TVMaze show id. Populated by lookup_show on a match and persisted
# to `.tvmaze_id_cache.json` (sibling of `_CACHE_PATH`). Persistence matters for
# the id-based collapse in clean_service: lookup_show early-returns on a warm
# name-cache hit WITHOUT re-deriving the id, so without a persisted id map the
# numeric id would be unavailable in steady state and collapse would no-op.
_id_cache: dict[str, int] = {}
_id_cache_dirty = False
_ID_CACHE_PATH = _CACHE_PATH.parent / ".tvmaze_id_cache.json"

# Shared episode cache, loaded lazily from _SHARED_CACHE_PATH:
#   normalized_show_key → {"episodes": [...], "fetchedAt": "..."}
_episodes_cache: dict[str, dict] | None = None

# Separator/punctuation normalization, ported verbatim from lime's
# LibraryScanner.normalizeSeparators so both projects compute identical keys.
_RE_SEPARATORS = re.compile(r"[._\-:]+")
_RE_WHITESPACE = re.compile(r"\s+")


def _normalize_show_key(name: str) -> str:
    """Normalized cache key shared with lime (normalizeSeparators + lowercase).

    "Hawaii.Five-0 (2010)" -> "hawaii five 0 (2010)"
    "It's Always Sunny"    -> "its always sunny"
    """
    s = _RE_SEPARATORS.sub(" ", name)
    s = s.replace("&", " and ")
    s = s.replace("'", "").replace("’", "").replace("‘", "")
    s = _RE_WHITESPACE.sub(" ", s).strip()
    return s.lower()


def _load_cache() -> None:
    global _cache
    if _CACHE_PATH.exists():
        try:
            raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            # Values are stored as [name, year] or null
            _cache = {k: (tuple(v) if v else None) for k, v in raw.items()}
        except Exception:
            pass


def _save_cache() -> None:
    global _cache_dirty
    if not _cache_dirty:
        return
    try:
        serializable = {k: list(v) if v else None for k, v in _cache.items()}
        _CACHE_PATH.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
        _cache_dirty = False
    except Exception:
        pass


def _load_id_cache() -> None:
    global _id_cache
    if _ID_CACHE_PATH.exists():
        try:
            raw = json.loads(_ID_CACHE_PATH.read_text(encoding="utf-8"))
            _id_cache = {k: int(v) for k, v in raw.items() if v is not None}
        except Exception:
            pass


def _save_id_cache() -> None:
    global _id_cache_dirty
    if not _id_cache_dirty:
        return
    try:
        _ID_CACHE_PATH.write_text(
            json.dumps(_id_cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _id_cache_dirty = False
    except Exception:
        pass


def _load_episodes_cache() -> dict[str, dict]:
    """Return the shared episode cache, loaded from disk ONCE and held in memory.

    Memoized: the first call reads + parses the file; later calls reuse the
    in-memory dict. This is a big deal for performance — a clean run does an
    episode-title lookup per file (thousands), and re-reading/parsing the
    multi-MB cache each time dominated run time. Safe to memoize because lime is
    now a read-only consumer, so CleanMedia is the only writer of this file; our
    own writes keep the in-memory copy current via _save_episodes_cache. Each
    clean run is a fresh process, so it reloads from disk on first use (no
    cross-run staleness).
    """
    global _episodes_cache
    if _episodes_cache is not None:
        return _episodes_cache
    if _SHARED_CACHE_PATH.exists():
        try:
            _episodes_cache = json.loads(_SHARED_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _episodes_cache = {}
    else:
        _episodes_cache = {}
    return _episodes_cache


def _save_episodes_cache(data: dict[str, dict]) -> None:
    """Persist new entries and keep the in-memory cache in sync.

    Updates the memoized in-memory cache so later lookups this run see the new
    entries, then merges into the on-disk file (read-modify-write) so a
    concurrent writer's other-show entries aren't clobbered.
    """
    global _episodes_cache
    if _episodes_cache is not None:
        _episodes_cache.update(data)
    try:
        _SHARED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged: dict = {}
        if _SHARED_CACHE_PATH.exists():
            try:
                merged = json.loads(_SHARED_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                merged = {}
        merged.update(data)
        _SHARED_CACHE_PATH.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


_load_cache()
_load_id_cache()

# Rate limiting
_last_request: float = 0.0
_MIN_INTERVAL = 0.25  # 4 req/s max


def _rate_limit() -> None:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.time()


def _strip_year(name: str) -> str:
    return _RE_YEAR.sub("", name).strip()


def _strip_stopwords(name: str) -> str:
    words = name.split()
    filtered = [w for w in words if w.lower() not in _STOPWORDS]
    return " ".join(filtered).strip()


def _query_variants(name: str) -> list[str]:
    """Return query strings to try in order, mirroring lime's TVMazeService logic."""
    base = _strip_year(name).strip()
    variants: list[str] = []

    amp_to_and = re.sub(r"\s*&\s*", " and ", base)
    and_to_amp = re.sub(r"\band\b", "&", base, flags=re.IGNORECASE)

    if amp_to_and != base:
        variants.append(amp_to_and)
    if and_to_amp != base and and_to_amp not in variants:
        variants.append(and_to_amp)
    if base not in variants:
        variants.append(base)

    stripped = _strip_stopwords(base)
    if stripped and stripped != base and stripped not in variants:
        variants.append(stripped)

    # Last-resort tail fallbacks for long, noisy names where the distinctive
    # title sits at the END after author/initial cruft, e.g.
    # "C S Forester's Horatio Hornblower" → "Horatio Hornblower". Tried LAST
    # (lowest priority) and only for 4+ word names, so they never override a
    # confident full-name match and can't mangle short titles.
    words = base.split()
    if len(words) >= 4:
        for n in (3, 2):
            tail = " ".join(words[-n:])
            if tail not in variants:
                variants.append(tail)

    return variants


def _search(query: str) -> list[dict]:
    _rate_limit()
    encoded = urllib.parse.quote(query)
    url = f"https://api.tvmaze.com/search/shows?q={encoded}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def _sanitize_name(name: str) -> str:
    """Sanitize a show/movie name for safe use as a filesystem path component.

    macOS HFS+ stores colons as '/' internally — a colon in a folder name creates
    nested directories when viewed in Finder.  Replace colon sequences with ' - '
    and strip any other characters that are reserved or problematic on common
    filesystems (HFS+, APFS, NTFS, ext4).
    """
    # Colon → " - " (most common TVMaze culprit)
    name = re.sub(r"\s*:\s*", " - ", name)
    # Forward-slash (path separator) → remove (shouldn't appear but guard anyway)
    name = re.sub(r"/", "", name)
    # Other broadly-reserved characters: \ ? * | " < >
    name = re.sub(r'[\\?*|"<>]', "", name)
    # Collapse any double-spaces left behind
    name = re.sub(r"  +", " ", name).strip()
    return name


def _best_match(results: list[dict], year: str | None) -> tuple[int, str, str] | None:
    """Pick the best result, preferring year match, then highest score.

    Returns (show_id, name, year) or None.
    """
    candidates = []
    for r in results:
        show = r.get("show", {})
        sid = show.get("id")
        name = show.get("name")
        score = r.get("score", 0.0)
        premiered = show.get("premiered") or ""
        if not sid or not name:
            continue
        candidates.append((score, sid, name, premiered[:4] if len(premiered) >= 4 else ""))

    if not candidates:
        return None

    if year:
        year_matches = [(s, i, n, y) for s, i, n, y in candidates if y == year]
        if year_matches:
            best = max(year_matches, key=lambda x: x[0])
            return best[1], best[2], best[3] if best[3] else year

    best = max(candidates, key=lambda x: x[0])
    return best[1], best[2], best[3]


def lookup_show(name: str, logger=None) -> tuple[str, str] | None:
    """Look up a TV show on TVMaze.

    Args:
        name: Show name, optionally with year like "Top Gear (2002)".
        logger: Optional logger for info/warning messages.

    Returns:
        (canonical_name, year) tuple, or None if not found.
    """
    cache_key = name.lower().strip()
    if cache_key in _cache:
        return _cache[cache_key]

    year_m = _RE_YEAR.search(name)
    year = year_m.group(1) if year_m else None

    global _cache_dirty, _id_cache_dirty
    for query in _query_variants(name):
        results = _search(query)
        match = _best_match(results, year)
        if match:
            sid, canonical, found_year = match
            canonical = _sanitize_name(canonical)
            result: tuple[str, str] = (canonical, found_year) if found_year else (canonical, year or "")
            _cache[cache_key] = result
            _cache_dirty = True
            _save_cache()
            _id_cache[cache_key] = sid
            _id_cache_dirty = True
            _save_id_cache()
            if logger:
                logger.info("TVMaze: '%s' → '%s (%s)' (query: '%s')", name, canonical, found_year, query)
            return result

    if logger:
        logger.warning("TVMaze: no match for '%s'", name)
    _cache[cache_key] = None
    _cache_dirty = True
    _save_cache()
    return None


def _resolve_show_id(name: str, logger=None) -> int | None:
    """Resolve a TVMaze show id for a name, using the persisted id cache.

    On a miss, `lookup_show` populates the id as a side effect (network search).
    But `lookup_show` early-returns on a warm NAME-cache hit without re-deriving
    the id — so for names already in `.tvmaze_cache.json` we fall back to a
    direct search to recover and persist the id.
    """
    global _id_cache_dirty
    cache_key = name.lower().strip()
    if cache_key in _id_cache:
        return _id_cache[cache_key]

    # Triggers a network search + id population on a name-cache miss.
    lookup_show(name, logger=logger)
    if cache_key in _id_cache:
        return _id_cache[cache_key]

    # Warm name-cache hit with no recorded id: resolve the id directly.
    year_m = _RE_YEAR.search(name)
    year = year_m.group(1) if year_m else None
    for query in _query_variants(name):
        match = _best_match(_search(query), year)
        if match:
            _id_cache[cache_key] = match[0]
            _id_cache_dirty = True
            _save_id_cache()
            return match[0]
    return None


def _fetch_all_episodes(show_id: int) -> list[dict]:
    """Fetch a show's full episode list from TVMaze.

    Returns a list of {"season", "episode", "title", "airdate"} dicts — the
    same per-episode shape lime stores in the shared cache. One network call
    per show (vs one per episode), so a season pack costs a single request.
    """
    _rate_limit()
    url = f"https://api.tvmaze.com/shows/{show_id}/episodes"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []
    episodes = []
    for ep in data:
        if ep.get("season") is None or ep.get("number") is None:
            continue
        episodes.append({
            "season": ep["season"],
            "episode": ep["number"],
            "title": ep.get("name") or "",
            "airdate": ep.get("airdate") or "",
        })
    return episodes


def _ensure_show_episodes(name: str, logger=None) -> list[dict] | None:
    """Return a show's episode list, from the shared cache or a fresh fetch.

    On a cache miss, resolves the show id, fetches the full episode list, and
    writes it into the shared cache under the normalized name key (lime schema).
    Returns None if the show can't be resolved.
    """
    key = _normalize_show_key(name)
    cache = _load_episodes_cache()
    entry = cache.get(key)
    if entry is not None:
        return entry.get("episodes", [])

    show_id = _resolve_show_id(name, logger=logger)
    if not show_id:
        return None

    episodes = _fetch_all_episodes(show_id)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_episodes_cache({key: {"episodes": episodes, "fetchedAt": fetched_at}})
    if logger:
        logger.info("TVMaze episodes: '%s' → %d episodes cached (key '%s')", name, len(episodes), key)
    return episodes


def lookup_episode_name(
    name: str, season: str | int, episode: str | int, logger=None
) -> str | None:
    """Look up an episode title on TVMaze, via the shared episode cache.

    Best-effort: returns the raw episode title (e.g. "We Don't Fight at
    Weddings") or None if the show or episode can't be resolved. The show's
    full episode list is cached in the shared cache co-owned with lime.

    Args:
        name: Show name, optionally with year like "Letterkenny (2016)".
        season: Season number (int or zero-padded string).
        episode: Episode number (int or zero-padded string).
        logger: Optional logger.
    """
    try:
        s_num = int(season)
        e_num = int(episode)
    except (TypeError, ValueError):
        return None

    episodes = _ensure_show_episodes(name, logger=logger)
    if not episodes:
        return None

    for ep in episodes:
        if ep.get("season") == s_num and ep.get("episode") == e_num:
            title = ep.get("title") or None
            if logger and title:
                logger.info("TVMaze episode: '%s' S%02dE%02d → '%s'", name, s_num, e_num, title)
            return title
    return None


def lookup_movie(name: str, logger=None) -> tuple[str, str] | None:
    """Look up a movie on TVMaze (covers TV movies and mini-series).

    Falls back gracefully — movies are less reliable on TVMaze so this
    is best-effort only.

    Returns:
        (canonical_name, year) or None.
    """
    # TVMaze is TV-focused; reuse show search as best-effort
    return lookup_show(name, logger=logger)


# =============================================================================
# Public helpers for show-id-based collapsing / renumbering (clean_service)
# =============================================================================

def resolve_show_id(name: str, logger=None) -> int | None:
    """Public: the TVMaze numeric show id for a name, or None if unresolved.

    Thin wrapper over `_resolve_show_id` (which populates the in-process id
    cache as a side effect of `lookup_show`). Two different spellings that
    resolve to the same series return the same id — the basis for collapsing
    name-variant folders into one canonical show.
    """
    return _resolve_show_id(name, logger=logger)


def get_show_episodes(name: str, logger=None) -> list[dict] | None:
    """Public: a show's full episode list, or None if the show can't resolve.

    Each entry is ``{"season", "episode", "title", "airdate"}`` in TVMaze's
    own (possibly year-based) season numbering. Served from the shared episode
    cache when present, otherwise one `/shows/{id}/episodes` fetch. Used to
    renumber loosely-parsed / seasonless episodes to TVMaze's actual seasons.
    """
    return _ensure_show_episodes(name, logger=logger)
