"""Resolve and vet the library roots a clean run was handed.

One job: turn the `--directory` values a caller supplied into the list of roots
it is actually safe to groom, and say loudly why any were dropped.

Why this is not just `Path(x).resolve()` (CLEAN-18). clean-movie became
multi-root so /Volumes/Summer/movie-archive could be organized alongside
seagate-movie. Two roots on two removable volumes means a run can now start
while one of them is not there, and macOS makes that dangerous in a specific
way: /Volumes/<name> is an ordinary directory on the boot disk that the mounter
creates and removes. If a volume is absent but a stale directory of the same
name survives, a path under it exists, is writable, and is on the WRONG DISK.
A groomer pointed at one sees a library that has apparently lost every file,
and anything it writes fills the boot disk instead of the archive.

So a root under /Volumes must sit on something actually mounted. `os.path.ismount`
answers that directly and cheaply. A root that fails any check is skipped with a
warning and the run continues over the roots that passed, because one unplugged
drive must not stop the other library from being tidied.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# macOS mounts removable and secondary volumes here. A path under this prefix
# is only trustworthy when its volume root is a real mount point.
_MOUNT_PREFIX = Path("/Volumes")


def _volume_root(path: Path) -> Path | None:
    """The /Volumes/<name> component of `path`, or None if it is not under one."""
    try:
        rel = path.relative_to(_MOUNT_PREFIX)
    except ValueError:
        return None
    return _MOUNT_PREFIX / rel.parts[0] if rel.parts else None


def check_root(raw: str | Path, log=None) -> tuple[Path | None, str | None]:
    """Vet one root.

    Args:
        raw: The path as the caller gave it.
        log: Logger for the rejection reason.

    Returns:
        `(resolved_path, None)` when the root is safe to groom, or
        `(None, reason)` when it is not.
    """
    log = log or logger
    path = Path(raw).expanduser()

    vol = _volume_root(path)
    if vol is not None and not os.path.ismount(vol):
        return None, (
            f"{vol} is not a mounted volume. The path may be a leftover "
            f"directory on the boot disk, which would look like a library that "
            f"lost every file"
        )

    try:
        path = path.resolve(strict=True)
    except (OSError, FileNotFoundError):
        return None, "does not exist"

    if not path.is_dir():
        return None, "is not a directory"

    return path, None


def resolve_roots(raws, log=None) -> list[Path]:
    """Vet every root, warn about the ones dropped, return the usable ones.

    Deduplicates while preserving order, so the same library named twice (or
    once by symlink and once by real path) is groomed once. An empty result
    means every root was rejected and the caller must not proceed.
    """
    log = log or logger
    out: list[Path] = []
    seen: set[Path] = set()

    for raw in raws:
        path, reason = check_root(raw, log)
        if path is None:
            log.warning("SKIP ROOT: %s (%s)", raw, reason)
            continue
        if path in seen:
            log.info("SKIP ROOT: %s (already named by an earlier --directory)", raw)
            continue
        seen.add(path)
        out.append(path)

    return out
