"""Read the pixel height of a video file's primary video stream.

Split out from the clean services because it is the one thing that can answer
"is this file actually better?" without trusting a release name. Filenames lose
their quality tag the moment CleanMedia normalizes them (`Show.(Year).S01E02.mkv`
keeps no `1080p`), so a conflict between an incumbent and a new arrival cannot be
judged from names alone — only from the media itself.

Uses ffprobe, which handles Matroska, MP4 and AVI alike. Results are memoized
per process and keyed on (path, size, mtime) so a file that changes underneath a
long run is re-probed rather than served a stale answer.

CLI, for checking a file by hand or from a test harness:

    python -m src.video_probe <file> [<file> ...]
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 30

# (resolved path, size, mtime_ns) -> height or None. Keyed on the file's
# identity rather than its name: a conflict run may probe a path, move another
# file onto it, and probe again.
_height_cache: dict[tuple[str, int, int], int | None] = {}


def video_height(path: Path, logger_=None) -> int | None:
    """Pixel height of `path`'s first video stream, or None if unreadable.

    None means "do not know" and callers must treat it as such — never as
    "low quality". A broken file, a missing ffprobe, a timeout and an audio-only
    file all land here, and none of them justify deleting anything.
    """
    log = logger_ or logger
    try:
        st = path.stat()
    except OSError as e:
        log.debug("video_height: cannot stat %s: %s", path, e)
        return None

    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    if key in _height_cache:
        return _height_cache[key]

    height = _probe_height(path, log)
    _height_cache[key] = height
    return height


def _probe_height(path: Path, log) -> int | None:
    """Run ffprobe once and pull the first video stream's height."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        log.warning("video_height: ffprobe not installed — cannot judge quality")
        return None
    except subprocess.TimeoutExpired:
        log.warning("video_height: ffprobe timed out after %ds: %s",
                    PROBE_TIMEOUT_SECONDS, path)
        return None

    if result.returncode != 0:
        log.debug("video_height: ffprobe failed (%d) for %s: %s",
                  result.returncode, path, result.stderr.strip()[:200])
        return None

    try:
        streams = json.loads(result.stdout).get("streams") or []
    except json.JSONDecodeError as e:
        log.debug("video_height: unparseable ffprobe output for %s: %s", path, e)
        return None

    if not streams:
        log.debug("video_height: no video stream in %s", path)
        return None

    height = streams[0].get("height")
    if not isinstance(height, int) or height <= 0:
        log.debug("video_height: no usable height in %s (%r)", path, height)
        return None

    log.debug("video_height: %s -> %dp (%sx%s)", path.name, height,
              streams[0].get("width"), height)
    return height


def describe_height(height: int | None) -> str:
    """Short human label for a probed height, for log lines."""
    return f"{height}p" if height else "unknown"


def main(argv: list[str] | None = None) -> int:
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    for name in args:
        p = Path(name)
        print(f"{describe_height(video_height(p)):>8}  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
