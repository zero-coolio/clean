"""Compare two titles for identity, and say when a query claims no identity.

One job: normalize titles so "Matrix.1999" and "The Matrix" compare equal, and
decide whether a query is substantive enough to be worth asking a database
about at all.

Extracted from imdb.py (CLEAN-19) because the IMDb path had a strict
exact-title gate and the TMDB path had none. `lookup_movie_year` took
`results[0]` with no title comparison whatsoever, which is how these happened
in one archive preview:

    "spider-man"  -> Spider-Man: Brand New Day (2026)   (an unreleased film)
    "Extra-1"     -> His Cat: Extra Chapter 1 (2020)
    "Extra-2"     -> Initial D: Extra Stage 2 (2008)
    "Untitled"    -> (Untitled) (2009)

Two separate defences, and both are needed:

1. `is_substantive` refuses to ask at all when the query says nothing. A bare
   placeholder, a placeholder plus an ordinal, or a lone generic word cannot
   identify a film, and a search engine asked an empty question still answers.
2. `titles_match` requires the answer to BE the question. A database's
   best-effort fuzzy match is not evidence of identity, and this is a
   delete-capable groomer.
"""
from __future__ import annotations

import re

_RE_ARTICLE = re.compile(r"^(the|a|an)\s+")

# Stems that are a label for "the payload", not a claim about which film it is.
# "Untitled.m4v" inside "The Thing (1982)" is The Thing; "Extra-1.mkv" inside a
# Green Lantern folder is a Green Lantern extra. Asking a database about either
# string gets a confident, wrong film.
PLACEHOLDER_WORDS = frozenset({
    "untitled", "unknown", "unnamed", "none", "null", "temp", "tmp", "output",
    "extra", "extras", "bonus", "featurette", "featurettes", "special",
    "specials", "deleted", "scene", "scenes", "interview", "interviews",
    "making", "behind", "menu", "intro", "outro", "credits", "trailer",
    "teaser", "preview", "sample", "clip", "segment", "chapter", "track",
    "movie", "film", "video", "title", "main", "feature", "features",
    "episode", "episodes", "part", "parts", "reel", "vts",
})

_RE_WORD = re.compile(r"[a-z0-9]+")


# Apostrophes are never word separators in a title, so they are DELETED rather
# than blanked. Blanking them split "Miller's Crossing" into "miller s
# crossing", which then failed to equal a release named "Millers Crossing" and
# lost a correct match. Covers the straight and both curly forms.
_RE_APOSTROPHE = re.compile(r"['\u2018\u2019\u02bc`]")


def normalize_keep_article(title: str) -> str:
    """Lowercase, fold '&'->'and', drop apostrophes, blank other punctuation.

    Keeps a leading article.
    """
    t = title.lower().replace("&", " and ")
    t = _RE_APOSTROPHE.sub("", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize(title: str) -> str:
    """Lowercase, fold '&'->'and', drop punctuation, strip a leading article.

    Article-insensitive on purpose: a release named "Matrix.1999.mkv" should
    still resolve to "The Matrix". But an article is not always noise, and two
    real films can differ by one ("State of Grace" 1990 and "A State of Grace"
    2000), so callers must not treat a match here as proof of identity on its
    own. See imdb.resolve_movie, which demands an exact year when the articles
    disagree.
    """
    return _RE_ARTICLE.sub("", normalize_keep_article(title))


def titles_match(query: str, candidate: str) -> bool:
    """True when `candidate` is the same title as `query`, article aside.

    Deliberately exact after normalization. A fuzzy near-match is what renamed
    a Doctor Who special onto "Eater's Guide to the World", so "close" does not
    count as evidence here.
    """
    return bool(query) and normalize(query) == normalize(candidate)


def is_substantive(title: str) -> bool:
    """True when `title` claims an identity worth asking a database about.

    False for a query that cannot possibly identify a film:
      * nothing left after normalization ("", "---", "01")
      * every remaining word is a placeholder ("Untitled", "Extra 1",
        "Deleted Scenes", "Bonus Features")
      * a single word that is itself generic ("Movie", "Feature")

    A real one-word title ("Snatch", "Watchmen", "Monolith") is substantive:
    the word has to be in PLACEHOLDER_WORDS to disqualify it, not merely short.
    """
    words = _RE_WORD.findall(normalize_keep_article(title))
    if not words:
        return False

    named = [w for w in words if not w.isdigit()]
    if not named:
        # Purely numeric. Three or more digits is a real title ("300", "1917",
        # "2012"); one or two is an index ("1.mkv" among Lexx's extras,
        # "01" from a boxset rip), and its folder is the thing that knows what
        # it is. Short numeric titles exist ("13") and are given up on purpose:
        # being named by the enclosing folder is the right outcome for them
        # anyway, and is free of a wrong TMDB match.
        return any(len(w) >= 3 for w in words)

    return any(w not in PLACEHOLDER_WORDS for w in named)
