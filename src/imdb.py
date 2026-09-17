#!/usr/bin/env python3
"""IMDb-backed movie title/year resolution.

Replaces the old TVMaze-based movie "verification", which was the root of the
wrong-movie renames that lost files: TVMaze is a TV database, so movies matched
whatever TV show scored least-badly ("Take Shelter" -> "Hello Kitty's Furry
Tale Theater"), then collided and got dedup-deleted.

Source: IMDb's public, keyless search-suggestion endpoint
    https://v3.sg.media-imdb.com/suggestion/<bucket>/<query>.json
which returns real IMDb entries including a type field (`qid`) that lets us
keep ONLY movies and reject TV series.

The gate is deliberately strict — a delete-capable groomer must never rename a
movie onto the wrong title:
  * movie types only (`movie` / `tvMovie` / `video`), never `tvSeries` etc.
  * the candidate's normalized title must EQUAL the query's, and
  * when a year is known, the candidate's year must be within +/- 1.
On anything less than a confident match it returns None, and the caller keeps
the original name (safe: no wrong rename, no delete).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Persisted, so repeat runs don't re-hit IMDb. Sits next to the other caches.
_CACHE_PATH = Path(__file__).parent / ".imdb_cache.json"
_cache: dict[str, tuple[str, str] | None] = {}
_cache_dirty = False

_last_request = 0.0
_MIN_INTERVAL = 0.34   # be polite to the endpoint

# IMDb `qid` values that count as a movie. Everything else (tvSeries,
# tvMiniSeries, tvEpisode, tvSpecial, short, musicVideo, videoGame, ...) is
# rejected so a movie can never be renamed onto a TV title.
_MOVIE_TYPES = {"movie", "tvMovie", "video"}

_RE_ARTICLE = re.compile(r"^(the|a|an)\s+")


def _normalize_keep_article(title: str) -> str:
    """Lowercase, fold '&'->'and', drop punctuation. Keeps a leading article."""
    t = title.lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _normalize(title: str) -> str:
    """Lowercase, fold '&'->'and', drop punctuation, strip a leading article.

    Article-insensitive on purpose: a release named "Matrix.1999.mkv" should
    still resolve to "The Matrix". But an article is not always noise, and two
    real films can differ by one ("State of Grace" 1990 and "A State of Grace"
    2000), so callers must not treat a match here as proof of identity on its
    own. See resolve_movie, which demands an exact year when the articles
    disagree.
    """
    return _RE_ARTICLE.sub("", _normalize_keep_article(title))


def _load_cache() -> None:
    global _cache
    if _CACHE_PATH.exists():
        try:
            raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            _cache = {k: (tuple(v) if v else None) for k, v in raw.items()}
        except Exception:
            pass


def _save_cache() -> None:
    global _cache_dirty
    if not _cache_dirty:
        return
    try:
        serializable = {k: (list(v) if v else None) for k, v in _cache.items()}
        _CACHE_PATH.write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _cache_dirty = False
    except Exception:
        pass


def _fetch(title: str) -> list[dict]:
    """Return IMDb suggestion entries for a title (empty on any error)."""
    q = title.strip()
    if not q:
        return []
    bucket = next((c.lower() for c in q if c.isalnum()), "x")
    url = (
        f"https://v3.sg.media-imdb.com/suggestion/{bucket}/"
        f"{urllib.parse.quote(q)}.json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []
    return data.get("d", []) or []


def _movie_candidates(entries: list[dict]) -> list[tuple[str, str, str]]:
    """(normalized_title, display_title, year) for movie-typed title entries."""
    out: list[tuple[str, str, str]] = []
    for e in entries:
        if not str(e.get("id", "")).startswith("tt"):   # tt = title (nm = person)
            continue
        if e.get("qid") not in _MOVIE_TYPES:
            continue
        label = e.get("l") or ""
        year = e.get("y")
        out.append((_normalize(label), label, str(year) if year else ""))
    return out


def resolve_movie(title: str, year: str | None = None, logger=None):
    """Resolve a movie to its canonical IMDb ``(title, year)``, or None.

    Strict: only an exact normalized-title movie match is accepted, and when a
    year is supplied, only if the candidate's year is close enough. Returns None
    (caller keeps the original name) on anything less certain.

    "Close enough" depends on the article. _normalize is article-insensitive so
    a release named "Matrix.1999" finds "The Matrix", but an article can also be
    the only thing separating two real films, so a candidate whose article
    differs from the query must match the year EXACTLY. Same-title candidates
    keep the +/- 1 window that absorbs festival-vs-release drift.
    """
    global _last_request, _cache_dirty

    key = f"{_normalize(title)}|{year or ''}"
    if key in _cache:
        return _cache[key]

    delta = time.time() - _last_request
    if delta < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - delta)
    entries = _fetch(title)
    _last_request = time.time()

    q_norm = _normalize(title)
    q_full = _normalize_keep_article(title)
    exact = [c for c in _movie_candidates(entries) if c[0] == q_norm]

    chosen: tuple[str, str] | None = None
    if exact:
        if year:
            try:
                target = int(year)
            except ValueError:
                yclose = []
            else:
                # The +/- 1 window absorbs festival-vs-release year drift, but
                # it may only do so for a candidate whose title matches article
                # and all. _normalize is article-insensitive so that
                # "Matrix.1999" finds "The Matrix", and that same leniency let
                # "A State of Grace" (2000) answer a query for "State of Grace"
                # (2001): two different films, one rename, exactly what this
                # gate exists to prevent. When the articles disagree, the year
                # must match exactly.
                yclose = [
                    c for c in exact
                    if c[2] and abs(int(c[2]) - target) <= (
                        1 if _normalize_keep_article(c[1]) == q_full else 0
                    )
                ]
            if yclose:
                chosen = (yclose[0][1], yclose[0][2])
            # exact title but no year-close candidate → ambiguous (a different
            # same-title film); stay None rather than guess.
        else:
            # No year to disambiguate: take IMDb's top-ranked exact-title movie
            # and adopt its year.
            chosen = (exact[0][1], exact[0][2])

    _cache[key] = chosen
    _cache_dirty = True
    _save_cache()
    if logger and chosen:
        logger.info("IMDb: '%s (%s)' → '%s (%s)'", title, year or "?", chosen[0], chosen[1])
    return chosen


_load_cache()
