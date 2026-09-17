#!/usr/bin/env python3
"""Clean Movie Service - Organizes movie files into a clean directory structure.

Parses movie filenames to extract title and year, then moves files to:
    <root>/<Movie Title> (Year)/<Movie Title> (Year).<ext>

Handles sidecars (subtitles), deletes junk files (samples, images, RAR),
and cleans up empty directories.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from ..config import (
    VIDEO_EXT,
    SUBTITLE_EXT,
    MOVIE_DELETE_EXT,
    QUALITY_MARKERS,
    get_logger,
)
from ..utils import normalize_unicode_separators, strip_noise_prefix
from ..intake_filter import is_season_dir, movie_needs_processing
from ..title_signal import describe_mismatch, folder_may_name_file
from .base import BaseCleanService


# Optional TMDB API support
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")


# Movie parsing patterns
# Match year followed by quality indicators to avoid matching years in titles like "2001"
RE_MOVIE_YEAR = re.compile(
    r"^(?P<title>.+?)"
    r"[.\s_(-]"
    r"(?P<year>(?:19|20)\d{2})"
    r"(?:[).\s_-]|$)",
    re.IGNORECASE,
)

RE_MOVIE_PAREN_YEAR = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>(?:19|20)\d{2})\)",
    re.IGNORECASE,
)


def clean_movie_title(raw_title: str) -> str:
    """Clean up a raw movie title.
    
    Converts dots/underscores to spaces, removes quality markers,
    and normalizes whitespace.
    
    Args:
        raw_title: Raw title string from filename.
        
    Returns:
        Cleaned, title-cased movie title.
    """
    # Replace dots and underscores with spaces
    title = re.sub(r"[._]+", " ", raw_title)
    
    # Remove quality markers
    for marker in QUALITY_MARKERS:
        title = re.sub(rf"\b{marker}\b", "", title, flags=re.IGNORECASE)
    
    # Remove release group patterns
    title = re.sub(r"\s*-\s*[A-Za-z0-9]+$", "", title)
    title = re.sub(r"\s*\[[^\]]+\]$", "", title)
    
    # Normalize whitespace
    title = re.sub(r"\s+", " ", title).strip()
    
    # Title case (preserve short acronyms like FBI, CIA)
    words = title.split()
    result = []
    for word in words:
        if word.isupper() and len(word) <= 4:
            result.append(word)
        else:
            result.append(word.title())
    
    return " ".join(result)


def parse_movie_from_string(s: str) -> tuple[str, str] | None:
    """Parse movie information from a filename or folder name.
    
    Handles common patterns:
    - Movie.Name.Year.Quality... (dotted format)
    - Movie Name (Year) (clean format)
    
    Args:
        s: Filename or folder name to parse.
        
    Returns:
        Tuple of (title, year) or None if unparseable.
    """
    name = normalize_unicode_separators(strip_noise_prefix(s))
    name_no_ext = Path(name).stem
    
    # Try parenthesized year first: "Movie Name (2024)"
    match = RE_MOVIE_PAREN_YEAR.search(name_no_ext)
    if match:
        raw_title = match.group("title")
        year = match.group("year")
        title = clean_movie_title(raw_title)
        return title, year
    
    # Try dotted/spaced format: "Movie.Name.2024.1080p..."
    match = RE_MOVIE_YEAR.search(name_no_ext)
    if match:
        raw_title = match.group("title")
        year = match.group("year")
        title = clean_movie_title(raw_title)
        return title, year
    
    return None


# ============================================================================
# TMDB API Support with Rate Limiting
# ============================================================================

# Disk cache path — sits next to this file, mirrors the TVMaze cache pattern
_TMDB_CACHE_PATH = Path(__file__).parent / ".tmdb_cache.json"

# In-process cache: query_key → (clean_title, year) | None
_tmdb_cache: dict[str, tuple[str, str] | None] = {}
_tmdb_last_request: float = 0
_TMDB_MIN_INTERVAL = 0.25  # 4 requests per second max


def _load_tmdb_cache() -> None:
    """Load the persisted TMDB cache from disk into the in-process cache."""
    global _tmdb_cache
    if _TMDB_CACHE_PATH.exists():
        try:
            raw = json.loads(_TMDB_CACHE_PATH.read_text(encoding="utf-8"))
            # Values are stored as [title, year] or null
            _tmdb_cache = {k: (tuple(v) if v else None) for k, v in raw.items()}
        except Exception:
            pass


def _save_tmdb_cache() -> None:
    """Persist the in-process TMDB cache to disk (best-effort)."""
    try:
        serializable = {k: list(v) if v else None for k, v in _tmdb_cache.items()}
        _TMDB_CACHE_PATH.write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


_load_tmdb_cache()


def lookup_movie_year(title: str, logger=None) -> tuple[str, str] | None:
    """Look up a movie's year from TMDB API.

    Results (including negative results) are cached in-process and persisted to
    disk so repeated runs don't re-hit the API for titles already seen.

    Includes rate limiting to avoid hitting API limits.

    Args:
        title: Movie title to search for.
        logger: Optional logger for status messages.

    Returns:
        Tuple of (clean_title, year) or None if not found.
    """
    global _tmdb_last_request

    if not REQUESTS_AVAILABLE or not TMDB_API_KEY:
        return None

    # Check cache
    cache_key = title.lower().strip()
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]

    # Rate limiting
    elapsed = time.time() - _tmdb_last_request
    if elapsed < _TMDB_MIN_INTERVAL:
        time.sleep(_TMDB_MIN_INTERVAL - elapsed)

    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "query": title,
            "include_adult": "false",
        }
        response = requests.get(url, params=params, timeout=5)
        _tmdb_last_request = time.time()
        response.raise_for_status()
        data = response.json()

        if data.get("results"):
            movie = data["results"][0]
            movie_title = movie.get("title", title)
            release_date = movie.get("release_date", "")
            if release_date:
                year = release_date[:4]
                result = (movie_title, year)
                _tmdb_cache[cache_key] = result
                _save_tmdb_cache()
                if logger:
                    logger.info("TMDB LOOKUP: '%s' -> '%s (%s)'", title, movie_title, year)
                return result

        _tmdb_cache[cache_key] = None
        _save_tmdb_cache()
        return None

    except Exception as e:
        if logger:
            logger.debug("TMDB lookup failed for '%s': %s", title, e)
        _tmdb_cache[cache_key] = None
        _save_tmdb_cache()
        return None


# ============================================================================
# Movie Service
# ============================================================================


# Matches TV episode markers (S01E01, 1x01) and season packs (standalone S01)
_RE_TV_IN_NAME = re.compile(
    r"(?:^|[\s._\-\(])S\d{1,2}(?:E\d{1,2}|(?:[\s._\-\(]|$))",
    re.IGNORECASE,
)


class CleanMovieService(BaseCleanService):
    """Service to clean and organize movie files."""

    SERVICE_NAME = "clean-movie"

    def _needs_processing(self, rel_path) -> bool:
        """Structural work selection for the movie layout. See intake_filter."""
        return movie_needs_processing(rel_path)

    def _folder_fallback_allowed(self, path: Path, folder_name: str) -> bool:
        """Refuse a folder title that contradicts the filename. See title_signal.

        The movie parser only succeeds on a name containing a year, so every
        yearless file reaches the folder fallback — including files that are
        plainly some other film, parked in a folder by hand. Renaming those
        destroys the one piece of evidence about what they actually are, so they
        stay put and get reported instead.
        """
        if folder_may_name_file(path.stem, folder_name):
            return True
        self._logger.warning(
            "REFUSE FOLDER TITLE: %s — filename disagrees with '%s' (%s)",
            path, folder_name, describe_mismatch(path.stem, folder_name),
        )
        return False

    def __init__(self) -> None:
        super().__init__(get_logger("clean-movie"))
        self._use_tmdb_lookup = False

    def process_file(self, path, root, commit, journal, quarantine, unexpected, dest=None):
        """Skip files already organized into TV Season folders, warn on TV-looking content."""
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        if any(is_season_dir(part) for part in rel.parts):
            return

        # Warn and skip if filename or any ancestor folder looks like TV content
        names_to_check = [path.stem] + [p for p in rel.parts[:-1]]
        for name in names_to_check:
            if _RE_TV_IN_NAME.search(name):
                self._logger.warning(
                    "SKIP (looks like TV content): %s — move to TV library manually", path
                )
                return

        super().process_file(path, root, commit, journal, quarantine, unexpected, dest)
    
    # =========================================================================
    # Abstract method implementations
    # =========================================================================
    
    def parse_media_info(self, name: str) -> tuple[str, str] | None:
        """Parse movie info from a filename or folder name."""
        return parse_movie_from_string(name)
    
    def build_video_dest(self, root: Path, parsed: tuple[str, str], ext: str) -> Path:
        """Build destination path for a video file.
        
        Format: <root>/<Movie Title> (Year)/<Movie Title> (Year).<ext>
        """
        title, year = parsed
        folder_name = f"{title} ({year})"
        filename = f"{title} ({year}){ext.lower()}"
        return root / folder_name / filename
    
    def build_sidecar_dest(self, root: Path, parsed: tuple[str, str], original_name: str) -> Path:
        """Build destination path for a sidecar file.
        
        Preserves language tags from the original filename.
        """
        title, year = parsed
        folder_name = f"{title} ({year})"
        
        # Extract language/type suffix from original name
        stem = Path(original_name).stem.lower()
        ext = Path(original_name).suffix.lower()
        
        # Language groups - prefer longer/more specific matches
        # Order matters: check longer variants first to avoid partial matches
        lang_groups = [
            # English variants (check longer first)
            (".english", "eng"),
            (".eng", "eng"),
            (".en.", "eng"),  # Only match .en. to avoid false positives
            # Spanish variants
            (".spanish", "spa"),
            (".spa", "spa"),
            (".es.", "spa"),
            # French variants
            (".french", "fre"),
            (".fre", "fre"),
            (".fr.", "fre"),
            # German variants
            (".german", "ger"),
            (".ger", "ger"),
            (".de.", "ger"),
        ]
        
        # Modifiers (can appear alongside language)
        modifiers = [".forced", ".sdh", ".cc", ".hi"]
        
        found_lang = None
        found_modifiers = []
        
        # Check for language
        for pattern, normalized in lang_groups:
            if pattern in f".{stem}.":
                found_lang = normalized
                break
        
        # Check for modifiers
        for mod in modifiers:
            if mod in f".{stem}.":
                found_modifiers.append(mod.strip("."))
        
        # Build suffix
        suffix_parts = []
        if found_lang:
            suffix_parts.append(found_lang)
        suffix_parts.extend(found_modifiers)
        
        if suffix_parts:
            filename = f"{title} ({year}).{'.'.join(suffix_parts)}{ext}"
        else:
            filename = f"{title} ({year}){ext}"
        
        return root / folder_name / filename
    
    def is_clean_folder_name(self, folder_name: str) -> bool:
        """Check if folder follows 'Movie Title (Year)' format."""
        return bool(re.match(r"^.+\s+\(\d{4}\)$", folder_name))
    
    def is_release_folder_name(self, folder_name: str) -> bool:
        """Detect release/wrapper folders with quality tags, codecs, etc."""
        bad_patterns = [
            r"\d{3,4}p",
            r"(WEB-?DL|WEBRip|BluRay|BDRip|HDRip|DVDRip)",
            r"(x264|x265|h264|h265|HEVC)",
            r"\[.*\]$",
            r"-[A-Z0-9]+$",
            r"(YIFY|YTS|RARBG|TGx)",
        ]
        for pat in bad_patterns:
            if re.search(pat, folder_name, re.IGNORECASE):
                return True
        return False
    
    def get_video_extensions(self) -> frozenset[str]:
        return VIDEO_EXT
    
    def get_sidecar_extensions(self) -> frozenset[str]:
        return SUBTITLE_EXT
    
    def get_delete_extensions(self) -> frozenset[str]:
        return MOVIE_DELETE_EXT
    
    # =========================================================================
    # Overrides for TMDB lookup support
    # =========================================================================
    
    def _try_parse_media(self, path: Path, root: Path) -> tuple[str, str] | None:
        """Try to parse media info, with TVMaze verify, then optional TMDB fallback."""
        parsed = super()._try_parse_media(path, root)

        if parsed:
            title, year = parsed
            title, year = self._imdb_verify(title, year)
            return title, year

        # If TMDB lookup is enabled and this is a video file, try API
        if self._use_tmdb_lookup and path.suffix.lower() in VIDEO_EXT:
            raw_name = Path(path.name).stem
            clean_name = clean_movie_title(raw_name)
            return lookup_movie_year(clean_name, self._logger)

        return None

    def _imdb_verify(self, title: str, year: str) -> tuple[str, str]:
        """Canonicalize a movie title/year via IMDb (movies only, strict gate).

        Returns the IMDb ``(title, year)`` only on a confident exact-title,
        year-matched movie hit; otherwise returns the ORIGINAL name unchanged.
        Never matches a TV series, so a movie can't be renamed onto the wrong
        title (the failure that lost files under the old TVMaze verify).
        """
        try:
            from ..imdb import resolve_movie
            result = resolve_movie(title, year or None, logger=self._logger)
            if result:
                canonical, found_year = result
                return canonical, (found_year or year)
        except Exception as e:
            self._logger.debug("IMDb verify failed for '%s': %s", title, e)
        return title, year
    
    def run(
        self,
        root: Path,
        commit: bool = False,
        plan: bool = False,
        quarantine: Path | None = None,
        lookup: bool = False,
        dest: Path | None = None,
        since_seconds: float | None = None,
        structural: bool = False,
    ) -> None:
        """Run the movie cleaning process.

        Args:
            root: Root directory to scan for files.
            commit: If True, apply changes. If False, dry-run.
            plan: If True, write journal even in dry-run mode.
            quarantine: Optional path to move samples instead of deleting.
            lookup: If True, use TMDB API to look up missing years.
            dest: Optional separate destination root (e.g. seagate-movie)
                  when scanning a shared download directory.
            since_seconds: Optional incremental window (seconds); only files
                  modified within it are processed. None processes everything.
            structural: Select files by path shape instead of mtime. Overrides
                  since_seconds. See _needs_processing / intake_filter.
        """
        self._use_tmdb_lookup = lookup
        # Keywords, not positionals: this override shadows a 7-argument base
        # signature, and the two lists have already drifted once.
        super().run(
            root=root,
            commit=commit,
            plan=plan,
            quarantine=quarantine,
            dest=dest,
            since_seconds=since_seconds,
            structural=structural,
        )
    
    # =========================================================================
    # Legacy compatibility methods
    # =========================================================================
    
    @staticmethod
    def build_dest(root: Path, title: str, year: str, ext: str) -> Path:
        """Build destination path (static method for backwards compatibility)."""
        folder_name = f"{title} ({year})"
        filename = f"{title} ({year}){ext.lower()}"
        return root / folder_name / filename

    @staticmethod
    def _is_clean_folder_name(folder_name: str) -> bool:
        """Static method for backwards compatibility."""
        return bool(re.match(r"^.+\s+\(\d{4}\)$", folder_name))

    @staticmethod
    def _is_release_folder_name(folder_name: str) -> bool:
        """Static method for backwards compatibility."""
        bad_patterns = [
            r"\d{3,4}p",
            r"(WEB-?DL|WEBRip|BluRay|BDRip|HDRip|DVDRip)",
            r"(x264|x265|h264|h265|HEVC)",
            r"\[.*\]$",
            r"-[A-Z0-9]+$",
            r"(YIFY|YTS|RARBG|TGx)",
        ]
        for pat in bad_patterns:
            if re.search(pat, folder_name, re.IGNORECASE):
                return True
        return False
