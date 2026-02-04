#!/usr/bin/env python3
"""Audio track utilities - Set default audio/subtitle tracks using mkvpropedit.

Sets English audio as default and disables subtitles unless marked as "forced"
(for foreign dialogue in English audio tracks).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from logging import Logger
from pathlib import Path


def check_mkvtoolnix_installed() -> bool:
    """Check if mkvtoolnix (mkvmerge, mkvpropedit) is installed.
    
    Returns:
        True if installed, False otherwise.
    """
    return shutil.which("mkvmerge") is not None and shutil.which("mkvpropedit") is not None


def get_track_info(path: Path, logger: Logger) -> dict | None:
    """Get track information from a video file using mkvmerge.
    
    Args:
        path: Path to video file.
        logger: Logger instance.
        
    Returns:
        JSON dict with track info, or None on error.
    """
    if path.suffix.lower() != ".mkv":
        return None
    
    try:
        result = subprocess.run(
            ["mkvmerge", "-J", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("mkvmerge failed for %s: %s", path, result.stderr)
            return None
        
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("mkvmerge timeout for %s", path)
        return None
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse mkvmerge output for %s: %s", path, e)
        return None
    except Exception as e:
        logger.warning("Error getting track info for %s: %s", path, e)
        return None


def is_english_track(track: dict) -> bool:
    """Check if a track is English.
    
    Args:
        track: Track info dict from mkvmerge.
        
    Returns:
        True if track language is English or undefined.
    """
    props = track.get("properties", {})
    lang = props.get("language", "").lower()
    lang_ietf = props.get("language_ietf", "").lower()
    
    # Consider undefined as potentially English (common in single-audio files)
    english_codes = {"eng", "en", "english", "und", ""}
    
    return lang in english_codes or lang_ietf.startswith("en")


def is_forced_subtitle(track: dict) -> bool:
    """Check if a subtitle track is marked as forced.
    
    Forced subtitles are for foreign dialogue in otherwise English audio.
    
    Args:
        track: Track info dict from mkvmerge.
        
    Returns:
        True if track is forced.
    """
    props = track.get("properties", {})
    
    # Check forced flag
    if props.get("forced_track", False):
        return True
    
    # Check track name for "forced" indicator
    track_name = props.get("track_name", "").lower()
    if "forced" in track_name:
        return True
    
    return False


def set_track_defaults(
    path: Path,
    logger: Logger,
    commit: bool = False,
) -> bool:
    """Set English audio as default and disable non-forced subtitles.
    
    Args:
        path: Path to MKV file.
        logger: Logger instance.
        commit: If True, apply changes. If False, dry-run.
        
    Returns:
        True if changes were made (or would be made), False otherwise.
    """
    if path.suffix.lower() != ".mkv":
        return False
    
    info = get_track_info(path, logger)
    if not info:
        return False
    
    tracks = info.get("tracks", [])
    if not tracks:
        return False
    
    # Categorize tracks
    audio_tracks = [t for t in tracks if t.get("type") == "audio"]
    subtitle_tracks = [t for t in tracks if t.get("type") == "subtitles"]
    
    # Skip if no audio tracks
    if not audio_tracks:
        return False
    
    # Find English audio tracks
    english_audio = [t for t in audio_tracks if is_english_track(t)]
    
    # Build mkvpropedit commands
    commands: list[str] = []
    changes_needed = False
    
    # Handle audio tracks
    if not english_audio:
        logger.warning("NO ENGLISH AUDIO: %s", path.name)
        # Still process subtitles even if no English audio
    else:
        # Find which English track should be default (prefer first one)
        target_audio = english_audio[0]
        target_audio_id = target_audio["id"]
        
        for track in audio_tracks:
            track_id = track["id"]
            props = track.get("properties", {})
            is_default = props.get("default_track", False)
            
            if track_id == target_audio_id:
                # This should be default
                if not is_default:
                    commands.extend(["--edit", f"track:@{track_id}", "--set", "flag-default=1"])
                    changes_needed = True
                    logger.info("SET DEFAULT AUDIO: track %d (%s)", track_id, props.get("language", "und"))
            else:
                # This should not be default
                if is_default:
                    commands.extend(["--edit", f"track:@{track_id}", "--set", "flag-default=0"])
                    changes_needed = True
                    logger.info("UNSET DEFAULT AUDIO: track %d (%s)", track_id, props.get("language", "?"))
    
    # Handle subtitle tracks
    for track in subtitle_tracks:
        track_id = track["id"]
        props = track.get("properties", {})
        is_default = props.get("default_track", False)
        is_forced = is_forced_subtitle(track)
        track_name = props.get("track_name", "")
        lang = props.get("language", "und")
        
        if is_forced and is_english_track(track):
            # Forced English subtitles should be enabled (but not default)
            if is_default:
                # Keep enabled but not default - actually forced should stay default
                # Per user request: forced subs for foreign dialogue should be on
                logger.info("KEEP FORCED SUBTITLE: track %d (%s) %s", track_id, lang, track_name)
        else:
            # Non-forced subtitles should be disabled
            if is_default:
                commands.extend(["--edit", f"track:@{track_id}", "--set", "flag-default=0"])
                changes_needed = True
                logger.info("DISABLE SUBTITLE: track %d (%s) %s", track_id, lang, track_name)
    
    if not changes_needed:
        logger.debug("TRACKS OK: %s", path.name)
        return False
    
    if not commit:
        logger.info("WOULD UPDATE TRACKS: %s", path.name)
        return True
    
    # Apply changes
    try:
        cmd = ["mkvpropedit", str(path)] + commands
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("mkvpropedit failed for %s: %s", path, result.stderr)
            return False
        
        logger.info("UPDATED TRACKS: %s", path.name)
        return True
    except subprocess.TimeoutExpired:
        logger.error("mkvpropedit timeout for %s", path)
        return False
    except Exception as e:
        logger.error("Error updating tracks for %s: %s", path, e)
        return False


def process_directory(
    root: Path,
    logger: Logger,
    commit: bool = False,
) -> tuple[int, int, int]:
    """Process all MKV files in a directory tree.
    
    Args:
        root: Root directory to process.
        logger: Logger instance.
        commit: If True, apply changes.
        
    Returns:
        Tuple of (processed, updated, warnings) counts.
    """
    if not check_mkvtoolnix_installed():
        logger.error("mkvtoolnix not installed. Install with: brew install mkvtoolnix")
        return 0, 0, 0
    
    processed = 0
    updated = 0
    warnings = 0
    
    for path in root.rglob("*.mkv"):
        if not path.is_file():
            continue
        
        processed += 1
        
        # Check for English audio before processing
        info = get_track_info(path, logger)
        if info:
            audio_tracks = [t for t in info.get("tracks", []) if t.get("type") == "audio"]
            english_audio = [t for t in audio_tracks if is_english_track(t)]
            if audio_tracks and not english_audio:
                warnings += 1
        
        if set_track_defaults(path, logger, commit):
            updated += 1
    
    return processed, updated, warnings
