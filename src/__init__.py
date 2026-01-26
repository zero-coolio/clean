"""Clean Media Organizer - TV and Movie file organization services."""
from .config import get_logger
from .utils import (
    normalize_unicode_separators,
    strip_noise_prefix,
    is_english_subtitle,
    sha1sum,
    same_content,
    same_path,
    unique_path,
    safe_move,
    safe_delete,
    undo_from_journal,
    cleanup_empty_dirs,
)

__all__ = [
    "get_logger",
    "normalize_unicode_separators",
    "strip_noise_prefix",
    "is_english_subtitle",
    "sha1sum",
    "same_content",
    "same_path",
    "unique_path",
    "safe_move",
    "safe_delete",
    "undo_from_journal",
    "cleanup_empty_dirs",
]
