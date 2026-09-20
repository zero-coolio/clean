"""Ask ffprobe what a video file actually is.

Split out from the clean services because it is the one thing that can answer
questions about a file without trusting its name. Two questions live here:

* `video_height` answers "is this file actually better?" for conflict
  resolution. Filenames lose their quality tag the moment CleanMedia normalizes
  them (`Show.(Year).S01E02.mkv` keeps no `1080p`), so a conflict between an
  incumbent and a new arrival cannot be judged from names alone.
* `container_title` answers "what did this file call itself?" for identity.
  A rip carries the original release name in its container tags, and renaming
  the file never touches it. That tag survives every mistake CleanMedia has
  ever made to a filename, which makes it the most durable evidence on disk:

      TAG:title=Doctor.Who.Joy.to.the.World.2024.1080p.WEBRip.x264.Dual YG

  See name_evidence, which turns that into a parseable candidate. (CLEAN-13)

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

# (resolved path, size, mtime_ns) -> answer. Keyed on the file's identity
# rather than its name: a conflict run may probe a path, move another file onto
# it, and probe again. One cache per question.
_height_cache: dict[tuple[str, int, int], int | None] = {}
_title_cache: dict[tuple[str, int, int], str | None] = {}


def _cache_key(path: Path, log) -> tuple[str, int, int] | None:
    """Identity key for `path`, or None if it cannot be stat'd."""
    try:
        st = path.stat()
    except OSError as e:
        log.debug("probe: cannot stat %s: %s", path, e)
        return None
    return (str(path.resolve()), st.st_size, st.st_mtime_ns)


def _run_ffprobe(path: Path, entries: str, log, what: str) -> dict | None:
    """Run ffprobe once for `entries` and return the decoded JSON, or None.

    One subprocess wrapper for every question this module asks, so a timeout, a
    missing binary and a malformed file are handled identically no matter what
    is being probed.

    Args:
        path: File to probe.
        entries: An ffprobe `-show_entries` selector, e.g. "format_tags=title".
        log: Logger to report through.
        what: Caller name, for log lines.

    Returns:
        Parsed ffprobe JSON, or None when the answer is unknowable.
    """
    cmd = ["ffprobe", "-v", "error"]
    if entries.startswith("stream"):
        cmd += ["-select_streams", "v:0"]
    cmd += ["-show_entries", entries, "-of", "json", str(path)]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        log.warning("%s: ffprobe not installed, cannot read %s", what, path.name)
        return None
    except subprocess.TimeoutExpired:
        log.warning("%s: ffprobe timed out after %ds: %s",
                    what, PROBE_TIMEOUT_SECONDS, path)
        return None

    if result.returncode != 0:
        log.debug("%s: ffprobe failed (%d) for %s: %s",
                  what, result.returncode, path, result.stderr.strip()[:200])
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        log.debug("%s: unparseable ffprobe output for %s: %s", what, path, e)
        return None


def video_height(path: Path, logger_=None) -> int | None:
    """Pixel height of `path`'s first video stream, or None if unreadable.

    None means "do not know" and callers must treat it as such, never as
    "low quality". A broken file, a missing ffprobe, a timeout and an audio-only
    file all land here, and none of them justify deleting anything.
    """
    log = logger_ or logger
    key = _cache_key(path, log)
    if key is None:
        return None
    if key in _height_cache:
        return _height_cache[key]

    height = _probe_height(path, log)
    _height_cache[key] = height
    return height


def _probe_height(path: Path, log) -> int | None:
    """Pull the first video stream's height from ffprobe."""
    data = _run_ffprobe(path, "stream=width,height", log, "video_height")
    if data is None:
        return None

    streams = data.get("streams") or []
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


def container_title(path: Path, logger_=None) -> str | None:
    """The container's own title tag, or None when it carries none.

    This is what the file called itself when it was created, which is usually
    the original release name and is never rewritten when CleanMedia renames
    the file. None means the tag is absent or unreadable; it never means the
    file is unidentifiable, only that this particular rung of the ladder is
    empty. Callers must fall through rather than give up. (CLEAN-13)
    """
    log = logger_ or logger
    key = _cache_key(path, log)
    if key is None:
        return None
    if key in _title_cache:
        return _title_cache[key]

    title = _probe_title(path, log)
    _title_cache[key] = title
    return title


def _probe_title(path: Path, log) -> str | None:
    """Pull `format_tags.title` from ffprobe, normalized to a usable string."""
    data = _run_ffprobe(path, "format_tags=title", log, "container_title")
    if data is None:
        return None

    tags = (data.get("format") or {}).get("tags") or {}
    # Tag keys are case-preserving and vary by muxer: TITLE, title, Title.
    raw = next((v for k, v in tags.items() if k.lower() == "title"), None)
    if not isinstance(raw, str):
        return None

    title = raw.strip()
    if not title:
        return None

    log.debug("container_title: %s -> %r", path.name, title)
    return title


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
        print(f"{'tag':>8}  {container_title(p)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
