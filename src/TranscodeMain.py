#!/usr/bin/env python3
"""CLI entrypoint for Transcode Service.

Usage:
    # Transcode specific files
    python -m src.TranscodeMain file1.mkv file2.mp4
    
    # Transcode files listed in a text file
    python -m src.TranscodeMain --input-file files.txt
    
    # Dry-run (show what would be done)
    python -m src.TranscodeMain --input-file files.txt
    
    # Actually perform transcodes
    python -m src.TranscodeMain --input-file files.txt --commit
    
    # Keep original files
    python -m src.TranscodeMain --input-file files.txt --commit --keep-original
    
    # Use a specific quality preset
    python -m src.TranscodeMain --preset compact file.mkv --commit

Presets:
    fast      - Fast encode, good quality, decent compression (crf=23)
    balanced  - Balance of speed and compression (crf=22, default)
    quality   - Better quality, slower, less compression (crf=20)
    compact   - Force 1080p max, good compression (crf=24)
    tiny      - Force 720p, maximum compression (crf=26)
"""
import argparse
import sys
from pathlib import Path

from .service.transcode_service import TranscodeService, check_ffmpeg, PRESETS


def parse_args():
    ap = argparse.ArgumentParser(
        description="Transcode video files to HEVC to reduce disk space",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Presets:
  fast      Fast encode, good quality, decent compression (crf=23)
  balanced  Balance of speed and compression (crf=22, default)
  quality   Better quality, slower, less compression (crf=20)
  compact   Force 1080p max, good compression (crf=24)
  tiny      Force 720p, maximum compression (crf=26)

Examples:
  # Dry-run on specific files
  python -m src.TranscodeMain movie1.mkv movie2.mkv
  
  # Transcode files from a list
  python -m src.TranscodeMain -i large_files.txt --commit
  
  # Force 1080p with commit
  python -m src.TranscodeMain -i files.txt --preset compact --commit
        """,
    )
    
    ap.add_argument(
        "files",
        nargs="*",
        help="Video files to transcode",
    )
    ap.add_argument(
        "-i", "--input-file",
        type=Path,
        help="Text file containing paths to transcode (one per line)",
    )
    ap.add_argument(
        "-p", "--preset",
        choices=list(PRESETS.keys()),
        default="balanced",
        help="Quality preset (default: balanced)",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Actually perform transcodes (default is dry-run)",
    )
    ap.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep original files with .original suffix",
    )
    
    return ap.parse_args()


def main():
    args = parse_args()
    
    # Check ffmpeg
    if not check_ffmpeg():
        print("ERROR: ffmpeg not found. Please install ffmpeg.", file=sys.stderr)
        print("  macOS: brew install ffmpeg", file=sys.stderr)
        print("  Ubuntu: sudo apt install ffmpeg", file=sys.stderr)
        sys.exit(1)
    
    # Collect files
    files: list[Path] = []
    
    if args.input_file:
        if not args.input_file.exists():
            print(f"ERROR: Input file not found: {args.input_file}", file=sys.stderr)
            sys.exit(1)
    
    for f in args.files:
        path = Path(f).expanduser().resolve()
        if path.exists():
            files.append(path)
        else:
            print(f"WARNING: File not found, skipping: {f}", file=sys.stderr)
    
    if not files and not args.input_file:
        print("ERROR: No files specified. Use positional args or --input-file.", file=sys.stderr)
        sys.exit(1)
    
    # Run service
    service = TranscodeService(preset=args.preset)
    
    if args.input_file:
        results = service.transcode_from_file(
            args.input_file,
            commit=args.commit,
            keep_original=args.keep_original,
        )
    else:
        results = service.transcode_files(
            files,
            commit=args.commit,
            keep_original=args.keep_original,
        )
    
    # Exit with error code if any failures
    failures = [r for r in results if not r.success and r.error and "skipped" not in r.error]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
