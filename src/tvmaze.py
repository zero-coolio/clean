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

# Disk cache path — sits next to this file
_CACHE_PATH = Path(__file__).parent / ".tvmaze_cache.json"

# In-process cache: query_key → (canonical_name, year) | None
_cache: dict[str, tuple[str, str] | None] = {}
_cache_dirty = False


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


_load_cache()

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


def _best_match(results: list[dict], year: str | None) -> tuple[str, str] | None:
    """Pick the best result, preferring year match, then highest score."""
    candidates = []
    for r in results:
        show = r.get("show", {})
        sid = show.get("id")
        name = show.get("name")
        score = r.get("score", 0.0)
        premiered = show.get("premiered") or ""
        if not sid or not name:
            continue
        candidates.append((score, name, premiered[:4] if len(premiered) >= 4 else ""))

    if not candidates:
        return None

    if year:
        year_matches = [(s, n, y) for s, n, y in candidates if y == year]
        if year_matches:
            best = max(year_matches, key=lambda x: x[0])
            return best[1], best[2] if best[2] else year

    best = max(candidates, key=lambda x: x[0])
    return best[1], best[2]


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

    global _cache_dirty
    for query in _query_variants(name):
        results = _search(query)
        match = _best_match(results, year)
        if match:
            canonical, found_year = match
            result: tuple[str, str] = (canonical, found_year) if found_year else (canonical, year or "")
            _cache[cache_key] = result
            _cache_dirty = True
            _save_cache()
            if logger:
                logger.info("TVMaze: '%s' → '%s (%s)' (query: '%s')", name, canonical, found_year, query)
            return result

    if logger:
        logger.warning("TVMaze: no match for '%s'", name)
    _cache[cache_key] = None
    _cache_dirty = True
    _save_cache()
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
