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

    # Remove trailing year in parentheses like "(2023)"
    show = re.sub(r"\s*\(\d{4}\)\s*$", "", show).strip()

    # Title case the show name
    show = show.title()
    
    return show, season.zfill(2), episode.zfill(2)


class CleanService(BaseCleanService):
    """Service to clean and organize TV show files."""
    
    SERVICE_NAME = "clean-tv"
    
    def __init__(self) -> None:
        super().__init__(get_logger("clean-tv"))
    
    # =========================================================================
    # Abstract method implementations
    # =========================================================================
    
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
