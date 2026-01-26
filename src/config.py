#!/usr/bin/env python3
"""Shared configuration and constants for Clean Media services."""
from __future__ import annotations

import logging
import sys

# ============================================================================
# File Extensions
# ============================================================================

VIDEO_EXT = frozenset({".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv"})
SUBTITLE_EXT = frozenset({".srt", ".sub", ".idx", ".vtt", ".ass", ".ssa"})
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp"})

# Files to always delete
JUNK_EXT = frozenset({".ds_store", ".rar", ".r00", ".r01", ".sfv", ".nzb", ".par2", ".srr"})

# TV-specific: keep these as sidecars
TV_SIDECAR_EXT = SUBTITLE_EXT | frozenset({".nfo", ".txt"})

# Movie-specific: delete these (they're usually release info)
MOVIE_DELETE_EXT = JUNK_EXT | frozenset({".nfo", ".txt"})

# Sample/junk filename patterns
SAMPLE_PATTERNS = ("sample", "proof", "trailer")

# Subdirectory names containing subtitles
SUBS_FOLDER_NAMES = frozenset({"subs", "subtitles", "sub"})

# ============================================================================
# Parsing Patterns
# ============================================================================

NOISE_PREFIX_PATTERNS = [
    r"^www\.UIndex\.org\s*-\s*",
    # Handle bracketed prefixes like [YTS], [rartv], etc.
    r"^\[(?:tgx|rartv|rarbg|eztv|yts|yify)\][\s._-]*",
    # Handle unbracketed prefixes like rarbg-, yts., etc.
    r"^(?:tgx|rartv|rarbg|eztv|yts|yify|eztv\.re)[\s._-]+",
    r"^www\.",
]

# Quality markers to strip from movie titles
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

# ============================================================================
# Logging Setup
# ============================================================================

_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
_configured_loggers: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with consistent configuration.
    
    Args:
        name: Logger name (e.g., "clean-tv", "clean-movie")
        
    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    
    # Only configure once per logger name
    if name not in _configured_loggers:
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        
        # Prevent propagation to root logger
        logger.propagate = False
        _configured_loggers.add(name)
    
    return logger
