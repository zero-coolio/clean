#!/usr/bin/env python3
"""Clean TV Service - Organizes TV episodes into a clean directory structure.

Parses episode filenames to extract show name, season, and episode numbers,
then moves files to:
    <root>/<Show Name>/Season <SS>/<Show.Name.SxxExx.<ext>
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import VIDEO_EXT, JUNK_EXT, TV_SIDECAR_EXT, get_logger
from ..utils import normalize_unicode_separators, strip_noise_prefix
from .base import BaseCleanService

# Folder rename hint: "Old Show Name==New Show Name"
_RE_RENAME_HINT = re.compile(r"^(?P<from>.+?)\s*==\s*(?P<to>.+)$")


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


def parse_episode_from_string(s: str) -> tuple[str, str, str] | None:
    """Parse TV episode information from a string.

    Handles common patterns:
    - Show.Name.S01E02...
    - Show Name - 1x02 - Episode Title
    - Show Name Season 2 Episode 5

    Args:
        s: Filename or folder name to parse.

    Returns:
        Tuple of (show_name, season, episode) or None if unparseable.
        Season and episode are zero-padded to 2 digits.
    """
    name = normalize_unicode_separators(strip_noise_prefix(s))
    match = RE_SXXEYY.search(name) or RE_X.search(name) or RE_SEASON_EPISODE.search(name)
    
    if not match:
        return None
    
    raw_show = match.group("show")
    season = match.group("season")
    episode = match.group("episode")

    # Clean up show name
    show = re.sub(r"[._\-]+", " ", raw_show).strip()
    show = re.sub(r"\s+", " ", show)

    # Title case the show name
    show = show.title()

    # Normalize bare year to parenthesized form: "Show Name 2002" → "Show Name (2002)"
    show = re.sub(r"\s+((?:19|20)\d{2})$", r" (\1)", show)

    # If no year in show name, check remainder of filename (e.g. Show.S01E01(2002).mkv)
    if not re.search(r"(?:19|20)\d{2}", show):
        remainder = name[match.end():]
        year_match = re.search(r"[(\s._\-]((?:19|20)\d{2})[)\s._\-]", remainder)
        if year_match:
            show = f"{show} ({year_match.group(1)})"

    return show, season.zfill(2), episode.zfill(2)


class CleanService(BaseCleanService):
    """Service to clean and organize TV show files."""

    SERVICE_NAME = "clean-tv"

    def __init__(self) -> None:
        super().__init__(get_logger("clean-tv"))

    # =========================================================================
    # Folder rename hints  (FolderName==NewName)
    # =========================================================================

    def _before_run(self, root: Path, commit: bool, journal: list) -> None:
        """Rename files and folders marked with == rename hints before the main walk.

        A folder named "Unknown Show==Top Gear (2002)" causes every file inside
        whose name contains "Unknown.Show" (any separator) to be renamed to use
        "Top.Gear.(2002)", and the folder itself is renamed to "Top Gear (2002)".
        """
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            m = _RE_RENAME_HINT.match(entry.name)
            if not m:
                continue

            from_name = m.group("from").strip()
            to_name = m.group("to").strip()

            # Build a pattern that matches from_name with any word separator
            from_words = re.split(r"[\s._]+", from_name)
            from_re = re.compile(
                r"[\s._]*".join(re.escape(w) for w in from_words),
                re.IGNORECASE,
            )
            # Replacement uses dots between words (clean-tv filename style)
            to_dot = re.sub(r"\s+", ".", to_name)

            self._logger.info("RENAME HINT: '%s' -> '%s'", from_name, to_name)

            # Rename files inside the folder (walks Season subfolders too)
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

            # Rename the folder itself to to_name
            target = root / to_name
            if target.exists() and target != entry:
                # Target already exists — merge contents recursively
                self._logger.warning(
                    "RENAME HINT: target '%s' exists, merging contents", to_name
                )
                for child in sorted(entry.iterdir()):
                    dest_child = target / child.name
                    if not dest_child.exists():
                        self._logger.info("MERGE: %s -> %s", child, dest_child)
                        if commit:
                            child.rename(dest_child)
                        journal.append({"op": "move", "src": str(child), "dst": str(dest_child)})
                    elif child.is_dir():
                        # Season folder exists in both — merge files inside
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

    # =========================================================================
    # Abstract method implementations
    # =========================================================================

    def _try_parse_media(self, path: Path, root: Path) -> tuple | None:
        """Parse media info, then enrich show name with year from existing folder."""
        parsed = super()._try_parse_media(path, root)
        if parsed is None:
            return None
        show, season, episode = parsed
        if not re.search(r"(?:19|20)\d{2}", show):
            show = self._resolve_show_with_year(show, root)
        return show, season, episode

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
    
    def build_video_dest(self, root: Path, parsed: tuple[str, str, str], ext: str) -> Path:
        """Build destination path for a video file.
        
        Format: <root>/<Show Name>/Season <SS>/<Show.Name.SxxExx.<ext>
        """
        show, season, episode = parsed
        
        show_folder = show.strip() or "Unknown Show"
        season_folder = root / show_folder / f"Season {season}"
        
        base_show = re.sub(r"\s+", ".", show_folder)
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"
        
        return season_folder / filename
    
    def build_sidecar_dest(self, root: Path, parsed: tuple[str, str, str], original_name: str) -> Path:
        """Build destination path for a sidecar file.
        
        Sidecars use the same base name as the video file.
        """
        show, season, episode = parsed
        
        show_folder = show.strip() or "Unknown Show"
        season_folder = root / show_folder / f"Season {season}"
        
        base_show = re.sub(r"\s+", ".", show_folder)
        ext = Path(original_name).suffix
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"
        
        return season_folder / filename
    
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
    def build_dest(root: Path, show: str, season: str, episode: str, ext: str) -> Path:
        """Build destination path (static method for backwards compatibility)."""
        show_folder = show.strip() or "Unknown Show"
        season_folder = root / show_folder / f"Season {season}"
        base_show = re.sub(r"\s+", ".", show_folder)
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"
        return season_folder / filename
    
    @staticmethod
    def build_sidecar_target(root: Path, show: str, season: str, episode: str, name: str) -> Path:
        """Build sidecar path (static method for backwards compatibility)."""
        show_folder = show.strip() or "Unknown Show"
        season_folder = root / show_folder / f"Season {season}"
        base_show = re.sub(r"\s+", ".", show_folder)
        ext = Path(name).suffix
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"
        return season_folder / filename
    
    def undo_from_journal(self, journal_path: Path) -> None:
        """Undo operations from a journal file (legacy method name)."""
        self.undo(journal_path)
