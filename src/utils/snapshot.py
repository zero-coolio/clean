#!/usr/bin/env python3
"""
HOW TO USE
-----------
# Pretty-print JSON to stdout
python -m utils.snapshot -d "/path/to/intake"

# Include hidden files and cap at 5000 files
python -m utils.snapshot -d "/path/to/intake" --include-hidden --limit 5000

# Save JSON to file for ChatGPT training/debugging
python -m utils.snapshot -d "/path/to/intake" -o snapshot.json

# Regular table-style printout
python -m utils.snapshot -d "/path/to/intake" --print

# Save table-style output to file
python -m utils.snapshot -d "/path/to/intake" --print -o snapshot.txt


WHAT THE JSON GIVES YOU
-----------------------
- A "summary" section containing:
    - total_files, parsed_ok, parsed_fail
    - generation timestamp
- A "files" list containing entries like:
    {
      "rel_path": "Show/Season 01/Episode.mkv",
      "name": "Show.S01E01.mkv",
      "ext": ".mkv",
      "size": 734003200,
      "mtime_iso": "2025-11-06T03:20:00",
      "is_video": true,
      "is_sidecar": false,
      "parsed": {"show": "Show", "season": "01", "episode": "01"},
      "parse_ok": true,
      "parse_hint": null
    }

This snapshot helps identify mishandled or missing filename patterns
when training ChatGPT or validating the Clean-TV parsing logic.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov"}
SIDECAR_EXT = {".srt", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png", ".txt"}

SHOW_SEASON_PATTERNS = [
    re.compile(r"^(?P<show>.*?)[\.\s\-_]*S(?P<season>\d{1,2})[\.\s\-_]*E(?P<episode>\d{1,2})", re.IGNORECASE),
    re.compile(r"^(?P<show>.*?)[\.\s\-_]*(?P<season>\d{1,2})[xX](?P<episode>\d{1,2})", re.IGNORECASE),
    re.compile(r"^(?P<show>.*?)[\.\s\-_]*(?P<seasode>\d{3,4})(?!\d)", re.IGNORECASE),
]

def parse_tv_filename(name: str) -> Optional[Tuple[str, str, str]]:
    stem = Path(name).stem
    for pat in SHOW_SEASON_PATTERNS:
        m = pat.search(stem)
        if not m:
            continue
        if "seasode" in m.groupdict():
            val = m.group("seasode")
            if len(val) == 3:
                season, episode = val[0], val[1:]
            elif len(val) == 4:
                season, episode = val[:2], val[2:]
            else:
                continue
            raw_show = stem[: m.start()].strip()
        else:
            raw_show = m.group("show")
            season, episode = m.group("season"), m.group("episode")

        show = re.sub(r"[\._\-]+", " ", raw_show, flags=re.UNICODE).strip()
        show = re.sub(r"\s+", " ", show)
        if not show:
            continue
        return show, season.zfill(2), episode.zfill(2)
    return None

@dataclass
class FileRecord:
    rel_path: str
    name: str
    ext: str
    size: int
    mtime_iso: str
    is_video: bool
    is_sidecar: bool
    parsed: Optional[dict]
    parse_ok: bool
    parse_hint: Optional[str]

def classify_file(path: Path) -> tuple[bool, bool]:
    ext = path.suffix.lower()
    return (ext in VIDEO_EXT, ext in SIDECAR_EXT)

def stat_safe(p: Path):
    try:
        st = p.stat()
        return st.st_size, datetime.fromtimestamp(st.st_mtime).isoformat()
    except Exception:
        return -1, ""

def make_record(root: Path, path: Path) -> FileRecord:
    rel = str(path.relative_to(root))
    size, mtime_iso = stat_safe(path)
    is_video, is_sidecar = classify_file(path)
    parsed_tuple = parse_tv_filename(path.name)
    if parsed_tuple:
        show, season, episode = parsed_tuple
        parsed = {"show": show, "season": season, "episode": episode}
        parse_ok, parse_hint = True, None
    else:
        parsed, parse_ok, parse_hint = None, False, "pattern_not_matched"

    return FileRecord(
        rel_path=rel,
        name=path.name,
        ext=path.suffix.lower(),
        size=size,
        mtime_iso=mtime_iso,
        is_video=is_video,
        is_sidecar=is_sidecar,
        parsed=parsed,
        parse_ok=parse_ok,
        parse_hint=parse_hint,
    )

def snapshot_directory(root_dir: str, include_hidden: bool = False, limit: Optional[int] = None) -> dict:
    root = Path(root_dir).expanduser().resolve()
    files: List[FileRecord] = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        if not include_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            filenames = [f for f in filenames if not f.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if not p.is_file():
                continue
            files.append(make_record(root, p))
            count += 1
            if limit and count >= limit:
                break
        if limit and count >= limit:
            break

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "root": str(root),
        "total_files": len(files),
        "parsed_ok": sum(1 for r in files if r.parse_ok),
        "parsed_fail": sum(1 for r in files if not r.parse_ok),
    }

    return {
        "summary": summary,
        "files": [asdict(r) for r in files],
    }

def build_table(data: dict) -> str:
    summary = data["summary"]
    files = data["files"]
    lines = []
    lines.append(f"\nSnapshot Summary ({summary['generated_at']})")
    lines.append("-" * 90)
    lines.append(f"Root: {summary['root']}")
    lines.append(f"Total Files: {summary['total_files']}")
    lines.append(f"Parsed OK:   {summary['parsed_ok']}")
    lines.append(f"Parsed Fail: {summary['parsed_fail']}")
    lines.append("-" * 90)
    lines.append(f"{'Rel Path':60} {'Size(MB)':>10} {'Parsed?':>8} {'Show/Season/Episode'}")
    lines.append("-" * 90)
    for f in files:
        parsed_str = f"{f['parsed']['show']} S{f['parsed']['season']}E{f['parsed']['episode']}" if f["parsed"] else "-"
        size_mb = f["size"] / (1024 * 1024)
        lines.append(f"{f['rel_path'][:60]:60} {size_mb:10.2f} {str(f['parse_ok']):>8} {parsed_str}")
    lines.append("-" * 90)
    return "\n".join(lines)

def safe_write_output(text: str, output_path: str):
    out_path = Path(output_path).expanduser().resolve()
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[✓] Output written to {out_path}")

def main():
    ap = argparse.ArgumentParser(description="Print recursive, pretty-printed JSON or table of files for pattern training")
    ap.add_argument("--directory", "-d", required=True, help="Root directory to scan")
    ap.add_argument("--include-hidden", action="store_true", help="Include dotfiles and dot-directories")
    ap.add_argument("--limit", type=int, help="Max files to include")
    ap.add_argument("--output", "-o", help="Write output to file (JSON or table depending on mode)")
    ap.add_argument("--print", action="store_true", help="Print a human-readable table instead of JSON")
    args = ap.parse_args()

    data = snapshot_directory(args.directory, include_hidden=args.include_hidden, limit=args.limit)

    if args.print:
        table_text = build_table(data)
        if args.output:
            safe_write_output(table_text, args.output)
        else:
            print(table_text)
        return

    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        safe_write_output(text, args.output)
    else:
        print(text)

if __name__ == "__main__":
    main()
