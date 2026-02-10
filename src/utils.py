#!/usr/bin/env python3
"""Shared utilities for Clean Media services."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from .config import NOISE_PREFIX_PATTERNS, SUBTITLE_EXT


def normalize_unicode_separators(s: str) -> str:
    """Normalize unicode dashes and whitespace.
    
    Args:
        s: Input string.
        
    Returns:
        Normalized string with standard dashes and single spaces.
    """
    s = s.replace("\u2013", "-").replace("\u2014", "-")  # En-dash, em-dash
    s = s.replace("\u00A0", " ")  # Non-breaking space
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_noise_prefix(name: str) -> str:
    """Remove common torrent site prefixes from a filename.
    
    Args:
        name: Filename or folder name.
        
    Returns:
        Name with prefixes like [rartv], www.site.org, etc. removed.
    """
    s = normalize_unicode_separators(name)
    for pat in NOISE_PREFIX_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return s.lstrip()


def is_english_subtitle(name: str) -> bool:
    """Check if a subtitle filename indicates English language.
    
    Uses filename heuristics only, not content inspection.
    
    Args:
        name: Filename to check.
        
    Returns:
        True if the file appears to be an English subtitle.
        
    Examples:
        >>> is_english_subtitle("movie.eng.srt")
        True
        >>> is_english_subtitle("movie.spa.srt")
        False
        >>> is_english_subtitle("English.srt")
        True
    """
    lower = name.lower()
    
    # Must be a subtitle file
    if not any(lower.endswith(ext) for ext in SUBTITLE_EXT):
        return False
    
    stem = Path(name).stem.lower()
    
    # Filenames that are just "English.srt" or start with "English"
    if stem in ("english", "eng", "en"):
        return True
    if stem.startswith(("english", "eng.", "en.")):
        return True
    
    # SDH/HI English subtitles like "SDH.eng.HI.srt"
    if "eng" in stem or "english" in stem:
        return True
    
    # Language markers in filename
    markers = [
        ".en.", ".eng.", ".english.",
        "_en.", "_eng.", "-en.", "-eng.",
        "(en)", "[en]", "(eng)", "[eng]",
        " english",
    ]
    
    for m in markers:
        if m in lower:
            return True
    
    # Suffix patterns
    if lower.endswith((".en.srt", ".eng.srt", ".english.srt")):
        return True
    
    return False


def sha1sum(path: Path, limit_bytes: int = 1024 * 1024) -> str:
    """Compute SHA1 hash of the first N bytes of a file.
    
    Args:
        path: Path to file.
        limit_bytes: Maximum bytes to read (default 1MB).
        
    Returns:
        Hex-encoded SHA1 hash.
    """
    h = hashlib.sha1()
    with path.open("rb") as f:
        h.update(f.read(limit_bytes))
    return h.hexdigest()


def same_content(a: Path, b: Path, logger=None) -> bool:
    """Check if two files have identical content (size + partial hash).
    
    Args:
        a: First file path.
        b: Second file path.
        logger: Optional logger for error reporting.
        
    Returns:
        True if files appear to have the same content.
    """
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return sha1sum(a) == sha1sum(b)
    except OSError as e:
        if logger:
            logger.debug("Error comparing %s and %s: %s", a, b, e)
        return False


def same_path(a: Path, b: Path) -> bool:
    """Check if two paths resolve to the same filesystem location.
    
    Args:
        a: First path.
        b: Second path.
        
    Returns:
        True if paths point to the same location.
    """
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a.absolute()) == str(b.absolute())


def unique_path(p: Path) -> Path:
    """Generate a unique path by appending (alt N) suffix if needed.
    
    Args:
        p: Desired path.
        
    Returns:
        Original path if available, otherwise path with (alt), (alt 2), etc.
    """
    if not p.exists():
        return p
    
    base = p.stem
    ext = p.suffix
    i = 1
    
    while True:
        suffix = "alt" if i == 1 else f"alt {i}"
        alt = p.with_name(f"{base} ({suffix}){ext}")
        if not alt.exists():
            return alt
        i += 1


def safe_move(
    src: Path,
    dst: Path,
    commit: bool,
    journal: list[dict],
    logger=None,
    touch_parent_depth: int = 2,
) -> None:
    """Safely move a file, using copy+delete if rename fails.

    Args:
        src: Source file path.
        dst: Destination file path.
        commit: If False, only log the operation without executing.
        journal: List to append operation record to.
        logger: Optional logger for status messages.
        touch_parent_depth: How many levels up from the destination file to
            touch the folder timestamp. Default is 2, which for TV shows
            touches the show folder (root/ShowName/Season XX/file.mkv -> ShowName).
            Set to 0 to disable.

    Raises:
        FileExistsError: If destination already exists.
    """
    if dst.exists():
        raise FileExistsError(f"Destination exists: {dst}")

    if not commit:
        return

    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.rename(src, dst)
    except OSError:
        # Cross-device move: copy then delete
        with src.open("rb") as rf, dst.open("wb") as wf:
            shutil.copyfileobj(rf, wf)
        src.unlink(missing_ok=True)

    journal.append({"op": "move", "src": str(src), "dst": str(dst)})

    # Update the containing folder's timestamp
    if touch_parent_depth > 0:
        folder_to_touch = dst.parent
        for _ in range(touch_parent_depth - 1):
            if folder_to_touch.parent.exists():
                folder_to_touch = folder_to_touch.parent
            else:
                break
        touch_folder(folder_to_touch)


def safe_delete(
    path: Path,
    commit: bool,
    journal: list[dict],
    logger=None,
) -> None:
    """Safely delete a file or directory.
    
    Args:
        path: Path to delete.
        commit: If False, only log the operation without executing.
        journal: List to append operation record to.
        logger: Optional logger for status messages.
    """
    if not commit:
        return
    
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    
    journal.append({"op": "delete", "path": str(path)})


def undo_from_journal(journal_path: Path, logger=None) -> None:
    """Undo operations from a journal file.
    
    Processes the journal in reverse order, undoing moves and
    logging deleted files (which cannot be recovered).
    
    Args:
        journal_path: Path to the .jsonl journal file.
        logger: Optional logger for status messages.
    """
    if not journal_path.exists():
        if logger:
            logger.error("Journal file not found: %s", journal_path)
        return
    
    entries = []
    with journal_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    
    # Reverse order for undo
    for entry in reversed(entries):
        op = entry.get("op")
        
        if op == "move":
            src = Path(entry["src"])
            dst = Path(entry["dst"])
            
            if dst.exists():
                if logger:
                    logger.info("UNDO MOVE: %s -> %s", dst, src)
                src.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.rename(dst, src)
                except OSError:
                    with dst.open("rb") as rf, src.open("wb") as wf:
                        shutil.copyfileobj(rf, wf)
                    dst.unlink(missing_ok=True)
            else:
                if logger:
                    logger.warning("UNDO SKIP (dst missing): %s", dst)
        
        elif op == "delete":
            path = entry.get("path")
            if logger:
                logger.warning("CANNOT UNDO DELETE: %s", path)
    
    if logger:
        logger.info("Undo complete from: %s", journal_path)


def touch_folder(folder: Path) -> None:
    """Update a folder's modification timestamp to current time.

    This is useful for signaling to media servers (like Plex) that
    content in this folder has changed.

    Args:
        folder: Path to the folder to touch.
    """
    if folder.exists() and folder.is_dir():
        import time
        current_time = time.time()
        os.utime(folder, (current_time, current_time))


def cleanup_empty_dirs(root: Path, commit: bool, logger=None) -> None:
    """Remove empty directories and 'screens' folders.
    
    Args:
        root: Root directory to clean.
        commit: If False, only log without deleting.
        logger: Optional logger for status messages.
    """
    for dirpath, _, _ in os.walk(root, topdown=False):
        p = Path(dirpath)
        
        # Delete screens directories
        if "screens" in p.name.lower():
            if logger:
                logger.info("DELETE SCREENS DIR: %s", p)
            if commit:
                shutil.rmtree(p, ignore_errors=True)
            continue
        
        # Delete empty directories
        try:
            visible = [f for f in p.iterdir() if not f.name.startswith(".")]
        except FileNotFoundError:
            continue
        
        if not visible:
            if logger:
                logger.info("DELETE EMPTY DIR: %s", p)
            if commit:
                shutil.rmtree(p, ignore_errors=True)
