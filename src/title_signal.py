#!/usr/bin/env python3
"""Compare the identity a filename claims against the one its folder claims.

One job: given a file's stem and its containing folder's title, decide whether
the folder is allowed to name this file. No filesystem, no clock, no network.

The filename is the stronger signal. `_try_parse_media` already tries the
filename before the folder, but the movie parser only succeeds when it finds a
YEAR, and a yearless filename returns None, at which point the folder supplies
a title for a file that already told us it is something else. Two real cases in
seagate-movie on 2026-09-17, both of which a full run would have renamed:

    Eater's Guide to the World (2020)/Dr Who Joy To The World.mkv
        -> Eater'S Guide To The World (2020).mkv
    Nanyobi ni umareta no (2023)/the curse of the were-rabbit.avi
        -> Nanyobi Ni Umareta No (2023).avi

A Doctor Who special and a Wallace & Gromit film, each about to be relabelled
as whatever it happened to be sitting next to, with the original name destroyed
in the process. The folder was never evidence about these files; it was just
where someone dropped them.

So the folder may name a file only when the filename does not contradict it:
either the stem carries no identity of its own ("movie.mkv", "2_English.srt",
"Ad.Astra.mkv" beside an Ad Astra folder), or it shares enough of the folder's
words to be plausibly the same work. Otherwise we refuse, the file stays put
under its original name, and it is reported as unparsed for a human to look at.
Refusing costs a log line. Guessing costs the filename.

SCOPE: movies only, and deliberately so. TV filenames legitimately carry an
episode title that shares nothing with the show name
("Reacher.S04E01.City.of.Brotherly.Love.mkv"), so this comparison would reject
correct fallbacks wholesale. See CleanMovieService._folder_fallback_allowed.
"""
from __future__ import annotations

import re

from .config import QUALITY_MARKERS

# Words that carry no identity, so their presence or absence proves nothing.
# Stopwords matter more than they look: "Dr Who Joy To The World" and "Eater's
# Guide to the World" share "to", "the" and "world", which is enough to look
# like a 50% match until the first two are dropped.
_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with", "s", "part", "vol", "volume",
})

# Generic placeholder names a release uses for its payload. A stem made only of
# these is saying nothing, which is exactly when the folder SHOULD name it.
_GENERIC = frozenset({
    "movie", "film", "video", "title", "main", "feature", "movies",
    "vts", "vob", "disc", "disk", "cd", "cd1", "cd2", "dvd", "bluray",
})

# Sidecar language names, for the same reason: "Subs/2_English.srt" is a
# subtitle track, not a claim to be a film called "English".
_LANGUAGES = frozenset({
    "english", "eng", "en", "spanish", "spa", "es", "french", "fre", "fr",
    "german", "ger", "de", "italian", "ita", "it", "portuguese", "por", "pt",
    "dutch", "nld", "nl", "russian", "rus", "ru", "japanese", "jpn", "ja",
    "chinese", "chi", "zh", "korean", "kor", "ko", "forced", "sdh", "cc", "hi",
    "subs", "subtitles", "sub", "multi",
})

# QUALITY_MARKERS are unanchored substrings, and some are two letters ("TS",
# "TC", "DV", "CAM"). Spliced together unanchored they match inside ordinary
# words: "TS" ate the middle of "VTS_01_1" leaving "V", and would reduce
# "Ghosts" to "Ghos". Require a non-alphanumeric boundary on both sides.
_RE_QUALITY = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(QUALITY_MARKERS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# A trailing release-group tag: "-RARBG", "-V3SP4EV3R", "-GROUP". Requires
# upper case, because a lowercase trailing word is part of the title. An
# any-case pattern ate the "rabbit" off "the curse of the were-rabbit".
_RE_RELEASE_GROUP = re.compile(r"-[A-Z0-9]{2,}$")
_RE_BRACKETED = re.compile(r"[\[(][^\])]*[\])]")
_RE_WORD = re.compile(r"[a-z0-9]+")

# How much of the filename's identity must also appear in the folder's title
# for the folder to be believed. Tuned against the two real failures above
# (0.25 and 0.0) and the legitimate fallbacks they sit among (1.0).
FALLBACK_OVERLAP_THRESHOLD = 0.5


def meaningful_tokens(text: str) -> set[str]:
    """Reduce a filename stem or folder title to the words that identify it.

    Strips bracketed segments, quality markers, years, a trailing release-group
    tag, then drops stopwords, generic payload names and language tags.

    Args:
        text: A filename stem or folder name (no extension needed).

    Returns:
        The identifying words, lowercased. Empty means "claims no identity".
    """
    s = _RE_BRACKETED.sub(" ", text)
    s = _RE_RELEASE_GROUP.sub(" ", s)
    s = _RE_QUALITY.sub(" ", s)
    s = _RE_YEAR.sub(" ", s)
    s = s.replace(".", " ").replace("_", " ").replace("-", " ")
    words = _RE_WORD.findall(s.lower())
    # Bare numbers are track indices, disc numbers and part numbers
    # ("Subs/2_English.srt", "cd2"), never identity. This does mean a
    # numerically-titled film ("300", "1917") claims no identity of its own and
    # lets its folder name it, which is the right outcome in its own folder and
    # a tolerable one in the rare case it is misfiled.
    return {w for w in words if not w.isdigit()
            and w not in _STOPWORDS
            and w not in _GENERIC
            and w not in _LANGUAGES}


def folder_may_name_file(file_stem: str, folder_name: str) -> bool:
    """True if `folder_name` is allowed to supply the title for `file_stem`.

    Args:
        file_stem: The file's name without its extension.
        folder_name: The containing folder's name.

    Returns:
        True when the filename claims no identity of its own, or claims one
        consistent with the folder. False when the filename names something
        else, in which case the caller must not rename the file.
    """
    file_tokens = meaningful_tokens(file_stem)
    if not file_tokens:
        # The filename says nothing, so the folder is the only signal there is.
        return True

    folder_tokens = meaningful_tokens(folder_name)
    if not folder_tokens:
        return True

    shared = file_tokens & folder_tokens
    return (len(shared) / len(file_tokens)) >= FALLBACK_OVERLAP_THRESHOLD


def describe_mismatch(file_stem: str, folder_name: str) -> str:
    """A log-ready reason a fallback was refused, naming the disagreeing words."""
    file_tokens = meaningful_tokens(file_stem)
    folder_tokens = meaningful_tokens(folder_name)
    shared = file_tokens & folder_tokens
    ratio = len(shared) / len(file_tokens) if file_tokens else 1.0
    return (
        f"filename claims {sorted(file_tokens)}, folder claims "
        f"{sorted(folder_tokens)}, overlap {ratio:.2f} < {FALLBACK_OVERLAP_THRESHOLD}"
    )
