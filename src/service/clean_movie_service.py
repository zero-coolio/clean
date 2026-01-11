#!/usr/bin/env python3
"""Clean Movie Service - Organizes movie files into a clean directory structure.

Parses movie filenames to extract title and year, then moves files to:
    <root>/<Movie Title> (Year)/<Movie Title> (Year).<ext>

Handles sidecars (subtitles, NFO), deletes junk files (samples, images, RAR),
and cleans up empty directories.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Optional TMDB API support
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

LOGGER = logging.getLogger("clean-movie")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
if not LOGGER.handlers:
    LOGGER.addHandler(_handler)
else:
    LOGGER.handlers.clear()
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)


VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv"}
SUBTITLE_EXT = {".srt", ".sub", ".idx", ".vtt", ".ass", ".ssa"}  # Actual subtitle formats
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
AUX_DELETE = {".ds_store", ".rar", ".r00", ".r01", ".sfv", ".nzb", ".par2", ".srr", ".nfo", ".txt"}

SAMPLE_PATTERNS = ("sample", "proof", "trailer")

# Subdirectory names that contain subtitles
SUBS_FOLDER_NAMES = {"subs", "subtitles", "sub"}

# Common release group patterns and quality markers to strip
QUALITY_MARKERS = [
    r"2160p", r"1080p", r"720p", r"480p", r"4K", r"UHD",
    r"BluRay", r"BDRip", r"BRRip", r"WEB-?DL", r"WEBRip", r"HDRip",
    r"DVDRip", r"DVDSCR", r"CAM", r"TS", r"TC", r"HDTV",
    r"x264", r"x265", r"H\.?264", r"H\.?265", r"HEVC", r"AVC",
    r"AAC", r"AC3", r"DTS", r"DD5\.?1", r"FLAC", r"Atmos",
    r"REMUX", r"PROPER", r"REPACK", r"EXTENDED", r"UNRATED",
    r"DIRECTORS\.?CUT", r"THEATRICAL", r"IMAX",
    r"10bit", r"HDR", r"HDR10", r"DV", r"DoVi",
]

NOISE_PREFIX_PATTERNS = [
    r"^www\.UIndex\.org\s*-\s*",
    r"^\[?(?:tgx|rartv|rarbg|eztv|yts|yify|eztv\.re)\]?\s*",
    r"^www\.",
]

# Release group pattern (typically at the end: -GROUP or [GROUP])
RELEASE_GROUP_PATTERN = r"[-\[]?[A-Za-z0-9]+$"


def normalize_unicode_separators(s: str) -> str:
    """Normalize unicode dashes and spaces."""
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_noise_prefix(name: str) -> str:
    """Remove common torrent site prefixes."""
    s = normalize_unicode_separators(name)
    for pat in NOISE_PREFIX_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return s.lstrip()


def is_english_subtitle(name: str) -> bool:
    """Return True if a subtitle filename looks like English."""
    lower = name.lower()

    if not any(lower.endswith(ext) for ext in (".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx")):
        return False

    # Filenames that are just "English.srt" or start with "English"
    stem = Path(name).stem.lower()
    if stem in ("english", "eng", "en"):
        return True
    if stem.startswith("english") or stem.startswith("eng.") or stem.startswith("en."):
        return True
    
    # SDH/HI English subtitles like "SDH.eng.HI.srt"
    if "eng" in stem or "english" in stem:
        return True

    markers = [
        ".en.", ".eng.", ".english.",
        "_en.", "_eng.", "-en.", "-eng.",
        "(en)", "[en]", "(eng)", "[eng]",
        " english",
    ]

    for m in markers:
        if m in lower:
            return True

    if lower.endswith(".en.srt") or lower.endswith(".eng.srt") or lower.endswith(".english.srt"):
        return True

    return False


# Movie parsing patterns
# Pattern 1: Movie.Name.Year.Quality... or Movie Name (Year)
RE_MOVIE_YEAR = re.compile(
    r"^(?P<title>.+?)"
    r"[\.\s\-_\(]"
    r"(?P<year>(?:19|20)\d{2})"
    r"[\)\.\s\-_]",
    re.IGNORECASE,
)

# Pattern 2: Just year in parentheses at the end
RE_MOVIE_PAREN_YEAR = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>(?:19|20)\d{2})\)",
    re.IGNORECASE,
)


def parse_movie_from_string(s: str) -> Optional[Tuple[str, str]]:
    """Parse a movie filename/folder name to extract title and year.
    
    Returns:
        Tuple of (title, year) or None if unparseable.
    """
    name = normalize_unicode_separators(strip_noise_prefix(s))
    
    # Remove file extension if present
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


def clean_movie_title(raw_title: str) -> str:
    """Clean up a raw movie title.
    
    Converts dots/underscores to spaces, removes quality markers,
    and normalizes whitespace.
    """
    # Replace dots and underscores with spaces
    title = re.sub(r"[._]+", " ", raw_title)
    
    # Remove any quality markers that might have slipped in
    for marker in QUALITY_MARKERS:
        title = re.sub(rf"\b{marker}\b", "", title, flags=re.IGNORECASE)
    
    # Remove release group patterns
    title = re.sub(r"\s*-\s*[A-Za-z0-9]+$", "", title)
    title = re.sub(r"\s*\[[^\]]+\]$", "", title)
    
    # Normalize whitespace
    title = re.sub(r"\s+", " ", title).strip()
    
    # Title case (but preserve all-caps acronyms like "FBI")
    words = title.split()
    result = []
    for word in words:
        if word.isupper() and len(word) <= 4:
            result.append(word)
        else:
            result.append(word.title())
    
    return " ".join(result)


# Cache for TMDB lookups to avoid repeated API calls
_tmdb_cache: dict[str, Optional[Tuple[str, str]]] = {}


def lookup_movie_year(title: str) -> Optional[Tuple[str, str]]:
    """Look up a movie's year from TMDB API.
    
    Args:
        title: Movie title to search for.
        
    Returns:
        Tuple of (clean_title, year) or None if not found.
    """
    if not REQUESTS_AVAILABLE or not TMDB_API_KEY:
        return None
    
    # Check cache first
    cache_key = title.lower().strip()
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    
    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "query": title,
            "include_adult": "false",
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("results"):
            # Take the first result
            movie = data["results"][0]
            movie_title = movie.get("title", title)
            release_date = movie.get("release_date", "")
            if release_date:
                year = release_date[:4]
                result = (movie_title, year)
                _tmdb_cache[cache_key] = result
                LOGGER.info("TMDB LOOKUP: '%s' -> '%s (%s)'", title, movie_title, year)
                return result
        
        _tmdb_cache[cache_key] = None
        return None
        
    except Exception as e:
        LOGGER.debug("TMDB lookup failed for '%s': %s", title, e)
        _tmdb_cache[cache_key] = None
        return None


class CleanMovieService:
    """Service to clean and organize movie files."""
    
    def __init__(self) -> None:
        self._logger = LOGGER
        self._source_folders: set[Path] = set()

    # ------------------- Helpers -------------------
    @staticmethod
    def sha1sum(path: Path, limit_bytes: int = 1024 * 1024) -> str:
        """Compute SHA1 hash of first N bytes of a file."""
        h = hashlib.sha1()
        with path.open("rb") as f:
            h.update(f.read(limit_bytes))
        return h.hexdigest()

    def same_content(self, a: Path, b: Path) -> bool:
        """Check if two files have the same size and partial hash."""
        try:
            return a.stat().st_size == b.stat().st_size and self.sha1sum(a) == self.sha1sum(b)
        except Exception:
            return False

    @staticmethod
    def same_path(a: Path, b: Path) -> bool:
        """Check if two paths resolve to the same location."""
        try:
            return a.resolve() == b.resolve()
        except Exception:
            return str(a.absolute()) == str(b.absolute())

    @staticmethod
    def unique_path(p: Path) -> Path:
        """Generate a unique path by appending (alt N) if path exists."""
        if not p.exists():
            return p
        base = p.stem
        ext = p.suffix
        i = 1
        while True:
            alt = p.with_name(f"{base} (alt{'' if i == 1 else f' {i}'}){ext}")
            if not alt.exists():
                return alt
            i += 1

    @staticmethod
    def safe_move(src: Path, dst: Path, commit: bool, journal: List[dict]) -> None:
        """Safely move a file, using copy+delete if rename fails."""
        if dst.exists():
            raise FileExistsError(f"Destination exists: {dst}")
        if not commit:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dst)
        except OSError:
            with src.open("rb") as rf, dst.open("wb") as wf:
                shutil.copyfileobj(rf, wf)
            src.unlink(missing_ok=True)
        journal.append({"op": "move", "src": str(src), "dst": str(dst)})

    @staticmethod
    def safe_delete(path: Path, commit: bool, journal: List[dict]) -> None:
        """Safely delete a file or directory."""
        if not commit:
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        journal.append({"op": "delete", "path": str(path)})

    @staticmethod
    def build_dest(root: Path, title: str, year: str, ext: str) -> Path:
        """Build the canonical destination path for a movie file.

        Movies are placed under:
            <root>/<Movie Title> (Year)/<Movie Title> (Year)<ext>

        Example:
            /media/Movies/The Matrix (1999)/The Matrix (1999).mkv
        """
        folder_name = f"{title} ({year})"
        filename = f"{title} ({year}){ext.lower()}"
        return root / folder_name / filename

    @staticmethod
    def build_sidecar_dest(root: Path, title: str, year: str, original_name: str) -> Path:
        """Build the destination path for a sidecar file.
        
        Sidecars keep their language/type suffix but use the movie naming.
        Example: Movie.eng.srt -> Movie Title (Year).eng.srt
        """
        folder_name = f"{title} ({year})"
        
        # Extract language/type suffix from original name
        # e.g., "movie.eng.srt" -> "eng.srt", "movie.forced.eng.srt" -> "forced.eng.srt"
        original_lower = original_name.lower()
        ext = Path(original_name).suffix.lower()
        
        # Check for language tags
        lang_suffixes = [
            ".eng", ".en", ".english",
            ".spa", ".es", ".spanish",
            ".fre", ".fr", ".french",
            ".ger", ".de", ".german",
            ".forced", ".sdh", ".cc",
        ]
        
        suffix_parts = []
        stem = Path(original_name).stem
        for lang in lang_suffixes:
            if lang in stem.lower():
                # Extract the tag
                suffix_parts.append(lang.strip("."))
        
        if suffix_parts:
            filename = f"{title} ({year}).{'.'.join(suffix_parts)}{ext}"
        else:
            filename = f"{title} ({year}){ext}"
        
        return root / folder_name / filename

    # ------------------- Folder Name Rules -------------------
    @staticmethod
    def _is_clean_folder_name(folder_name: str) -> bool:
        """Check if folder follows clean 'Movie Title (Year)' format."""
        return bool(re.match(r"^.+\s+\(\d{4}\)$", folder_name))

    @staticmethod
    def _is_release_folder_name(folder_name: str) -> bool:
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

    # ------------------- Track folders without media -------------------
    def _track_folders_without_media(self, root: Path) -> None:
        """Track movie folders that have nested structure but no media files."""
        for entry in root.iterdir():
            if not entry.is_dir():
                continue

            movie_dir = entry
            has_nested = False
            has_media = False

            for dirpath, dirnames, filenames in os.walk(movie_dir):
                if dirnames:
                    has_nested = True
                for fn in filenames:
                    if Path(fn).suffix.lower() in VIDEO_EXT:
                        has_media = True
                        break
                if has_media:
                    break

            if movie_dir.exists() and has_nested and not has_media:
                self._source_folders.add(movie_dir)

    # ------------------- Cleanup -------------------
    def cleanup_empty_dirs(self, root: Path, commit: bool) -> None:
        """Remove empty directories and 'screens' folders."""
        for dirpath, _, _ in os.walk(root, topdown=False):
            p = Path(dirpath)

            # Delete screens directories
            if "screens" in p.name.lower():
                self._logger.info("DELETE SCREENS DIR: %s", p)
                if commit:
                    shutil.rmtree(p, ignore_errors=True)
                continue

            # Delete empty directories
            try:
                visible = [f for f in p.iterdir() if not f.name.startswith(".")]
            except FileNotFoundError:
                continue

            if not visible:
                self._logger.info("DELETE EMPTY DIR: %s", p)
                if commit:
                    shutil.rmtree(p, ignore_errors=True)

    # ------------------- Main -------------------
    def run(
        self,
        root: Path,
        commit: bool = False,
        plan: bool = False,
        quarantine: Optional[Path] = None,
        lookup: bool = False,
    ) -> None:
        """Run the movie cleaning process.
        
        Args:
            root: Root directory to process.
            commit: If True, actually perform operations. If False, dry-run.
            plan: If True, write journal even in dry-run mode.
            quarantine: Optional path to move samples/trailers instead of deleting.
            lookup: If True, use TMDB API to look up missing years.
        """
        journal_path = root / f".clean-movie-journal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        journal: List[dict] = []
        unexpected: List[str] = []

        self._logger.info(
            "START: %s (commit=%s, plan=%s, quarantine=%s)",
            root,
            commit,
            plan,
            quarantine,
        )

        # Collect all files
        files: List[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                files.append(Path(dirpath) / fn)

        for path in files:
            if not path.is_file():
                continue

            name = path.name
            ext = path.suffix.lower()

            # Skip journal files
            if name.startswith(".clean-movie-journal"):
                continue

            # Track non-clean folders
            try:
                rel_parts = path.parent.relative_to(root).parts if path.parent != root else ()
            except ValueError:
                rel_parts = ()
            
            if rel_parts:
                top_level = root / rel_parts[0]
                if self._is_release_folder_name(top_level.name):
                    self._source_folders.add(top_level)

            # Screens directory content
            if "screens" in str(path.parent).lower():
                self._logger.info("DELETE SCREENS FILE: %s", path)
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (screens-folder content)")
                continue

            # Samples, proofs, trailers - check if pattern appears anywhere in filename
            lowered = name.lower()
            is_sample = any(pattern in lowered for pattern in SAMPLE_PATTERNS)
            # Also check if file is in a Sample/ folder
            if path.parent.name.lower() in ("sample", "samples"):
                is_sample = True
            
            if is_sample:
                if quarantine is not None:
                    quarantine.mkdir(parents=True, exist_ok=True)
                    dst = quarantine / name
                    self._logger.info("QUARANTINE SAMPLE: %s -> %s", path, dst)
                    try:
                        self.safe_move(path, dst, commit, journal)
                    except FileExistsError:
                        self._logger.warning("SAMPLE DEST EXISTS, DELETING SOURCE: %s", path)
                        self.safe_delete(path, commit, journal)
                else:
                    self._logger.info("DELETE SAMPLE: %s", path)
                    self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (sample)")
                continue

            # Auxiliary files to delete
            if ext in AUX_DELETE:
                self._logger.info("DELETE AUX: %s", path)
                self.safe_delete(path, commit, journal)
                continue

            # Image files
            if ext in IMAGE_EXT:
                self._logger.info("DELETE IMAGE FILE: %s", path)
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (image)")
                continue

            # Check if file is in a Subs/ subfolder
            in_subs_folder = path.parent.name.lower() in SUBS_FOLDER_NAMES
            
            # Try to parse movie info from filename, parent folder, or grandparent (for Subs/)
            parsed_file = parse_movie_from_string(name)
            parsed_parent = parse_movie_from_string(path.parent.name)
            parsed_grandparent = None
            if in_subs_folder and len(path.parents) >= 2:
                parsed_grandparent = parse_movie_from_string(path.parents[1].name)
            
            parsed = parsed_file or parsed_parent or parsed_grandparent
            
            # If parsing failed and lookup is enabled, try TMDB
            if not parsed and lookup and ext in VIDEO_EXT:
                # Extract a clean title for lookup
                raw_name = Path(name).stem
                clean_name = clean_movie_title(raw_name)
                parsed = lookup_movie_year(clean_name)

            # Media and subtitles
            if ext in VIDEO_EXT or ext in SUBTITLE_EXT:
                # Filter non-English subtitles in release folders or Subs/ folders
                is_in_release_context = (
                    self._is_release_folder_name(path.parent.name) or
                    (in_subs_folder and len(path.parents) >= 2 and 
                     self._is_release_folder_name(path.parents[1].name))
                )
                
                if ext in SUBTITLE_EXT and is_in_release_context:
                    if not is_english_subtitle(name):
                        self._logger.info(
                            "DELETE NON-ENGLISH SUBTITLE: %s",
                            path,
                        )
                        self.safe_delete(path, commit, journal)
                        unexpected.append(f"{path} (non-English subtitle)")
                        continue

                if not parsed:
                    self._logger.warning("SKIP (unparsed media): %s", path)
                    unexpected.append(f"{path} (unparsed media)")
                    continue

                title, year = parsed

                if ext in VIDEO_EXT:
                    dest = self.build_dest(root, title, year, ext)
                else:
                    dest = self.build_sidecar_dest(root, title, year, name)

                dest.parent.mkdir(parents=True, exist_ok=True)

                if self.same_path(path, dest):
                    self._logger.info("OK (already placed): %s", path)
                    continue

                if dest.exists() and self.same_content(path, dest):
                    self._logger.info(
                        "DUPLICATE: %s matches %s — deleting source",
                        path,
                        dest,
                    )
                    self.safe_delete(path, commit, journal)
                    continue

                if dest.exists():
                    alt = self.unique_path(dest)
                    self._logger.warning("DEST EXISTS, USING ALT: %s", alt)
                    dest = alt

                self._logger.info("MOVE: %s -> %s", path, dest)
                if not self._is_clean_folder_name(path.parent.name):
                    self._source_folders.add(path.parent)
                self.safe_move(path, dest, commit, journal)
                continue

            # Unknown file in a release folder - delete it
            if parsed_parent is not None:
                self._logger.info(
                    "DELETE RELEASE FOLDER JUNK: %s (parent: %s)",
                    path,
                    path.parent.name,
                )
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (release folder junk)")
                continue

            self._logger.info("SKIP (unknown ext, not in release folder): %s", path)
            unexpected.append(f"{path} (unknown)")

        # Cleanup
        self.cleanup_empty_dirs(root, commit)
        self._track_folders_without_media(root)
        self._report_remaining_folders(root)

        # Write journal
        if plan or commit:
            with journal_path.open("w", encoding="utf-8") as f:
                for entry in journal:
                    f.write(json.dumps(entry) + "\n")
            self._logger.info("JOURNAL: %s", journal_path.resolve())

        if unexpected:
            self._logger.warning("UNEXPECTED FILES ENCOUNTERED (%d):", len(unexpected))
            for item in unexpected:
                self._logger.warning("UNEXPECTED: %s", item)

        self._logger.info("END")

    def _report_remaining_folders(self, root: Path) -> None:
        """Report which non-clean folders still exist after cleanup."""
        if not self._source_folders:
            self._logger.info("No non-clean folders were tracked.")
            return

        # Exclude the root folder itself from the report
        still_exist = [
            folder for folder in self._source_folders 
            if folder.exists() and folder != root
        ]

        if still_exist:
            self._logger.warning("\n=== NON-CLEAN FOLDERS STILL EXIST ===")
            self._logger.warning("The following %d folder(s) still exist:", len(still_exist))
            for folder in sorted(still_exist):
                self._logger.warning("  - %s", folder)
            self._logger.warning("====================================\n")
        else:
            self._logger.info("All non-clean folders were successfully deleted.")
