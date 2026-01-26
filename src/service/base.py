#!/usr/bin/env python3
"""Base service class for Clean Media services."""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime
from logging import Logger
from pathlib import Path

from ..config import VIDEO_EXT, SAMPLE_PATTERNS
from ..utils import (
    cleanup_empty_dirs,
    is_english_subtitle,
    same_content,
    same_path,
    safe_delete,
    safe_move,
    undo_from_journal,
    unique_path,
)


class BaseCleanService(ABC):
    """Abstract base class for media cleaning services.
    
    Provides common functionality for file operations, duplicate handling,
    folder tracking, and journal management. Subclasses implement media-specific
    parsing and path building.
    """
    
    # Subclasses should set this
    SERVICE_NAME = "clean"
    
    def __init__(self, logger: Logger) -> None:
        """Initialize the service.
        
        Args:
            logger: Logger instance for this service.
        """
        self._logger = logger
        self._source_folders: set[Path] = set()
    
    # =========================================================================
    # Abstract methods - subclasses must implement
    # =========================================================================
    
    @abstractmethod
    def parse_media_info(self, name: str) -> tuple | None:
        """Parse media information from a filename or folder name.
        
        Args:
            name: Filename or folder name to parse.
            
        Returns:
            Tuple of parsed info (structure depends on subclass) or None.
        """
        pass
    
    @abstractmethod
    def build_video_dest(self, root: Path, parsed: tuple, ext: str) -> Path:
        """Build the canonical destination path for a video file.
        
        Args:
            root: Root media directory.
            parsed: Parsed media info from parse_media_info().
            ext: File extension.
            
        Returns:
            Destination path.
        """
        pass
    
    @abstractmethod
    def build_sidecar_dest(self, root: Path, parsed: tuple, original_name: str) -> Path:
        """Build the destination path for a sidecar file.
        
        Args:
            root: Root media directory.
            parsed: Parsed media info from parse_media_info().
            original_name: Original sidecar filename.
            
        Returns:
            Destination path.
        """
        pass
    
    @abstractmethod
    def is_clean_folder_name(self, folder_name: str) -> bool:
        """Check if a folder follows the clean naming convention.
        
        Args:
            folder_name: Folder name to check.
            
        Returns:
            True if the folder name is clean/organized.
        """
        pass
    
    @abstractmethod
    def is_release_folder_name(self, folder_name: str) -> bool:
        """Check if a folder looks like a release/wrapper folder.
        
        Args:
            folder_name: Folder name to check.
            
        Returns:
            True if the folder appears to be a release folder.
        """
        pass
    
    @abstractmethod
    def get_video_extensions(self) -> frozenset[str]:
        """Get the set of video file extensions to process."""
        pass
    
    @abstractmethod
    def get_sidecar_extensions(self) -> frozenset[str]:
        """Get the set of sidecar file extensions to process."""
        pass
    
    @abstractmethod
    def get_delete_extensions(self) -> frozenset[str]:
        """Get the set of file extensions to always delete."""
        pass
    
    # =========================================================================
    # Common functionality
    # =========================================================================
    
    def is_sample_file(self, path: Path) -> bool:
        """Check if a file is a sample, proof, or trailer.
        
        Args:
            path: File path to check.
            
        Returns:
            True if the file appears to be a sample.
        """
        lowered = path.name.lower()
        
        # Check filename
        if any(pattern in lowered for pattern in SAMPLE_PATTERNS):
            return True
        
        # Check if in a Sample/ folder
        if path.parent.name.lower() in ("sample", "samples"):
            return True
        
        return False
    
    def track_folder(self, folder: Path) -> None:
        """Track a folder as potentially needing cleanup.
        
        Args:
            folder: Folder to track.
        """
        self._source_folders.add(folder)
    
    def track_folders_without_media(self, root: Path) -> None:
        """Track folders that have structure but no media files.
        
        Args:
            root: Root directory to scan.
        """
        if not root.exists():
            return
        
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            
            has_nested = False
            has_media = False
            
            for dirpath, dirnames, filenames in os.walk(entry):
                if dirnames:
                    has_nested = True
                for fn in filenames:
                    if Path(fn).suffix.lower() in VIDEO_EXT:
                        has_media = True
                        break
                if has_media:
                    break
            
            if entry.exists() and has_nested and not has_media:
                self._source_folders.add(entry)
    
    def report_remaining_folders(self, root: Path) -> None:
        """Report non-clean folders that still exist after processing.
        
        Args:
            root: Root directory (excluded from report).
        """
        if not self._source_folders:
            self._logger.info("No non-clean folders were tracked.")
            return
        
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
    
    def undo(self, journal_path: Path) -> None:
        """Undo operations from a journal file.
        
        Args:
            journal_path: Path to journal file.
        """
        undo_from_journal(journal_path, logger=self._logger)
    
    def process_file(
        self,
        path: Path,
        root: Path,
        commit: bool,
        journal: list[dict],
        quarantine: Path | None,
        unexpected: list[str],
    ) -> None:
        """Process a single file.
        
        Args:
            path: File to process.
            root: Root media directory.
            commit: If True, apply changes.
            journal: Operation journal.
            quarantine: Optional quarantine directory.
            unexpected: List to append unexpected file reports to.
        """
        name = path.name
        ext = path.suffix.lower()
        
        # Skip journal files
        if name.startswith(f".{self.SERVICE_NAME}-journal"):
            return
        
        # Track non-clean folders
        try:
            rel_parts = path.parent.relative_to(root).parts if path.parent != root else ()
        except ValueError:
            rel_parts = ()
        
        if rel_parts:
            top_level = root / rel_parts[0]
            if self.is_release_folder_name(top_level.name):
                self.track_folder(top_level)
        
        if len(rel_parts) >= 2:
            if not self.is_clean_folder_name(path.parent.name):
                self.track_folder(path.parent)
        
        # Screens directory content
        if "screens" in str(path.parent).lower():
            self._logger.info("DELETE SCREENS FILE: %s", path)
            safe_delete(path, commit, journal, self._logger)
            unexpected.append(f"{path} (screens-folder content)")
            return
        
        # Samples, proofs, trailers
        if self.is_sample_file(path):
            if quarantine is not None:
                quarantine.mkdir(parents=True, exist_ok=True)
                dst = quarantine / name
                self._logger.info("QUARANTINE SAMPLE: %s -> %s", path, dst)
                try:
                    safe_move(path, dst, commit, journal, self._logger)
                except FileExistsError:
                    self._logger.warning("SAMPLE DEST EXISTS, DELETING SOURCE: %s", path)
                    safe_delete(path, commit, journal, self._logger)
            else:
                self._logger.info("DELETE SAMPLE: %s", path)
                safe_delete(path, commit, journal, self._logger)
            unexpected.append(f"{path} (sample)")
            return
        
        # Files to always delete
        if ext in self.get_delete_extensions():
            self._logger.info("DELETE AUX: %s", path)
            safe_delete(path, commit, journal, self._logger)
            return
        
        # Image files
        from ..config import IMAGE_EXT
        if ext in IMAGE_EXT:
            self._logger.info("DELETE IMAGE FILE: %s", path)
            safe_delete(path, commit, journal, self._logger)
            unexpected.append(f"{path} (image)")
            return
        
        # Try to parse media info
        parsed = self._try_parse_media(path, root)
        
        # Handle video and sidecar files
        video_exts = self.get_video_extensions()
        sidecar_exts = self.get_sidecar_extensions()
        
        if ext in video_exts or ext in sidecar_exts:
            # Filter non-English subtitles in release folders
            if ext in sidecar_exts and self._is_in_release_context(path):
                if not is_english_subtitle(name):
                    self._logger.info("DELETE NON-ENGLISH SUBTITLE: %s", path)
                    safe_delete(path, commit, journal, self._logger)
                    unexpected.append(f"{path} (non-English subtitle)")
                    return
            
            if not parsed:
                self._logger.warning("SKIP (unparsed media): %s", path)
                unexpected.append(f"{path} (unparsed media)")
                return
            
            # Build destination
            if ext in video_exts:
                dest = self.build_video_dest(root, parsed, ext)
            else:
                dest = self.build_sidecar_dest(root, parsed, name)
            
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            # Already in correct location
            if same_path(path, dest):
                self._logger.info("OK (already placed): %s", path)
                return
            
            # Handle duplicates
            if dest.exists() and same_content(path, dest, self._logger):
                self._logger.info("DUPLICATE: %s matches %s — deleting source", path, dest)
                safe_delete(path, commit, journal, self._logger)
                return
            
            # Handle destination conflict
            if dest.exists():
                alt = unique_path(dest)
                self._logger.warning("DEST EXISTS, USING ALT: %s", alt)
                dest = alt
            
            # Move the file
            self._logger.info("MOVE: %s -> %s", path, dest)
            if not self.is_clean_folder_name(path.parent.name):
                self.track_folder(path.parent)
            safe_move(path, dest, commit, journal, self._logger)
            return
        
        # Unknown file in a release folder - delete it
        parsed_parent = self.parse_media_info(path.parent.name)
        if parsed_parent is not None:
            self._logger.info("DELETE RELEASE FOLDER JUNK: %s", path)
            safe_delete(path, commit, journal, self._logger)
            unexpected.append(f"{path} (release folder junk)")
            return
        
        self._logger.info("SKIP (unknown ext, not in release folder): %s", path)
        unexpected.append(f"{path} (unknown)")
    
    def _try_parse_media(self, path: Path, root: Path) -> tuple | None:
        """Try to parse media info from file, parent, and grandparent.
        
        Args:
            path: File path.
            root: Root directory.
            
        Returns:
            Parsed info or None.
        """
        from ..config import SUBS_FOLDER_NAMES
        
        # Try filename first
        parsed = self.parse_media_info(path.name)
        if parsed:
            return parsed
        
        # Try parent folder
        parsed = self.parse_media_info(path.parent.name)
        if parsed:
            return parsed
        
        # Try grandparent for Subs/ folders
        in_subs_folder = path.parent.name.lower() in SUBS_FOLDER_NAMES
        if in_subs_folder and len(path.parents) >= 2:
            parsed = self.parse_media_info(path.parents[1].name)
            if parsed:
                return parsed
        
        return None
    
    def _is_in_release_context(self, path: Path) -> bool:
        """Check if a file is in a release folder context.
        
        Args:
            path: File path.
            
        Returns:
            True if in a release folder or Subs subfolder of one.
        """
        from ..config import SUBS_FOLDER_NAMES
        
        if self.is_release_folder_name(path.parent.name):
            return True
        
        in_subs_folder = path.parent.name.lower() in SUBS_FOLDER_NAMES
        if in_subs_folder and len(path.parents) >= 2:
            if self.is_release_folder_name(path.parents[1].name):
                return True
        
        return False
    
    def run(
        self,
        root: Path,
        commit: bool = False,
        plan: bool = False,
        quarantine: Path | None = None,
    ) -> None:
        """Run the cleaning process.
        
        Args:
            root: Root directory to process.
            commit: If True, apply changes. If False, dry-run.
            plan: If True, write journal even in dry-run mode.
            quarantine: Optional path to move samples instead of deleting.
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        journal_path = root / f".{self.SERVICE_NAME}-journal-{timestamp}.jsonl"
        journal: list[dict] = []
        unexpected: list[str] = []
        
        self._logger.info(
            "START: %s (commit=%s, plan=%s, quarantine=%s)",
            root, commit, plan, quarantine,
        )
        
        # Collect all files
        files: list[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                files.append(Path(dirpath) / fn)
        
        # Process each file
        for path in files:
            if path.is_file():
                self.process_file(path, root, commit, journal, quarantine, unexpected)
        
        # Cleanup
        cleanup_empty_dirs(root, commit, self._logger)
        self.track_folders_without_media(root)
        self.report_remaining_folders(root)
        
        # Write journal
        if plan or commit:
            with journal_path.open("w", encoding="utf-8") as f:
                for entry in journal:
                    f.write(json.dumps(entry) + "\n")
            self._logger.info("JOURNAL: %s", journal_path.resolve())
        
        # Report unexpected files
        if unexpected:
            self._logger.warning("UNEXPECTED FILES ENCOUNTERED (%d):", len(unexpected))
            for item in unexpected:
                self._logger.warning("UNEXPECTED: %s", item)
        
        self._logger.info("END")
