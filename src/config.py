#!/usr/bin/env python3
"""Shared configuration and constants for Clean Media services."""
from __future__ import annotations

import logging
import os
import re
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

# A real episode is never this small; a genuine sample/trailer/proof clip is.
# Size is the DECISIVE guard for sample detection so a legitimate episode whose
# title merely contains "sample"/"proof"/"trailer" as a substring (e.g.
# "Bulletproof", "Proof of Concept", "Nacho Sampler") is never deleted.
SAMPLE_MAX_BYTES = 100 * 1024 * 1024  # 100 MB

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
# Incremental ("recent files only") mode
# ============================================================================

# Default time window for --recent: only files modified within the last hour
# are processed. Watcher-triggered runs use this so a single new download is
# organized in seconds instead of re-walking/re-checking the whole library.
DEFAULT_RECENT_WINDOW = "60m"

_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
}

_RE_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)


def parse_duration(text: str) -> float:
    """Parse a human duration like "1h", "30m", "90s", "2d" into seconds.

    A bare number with no unit is interpreted as seconds ("3600" == "1h").
    Accepts an optional decimal (e.g. "1.5h"). Raises ValueError on anything
    unparseable so a typo'd watcher flag fails loudly rather than silently
    disabling the time-window filter.

    Args:
        text: Duration string (e.g. "1h", "45m", "2d", "3600").

    Returns:
        The duration in seconds as a float.

    Raises:
        ValueError: If the string is not a recognized duration.
    """
    m = _RE_DURATION.match(text or "")
    if not m:
        raise ValueError(
            f"Invalid duration {text!r}; expected forms like '1h', '30m', '90s', '2d', or a bare number of seconds"
        )
    value = float(m.group(1))
    unit = m.group(2).lower() or "s"
    return value * _DURATION_UNITS[unit]


# ============================================================================
# qBittorrent integration
# ============================================================================
# Before renaming a downloaded file, CleanMedia asks qBittorrent who owns it:
#   * a COMPLETED torrent  -> remove it from the client (data kept) so the move
#     doesn't yank a seeded file out from under qBittorrent, then rename;
#   * an INCOMPLETE torrent -> flag the file as a "possible zombie", leave it;
#   * no torrent            -> rename as normal.
# See src/qbittorrent.py. All settings are env-overridable. Defaults assume the
# Web UI on localhost:8080 with "Bypass authentication for clients on localhost"
# enabled (no credentials needed).


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean-ish env var. Unset -> default; "0"/"false"/"no"/"off"/""
    -> False; anything else -> True."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


QBIT_ENABLED = _env_flag("QBIT_ENABLED", True)
QBIT_HOST = os.environ.get("QBIT_HOST", "localhost")
QBIT_PORT = int(os.environ.get("QBIT_PORT", "8080"))
QBIT_USER = os.environ.get("QBIT_USER") or None
QBIT_PASS = os.environ.get("QBIT_PASS") or None
QBIT_TIMEOUT = float(os.environ.get("QBIT_TIMEOUT", "5"))


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
