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
