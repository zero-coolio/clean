#!/usr/bin/env python3
"""Clean TV Service - Organizes TV episodes into a clean directory structure.

Parses episode filenames to extract show name, season, and episode numbers,
then moves files to:
    <root>/<Show Name>/Season <SS>/<Show.Name.SxxExx.<ext>
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from ..config import VIDEO_EXT, JUNK_EXT, TV_SIDECAR_EXT, get_logger
from ..utils import normalize_unicode_separators, strip_noise_prefix
from .base import BaseCleanService

# Show-level rename hint: "Old Show Name==New Show Name"
_RE_RENAME_HINT = re.compile(r"^(?P<from>.+?)\s*==\s*(?P<to>.+)$")

# Season-level rename hint: "Season 09==New Show Name (Year)"
_RE_SEASON_RENAME_HINT = re.compile(
    r"^Season\s+(?P<season>\d+)\s*==\s*(?P<to>.+)$", re.IGNORECASE
)

# Extracts SxxExx from a filename as a fallback
_RE_EPISODE_IN_NAME = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,2})")


# Episode parsing patterns
RE_SXXEYY = re.compile(
    r"^(?P<show>.*?)[.\s\-_]*S(?P<season>\d{1,2})[.\s\-_]*E(?P<episode>\d{1,2})",
    re.IGNORECASE,
)
RE_X = re.compile(
    r"^(?P<show>.*?)[.\s\-_]*(?P<season>\d{1,2})[xX](?P<episode>\d{1,2})",
    re.IGNORECASE,
)
# "Season 2 Episode 5" format (spelled out)
RE_SEASON_EPISODE = re.compile(
    r"^(?P<show>.*?)[.\s\-_]*Season[.\s\-_]*(?P<season>\d{1,2})[.\s\-_]*Episode[.\s\-_]*(?P<episode>\d{1,2})",
    re.IGNORECASE,
)

# Scene "compact code" format: a standalone 3- or 4-digit token where the
# digits are season+episode concatenated, e.g.
#   Hawaii.Five-0.2010.713.hdtv-lol   -> S07E13   (3 digits: S=7,  E=13)
#   South.Park.1314.HDTV.x264          -> S13E14   (4 digits: S=13, E=14)
# The token must be delimited on both sides so it can't grab the trailing "0"
# in "Five-0", a resolution like "1080p"/"720p", or a codec like "x264".
_RE_COMPACT_TOKEN = re.compile(r"(?:^|[.\s_\-])(\d{3,4})(?=[.\s_\-]|$)")


def _parse_compact_code(name: str) -> tuple[str, str, str, int] | None:
    """Last-resort parse for the scene compact-code episode format.

    Scans for standalone 3-4 digit tokens, skips anything that looks like a
    release year (19xx/20xx), and treats the first remaining token as the
    season+episode code. Returns (raw_show, season, episode, end_index) where
    end_index is the offset just past the code token, or None if no usable
    token is found.

    Note: a genuine S20E10 would encode as "2010" and is indistinguishable
    from a year, so it is (deliberately) skipped — years are far more common
    than 20+ season shows, and misclassifying a year as an episode is worse.
    """
    for m in _RE_COMPACT_TOKEN.finditer(name):
        tok = m.group(1)
        if len(tok) == 4 and re.fullmatch(r"(?:19|20)\d{2}", tok):
            continue  # release year, not an episode code
        if len(tok) == 3:
            season, episode = tok[0], tok[1:]
        else:
            season, episode = tok[:2], tok[2:]
        if int(episode) == 0:
            continue  # "100" -> E00 etc. is not a real episode
        raw_show = name[: m.start(1)]
        return raw_show, season, episode, m.end(1)
    return None


# Seasonless "bare episode number" format used by miniseries / TV-film runs:
#   Horatio Hornblower 03 The Duchess And The Devil 480p  -> S01E03
# A leading zero ("03") is REQUIRED: it's the signal that distinguishes an
# episode number from a number baked into a show title ("Studio 60",
# "Catch 22", "Apollo 13"), which are essentially never zero-padded. The token
# must be delimited on both sides. Season is assumed to be 01 (Plex/Jellyfin
# treat seasonless miniseries as Season 01). Consequence: episodes >= 10 (no
# leading zero) are deliberately NOT matched here, to avoid false positives.
RE_BARE_EPISODE = re.compile(
    r"^(?P<show>.*?)[.\s_\-]+(?P<episode>0\d)(?=[.\s_\-])",
)


def _parse_bare_episode(name: str) -> tuple[str, str, str, int] | None:
    """Last-resort parse for the seasonless bare-episode-number format."""
    m = RE_BARE_EPISODE.search(name)
    if not m:
        return None
    return m.group("show"), "01", m.group("episode"), m.end("episode")


# A spurious SxxExx that a *prior* clean run appended AFTER quality/release
# tags, e.g. "Horatio.Hornblower.03.The.Duchess.480P.H.S02E64". Left in place it
# wins the parse (RE_SXXEYY) and swallows the whole junk string as the "show".
# Only stripped when a real bare-episode number can still be recovered from the
# remainder (the poison signal) — so a legitimate trailing SxxExx is never lost.
_RE_TRAILING_SXXEXX = re.compile(r"[.\s_\-]+s\d{1,2}e\d{1,2}\s*$", re.IGNORECASE)

# Known media / sidecar extensions, stripped before parsing so a trailing
# ".mkv" can't pollute the episode-title hint or block the poison-strip's
# end-anchor. Restricted to a known set so folder names like "...S06" (no real
# extension) are never truncated.
_RE_MEDIA_EXT = re.compile(
    r"\.(mkv|mp4|avi|m4v|mov|wmv|flv|ts|mpg|mpeg|webm|srt|sub|idx|ass|ssa|vtt|nfo|txt)$",
    re.IGNORECASE,
)

# Release/quality noise; used to trim an episode-title hint down to real words.
_RE_QUALITY_NOISE = re.compile(
    r"(?i)[.\s_\-]+("
    r"\d{3,4}p|web[.\s_\-]?dl|webrip|hdtv|blu[.\s_\-]?ray|bdrip|hdrip|dvdrip|web|"
    r"x26[45]|h[.\s_\-]?26[45]|hevc|xvid|aac\d?|ac3|dd[.\s_\-]?5[.\s_\-]?1|"
    r"proper|repack|internal|complete|extended|remastered|\[[^\]]*\]|-[a-z0-9]+"
    r")\b.*$"
)


class ParsedEpisode(NamedTuple):
    """Richer parse result used for TVMaze id-collapse + renumbering."""
    show: str
    season: str
    episode: str
    title_hint: str   # episode-title text recovered from the name ("" if none)
    seasonless: bool  # True when the season was *guessed* (bare-episode form)


def _clean_show_name(raw_show: str, remainder: str) -> str:
    """Title-case + year-normalize a raw show fragment (shared parse logic)."""
    show = re.sub(r"[._\-]+", " ", raw_show).strip()
    show = re.sub(r"\s+", " ", show).title()
    # Normalize bare year to parenthesized form: "Show Name 2002" → "Show Name (2002)"
    show = re.sub(r"\s+((?:19|20)\d{2})$", r" (\1)", show)
    # If no year in the show name, check the remainder (e.g. Show.S01E01.(2002).mkv)
    if not re.search(r"(?:19|20)\d{2}", show):
        year_match = re.search(r"[(\s._\-]((?:19|20)\d{2})[)\s._\-]", remainder)
        if year_match:
            show = f"{show} ({year_match.group(1)})"
    return show


def _has_real_show_text(show: str) -> bool:
    """True when `show` has actual title text beyond a year and punctuation.

    Guards against filing under a show folder named only after a year (e.g.
    "(2016)"), which happens when an episode filename STARTS with SxxExx and the
    real show name lives only in the parent folder. A show whose entire name is
    just a 19xx/20xx year is treated as "no real name" (vanishingly rare for TV,
    and the caller falls back to the parent folder rather than mis-filing).
    """
    if not show:
        return False
    residue = re.sub(r"\(?(?:19|20)\d{2}\)?", "", show)   # drop year (± parens)
    residue = re.sub(r"[^0-9A-Za-z]", "", residue)         # drop spaces/punctuation
    return bool(residue)


def _title_hint_from_remainder(remainder: str) -> str:
    """Recover a human episode title from the text after the episode marker,
    dropping quality/release noise. Returns '' when nothing meaningful remains."""
    t = _RE_QUALITY_NOISE.sub("", remainder)
    t = re.sub(r"[._\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .-_")
    # Drop a leading bare year token left over from "Show 1998 Title" remainders.
    t = re.sub(r"^(?:19|20)\d{2}\b\s*", "", t).strip()
    return t.title() if t else ""


def parse_episode_detail(s: str) -> ParsedEpisode | None:
    """Parse TV episode info, carrying an episode-title hint + a seasonless flag.

    Handles the same patterns as before:
    - Show.Name.S01E02...
    - Show Name - 1x02 - Episode Title
    - Show Name Season 2 Episode 5
    - Show.Name.2010.713.hdtv-lol  (scene compact code: S07E13)
    - Horatio Hornblower 03 Title 480p  (seasonless bare episode → guessed S01)

    Plus: strips a spurious trailing SxxExx left by an earlier mis-parse (see
    `_RE_TRAILING_SXXEXX`) so poisoned bare-episode files parse correctly.
    """
    name = normalize_unicode_separators(strip_noise_prefix(_RE_MEDIA_EXT.sub("", s)))

    # Drop a spurious trailing SxxExx appended after quality tags, but ONLY when
    # a real bare-episode number survives in the remainder (the poison signal).
    stripped = _RE_TRAILING_SXXEXX.sub("", name)
    if stripped != name and _parse_bare_episode(stripped) is not None:
        name = stripped

    match = RE_SXXEYY.search(name) or RE_X.search(name) or RE_SEASON_EPISODE.search(name)
    seasonless = False
    if match:
        raw_show = match.group("show")
        season = match.group("season")
        episode = match.group("episode")
        match_end = match.end()
    else:
        # Looser fallbacks only when the explicit forms miss: scene compact code
        # (which carries a real season) first, then the seasonless bare number.
        compact = _parse_compact_code(name)
        if compact:
            raw_show, season, episode, match_end = compact
        else:
            bare = _parse_bare_episode(name)
            if not bare:
                return None
            raw_show, season, episode, match_end = bare
            seasonless = True   # season was assumed to be 01

    remainder = name[match_end:]
    show = _clean_show_name(raw_show, remainder)
    title_hint = _title_hint_from_remainder(remainder)
    return ParsedEpisode(show, season.zfill(2), episode.zfill(2), title_hint, seasonless)


def parse_episode_from_string(s: str) -> tuple[str, str, str] | None:
    """Back-compat 3-tuple wrapper over `parse_episode_detail`.

    Returns (show_name, season, episode) — zero-padded — or None.
    """
    d = parse_episode_detail(s)
    return None if d is None else (d.show, d.season, d.episode)


def _normalize_title(t: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy matching."""
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _match_episode_by_title(ordered: list[dict], hint: str) -> dict | None:
    """Find the TVMaze episode whose title best matches a folder title hint.

    Tries exact / substring containment first (handles "The Duchess and the
    Devil" inside "Hornblower: The Duchess and the Devil"), then a token-overlap
    fallback gated at 60% so a weak hint can't grab the wrong episode.
    """
    h = _normalize_title(hint)
    if not h:
        return None
    for ep in ordered:
        et = _normalize_title(ep.get("title", ""))
        if et and (h == et or h in et or et in h):
            return ep
    hw = set(h.split())
    best, best_score = None, 0.0
    for ep in ordered:
        ew = set(_normalize_title(ep.get("title", "")).split())
        if not ew:
            continue
        score = len(hw & ew) / max(len(hw), 1)
        if score > best_score:
            best, best_score = ep, score
    return best if best_score >= 0.6 else None


def episode_title_suffix(title: str) -> str:
    """Format an episode title into a dotted, filesystem-safe filename segment.

    "We Don't Fight at Weddings" -> "We.Don't.Fight.at.Weddings"
    Strips characters illegal on common filesystems, converts whitespace runs
    to single dots, and collapses repeated dots. Returns "" for an empty title.
    """
    if not title:
        return ""
    t = re.sub(r'[\\/:*?"<>|]', "", title)   # illegal path chars
    t = re.sub(r"\s+", ".", t.strip())        # whitespace -> dots
    t = re.sub(r"\.+", ".", t).strip(".")     # collapse runs of dots
    return t


class CleanService(BaseCleanService):
    """Service to clean and organize TV show files."""

    SERVICE_NAME = "clean-tv"

    def __init__(self) -> None:
        super().__init__(get_logger("clean-tv"))
        # Per-run cache: bare show name (lower) → canonical "Show (Year)" string
        self._show_canonical: dict[str, str] = {}
        # Per-run cache: TVMaze show id → canonical "Show (Year)" string. The
        # FIRST spelling to resolve a given id sets the canonical name; every
        # other spelling that resolves to the same id reuses it, so name-variant
        # folders (e.g. "Horatio Hornblower" and "C S Forester's Horatio
        # Hornblower") collapse into one show folder.
        self._id_canonical: dict[int, str] = {}

    # =========================================================================
    # Folder rename hints  (FolderName==NewName)
    # =========================================================================

    def _before_run(self, root: Path, commit: bool, journal: list) -> None:
        """Apply folder rename hints before the main walk.

        Two hint styles are supported:

        Show-level:  "Old Show==New Show (Year)"
            Renames all files inside from Old.Show → New.Show.(Year) then
            renames/merges the folder to "New Show (Year)".

        Season-level:  "Season 09==New Show (Year)"  (inside any show folder)
            Rebuilds each file's name using the new show and the existing
            episode number, then renames the Season folder back to "Season 09".
            clean-tv's normal pass then routes files to the correct show folder.
        """
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue

            # Show-level hint
            m = _RE_RENAME_HINT.match(entry.name)
            if m and not _RE_SEASON_RENAME_HINT.match(entry.name):
                self._apply_show_rename(
                    entry, root,
                    m.group("from").strip(), m.group("to").strip(),
                    commit, journal,
                )
                continue

            # Season-level hints inside this show folder
            for season_entry in sorted(entry.iterdir()):
                if not season_entry.is_dir():
                    continue
                sm = _RE_SEASON_RENAME_HINT.match(season_entry.name)
                if sm:
                    self._apply_season_rename(
                        season_entry,
                        sm.group("season").zfill(2),
                        sm.group("to").strip(),
                        commit, journal,
                    )

    def _apply_show_rename(
        self,
        entry: Path,
        root: Path,
        from_name: str,
        to_name: str,
        commit: bool,
        journal: list,
    ) -> None:
        """Apply a show-level rename hint."""
        from_words = re.split(r"[\s._]+", from_name)
        from_re = re.compile(
            r"[\s._]*".join(re.escape(w) for w in from_words),
            re.IGNORECASE,
        )
        to_dot = re.sub(r"\s+", ".", to_name)

        self._logger.info("RENAME HINT: '%s' -> '%s'", from_name, to_name)

        for file in sorted(entry.rglob("*")):
            if not file.is_file():
                continue
            new_name = from_re.sub(to_dot, file.name)
            if new_name != file.name:
                new_path = file.parent / new_name
                self._logger.info("RENAME FILE: %s -> %s", file.name, new_name)
                if commit:
                    file.rename(new_path)
                journal.append({"op": "move", "src": str(file), "dst": str(new_path)})

        target = root / to_name
        if target.exists() and target != entry:
            self._logger.warning("RENAME HINT: target '%s' exists, merging contents", to_name)
            for child in sorted(entry.iterdir()):
                dest_child = target / child.name
                if not dest_child.exists():
                    self._logger.info("MERGE: %s -> %s", child, dest_child)
                    if commit:
                        child.rename(dest_child)
                    journal.append({"op": "move", "src": str(child), "dst": str(dest_child)})
                elif child.is_dir():
                    for grandchild in sorted(child.iterdir()):
                        dest_gc = dest_child / grandchild.name
                        if not dest_gc.exists():
                            self._logger.info("MERGE FILE: %s -> %s", grandchild.name, dest_gc)
                            if commit:
                                grandchild.rename(dest_gc)
                            journal.append({"op": "move", "src": str(grandchild), "dst": str(dest_gc)})
                        else:
                            self._logger.warning("MERGE SKIP (exists): %s", dest_gc)
                    if commit:
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                else:
                    self._logger.warning("MERGE SKIP (exists): %s", dest_child)
            if commit:
                try:
                    entry.rmdir()
                except OSError:
                    pass
        else:
            self._logger.info("RENAME FOLDER: '%s' -> '%s'", entry.name, to_name)
            if commit:
                entry.rename(target)
            journal.append({"op": "move", "src": str(entry), "dst": str(target)})

    def _apply_season_rename(
        self,
        season_entry: Path,
        season_num: str,
        to_name: str,
        commit: bool,
        journal: list,
    ) -> None:
        """Apply a season-level rename hint.

        Rebuilds each file as <to_name_dot>.S<season>E<episode>.<ext>,
        extracting the episode number from the existing filename.
        Then renames the Season folder back to "Season <season_num>".
        The normal clean-tv pass will then route files to the right show folder.
        """
        to_dot = re.sub(r"\s+", ".", to_name)
        self._logger.info(
            "SEASON RENAME HINT: Season %s -> '%s'", season_num, to_name
        )

        for file in sorted(season_entry.iterdir()):
            if not file.is_file():
                continue

            # Try structured parse first, fall back to raw SxxExx search
            parsed = parse_episode_from_string(file.stem)
            if parsed:
                episode = parsed[2]
            else:
                ep_m = _RE_EPISODE_IN_NAME.search(file.name)
                if not ep_m:
                    self._logger.warning(
                        "SEASON RENAME SKIP (no episode number): %s", file.name
                    )
                    continue
                episode = ep_m.group(2).zfill(2)

            new_name = f"{to_dot}.S{season_num}E{episode}{file.suffix.lower()}"
            if new_name != file.name:
                new_path = file.parent / new_name
                self._logger.info("RENAME FILE: %s -> %s", file.name, new_name)
                if commit:
                    file.rename(new_path)
                journal.append({"op": "move", "src": str(file), "dst": str(new_path)})

        # Rename the Season folder back (strip the hint)
        target_season = season_entry.parent / f"Season {season_num}"
        if target_season != season_entry:
            self._logger.info(
                "RENAME FOLDER: '%s' -> 'Season %s'", season_entry.name, season_num
            )
            if commit:
                season_entry.rename(target_season)
            journal.append({"op": "move", "src": str(season_entry), "dst": str(target_season)})

    # =========================================================================
    # Abstract method implementations
    # =========================================================================

    def _try_parse_media(self, path: Path, root: Path) -> tuple | None:
        """Parse media info, enrich with year from folder, then verify via TVMaze.

        Returns a 4-tuple (show, season, episode, title); title is "" when no
        episode name could be resolved.
        """
        detail = self._parse_detail(path)
        if detail is None:
            return None
        show, season, episode = detail.show, detail.season, detail.episode
        if not re.search(r"(?:19|20)\d{2}", show):
            show = self._resolve_show_with_year(show, root)
        show = self._canonical_show(show, season, episode)
        # Renumber to TVMaze's actual seasons (e.g. seasonless / flattened
        # anthologies → year-based seasons). No-op when the parsed pair is
        # already a real TVMaze episode.
        season, episode = self._remap_episode_via_tvmaze(show, season, episode, detail)
        title = self._episode_title(show, season, episode)
        return show, season, episode, title

    def _parse_detail(self, path: Path) -> ParsedEpisode | None:
        """Parse (with title hint + seasonless flag) from filename, then parent,
        then a Subs/ grandparent — mirroring the base resolution order.

        Special case: when the filename parses to a valid season/episode but an
        empty / year-only show name (the file STARTS with SxxExx and the show
        name lives in the parent folder, e.g. parent "Bull - S01 E01-23 (2017)"
        with files "S01E08 ...mkv"), keep the filename's per-file episode
        numbering but borrow the show NAME from the parent. Falling back to the
        parent parse wholesale would be wrong — the parent's own SxxExx range
        yields E01 for every file and collapses them. And never accept a
        year-only name: better to skip (log unparsed) than create a "(2016)"
        show folder.
        """
        from ..config import SUBS_FOLDER_NAMES

        file_detail = parse_episode_detail(path.name)
        if file_detail and _has_real_show_text(file_detail.show):
            return file_detail

        parent_detail = parse_episode_detail(path.parent.name)
        if file_detail is not None:
            # Filename had episode numbering but no real name — take the name
            # from the parent if it has one; otherwise skip rather than mis-file.
            if parent_detail and _has_real_show_text(parent_detail.show):
                return file_detail._replace(show=parent_detail.show)
            return None

        # Filename didn't parse at all — fall back to parent, then Subs grandparent.
        if parent_detail and _has_real_show_text(parent_detail.show):
            return parent_detail
        if path.parent.name.lower() in SUBS_FOLDER_NAMES and len(path.parents) >= 2:
            gp = parse_episode_detail(path.parents[1].name)
            if gp and _has_real_show_text(gp.show):
                return gp
        return None

    def _remap_episode_via_tvmaze(
        self, show: str, season: str, episode: str, detail: ParsedEpisode
    ) -> tuple[str, str]:
        """Remap (season, episode) onto TVMaze's real numbering for `show`.

        Strategy, in order:
          1. If the parsed pair is already a real TVMaze episode → keep it
             (the common case; a no-op for normal, correctly-numbered files).
          2. Match the folder's episode-title hint against TVMaze titles.
          3. Sequential-index fallback: treat the episode number as a 1-based
             index into the TVMaze-ordered episode list. Applies to seasonless
             bare-episode parses, and to flattened "Season 01" files when the
             show has no real season 1 on TVMaze (year-based seasons).

        Anything unresolved is left exactly as parsed and logged loudly.
        """
        try:
            from ..tvmaze import get_show_episodes
            eps = get_show_episodes(show, logger=self._logger)
        except Exception as e:
            self._logger.debug("Renumber: episode fetch failed for '%s': %s", show, e)
            return season, episode
        if not eps:
            return season, episode

        s_num, e_num = int(season), int(episode)

        # 1. Already a genuine TVMaze episode — trust the explicit numbering.
        if any(ep["season"] == s_num and ep["episode"] == e_num for ep in eps):
            return season, episode

        ordered = sorted(eps, key=lambda ep: (ep["season"], ep["episode"]))

        # 2. Title match (robust against reordered / alternate numbering).
        if detail.title_hint:
            m = _match_episode_by_title(ordered, detail.title_hint)
            if m:
                self._logger.info(
                    "Renumber '%s' S%sE%s → S%02dE%02d via title '%s' (TVMaze '%s')",
                    show, season, episode, m["season"], m["episode"],
                    detail.title_hint, m.get("title", ""))
                return f"{m['season']:02d}", f"{m['episode']:02d}"

        # 3. Sequential-index fallback.
        tvmaze_has_season_1 = any(ep["season"] == 1 for ep in ordered)
        index_eligible = detail.seasonless or (s_num == 1 and not tvmaze_has_season_1)
        if index_eligible and 1 <= e_num <= len(ordered):
            m = ordered[e_num - 1]
            self._logger.info(
                "Renumber '%s' S%sE%s → S%02dE%02d via sequential index (#%d of %d)",
                show, season, episode, m["season"], m["episode"], e_num, len(ordered))
            return f"{m['season']:02d}", f"{m['episode']:02d}"

        self._logger.warning(
            "Renumber: '%s' S%sE%s not found in TVMaze (%d eps) and no confident "
            "match — keeping as-is", show, season, episode, len(ordered))
        return season, episode

    def _episode_title(self, show: str, season: str, episode: str) -> str:
        """Best-effort episode title from TVMaze; "" if unavailable."""
        try:
            from ..tvmaze import lookup_episode_name
            title = lookup_episode_name(show, season, episode, logger=self._logger)
            return title or ""
        except Exception as e:
            self._logger.debug(
                "Episode title lookup failed for '%s' S%sE%s: %s", show, season, episode, e
            )
            return ""

    def _canonical_show(self, show: str, season: str, episode: str) -> str:
        """Return the canonical show name, consistent across all episodes in this run.

        The bare show name (without year) is used as the key so that files
        parsed with and without a year all resolve to the same canonical string.
        """
        bare = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", show).strip().lower()

        if bare in self._show_canonical:
            return self._show_canonical[bare]

        # TVMaze lookup, keyed by show id so name-variants collapse.
        try:
            from ..tvmaze import lookup_show, resolve_show_id
            result = lookup_show(show, logger=self._logger)
            if result:
                canonical, year = result
                verified = f"{canonical} ({year})" if year else canonical
                sid = resolve_show_id(show, logger=self._logger)
                if sid is not None:
                    if sid in self._id_canonical:
                        # Another spelling already owns this show id — collapse.
                        chosen = self._id_canonical[sid]
                        if chosen != verified:
                            self._logger.info(
                                "TVMaze id-collapse: '%s' → '%s' (show id %d)",
                                show, chosen, sid)
                        verified = chosen
                    else:
                        self._id_canonical[sid] = verified
                if verified.lower() != show.lower():
                    self._logger.info("TVMaze verify: '%s' → '%s'", show, verified)
                self._show_canonical[bare] = verified
                return verified
        except Exception as e:
            self._logger.debug("TVMaze verify failed for '%s': %s", show, e)

        self._show_canonical[bare] = show
        return show

    def _resolve_show_with_year(self, show: str, root: Path) -> str:
        """Return show name with year if a matching versioned folder exists in root."""
        if not root.is_dir():
            return show
        pattern = re.compile(
            r"^" + re.escape(show) + r"\s*\(?((?:19|20)\d{2})\)?$",
            re.IGNORECASE,
        )
        for entry in root.iterdir():
            if entry.is_dir():
                m = pattern.match(entry.name)
                if m:
                    return f"{show} ({m.group(1)})"
        return show

    def parse_media_info(self, name: str) -> tuple[str, str, str] | None:
        """Parse episode info from a filename or folder name."""
        return parse_episode_from_string(name)
    
    def build_video_dest(self, root: Path, parsed: tuple, ext: str) -> Path:
        """Build destination path for a video file.

        Format: <root>/<Show Name>/Season <SS>/<Show.Name.SxxExx[.Episode.Title].<ext>
        `parsed` may be a 3-tuple (show, season, episode) or a 4-tuple that also
        carries the episode title.
        """
        show, season, episode = parsed[0], parsed[1], parsed[2]
        title = parsed[3] if len(parsed) > 3 else ""
        return self.build_dest(root, show, season, episode, ext, title)

    def build_sidecar_dest(self, root: Path, parsed: tuple, original_name: str) -> Path:
        """Build destination path for a sidecar file.

        Sidecars use the same base name as the video file (including the
        episode title, so media servers keep them paired).
        """
        show, season, episode = parsed[0], parsed[1], parsed[2]
        title = parsed[3] if len(parsed) > 3 else ""
        ext = Path(original_name).suffix
        return self.build_dest(root, show, season, episode, ext, title)
    
    def is_clean_folder_name(self, folder_name: str) -> bool:
        """Check if folder follows 'Season XX' format."""
        return bool(re.match(r"^Season\s+\d{2}$", folder_name, re.IGNORECASE))
    
    def is_release_folder_name(self, folder_name: str) -> bool:
        """Detect release/wrapper folders with quality tags, codecs, etc."""
        bad_patterns = [
            r"\d{3,4}p",
            r"(WEB-?DL|WEBRip|BluRay|BDRip|HDRip)",
            r"(x264|x265|h264|h265|HEVC)",
            r"\[.*\]$",
            r"-[A-Z0-9]+$",
        ]
        for pat in bad_patterns:
            if re.search(pat, folder_name, re.IGNORECASE):
                return True
        return False
    
    def get_video_extensions(self) -> frozenset[str]:
        return VIDEO_EXT
    
    def get_sidecar_extensions(self) -> frozenset[str]:
        return TV_SIDECAR_EXT
    
    def get_delete_extensions(self) -> frozenset[str]:
        return JUNK_EXT
    
    # =========================================================================
    # Legacy compatibility methods
    # =========================================================================
    
    @staticmethod
    def build_dest(root: Path, show: str, season: str, episode: str, ext: str, title: str = "") -> Path:
        """Build destination path. Appends the episode title after SxxExx when given.

        e.g. Letterkenny.(2016).S05E01.We.Don't.Fight.at.Weddings.mkv
        """
        show_folder = show.strip() or "Unknown Show"
        season_folder = root / show_folder / f"Season {season}"
        base_show = re.sub(r"\s+", ".", show_folder)
        # Collapse dot runs so a dotted show name ("C.S. Forester's …") doesn't
        # yield "C.S..Forester's" once spaces become dots.
        base_show = re.sub(r"\.+", ".", base_show)
        suffix = episode_title_suffix(title)
        title_part = f".{suffix}" if suffix else ""
        filename = f"{base_show}.S{season}E{episode}{title_part}{ext.lower()}"
        return season_folder / filename

    @staticmethod
    def build_sidecar_target(root: Path, show: str, season: str, episode: str, name: str, title: str = "") -> Path:
        """Build sidecar path (static method for backwards compatibility)."""
        ext = Path(name).suffix
        return CleanService.build_dest(root, show, season, episode, ext, title)
    
    def undo_from_journal(self, journal_path: Path) -> None:
        """Undo operations from a journal file (legacy method name)."""
        self.undo(journal_path)
