#!/bin/bash
# Transcode large video files to HEVC
# Usage: ./transcode.command [--commit] [files...]
#
# If no files specified, reads from large_files.txt in the same directory

cd "$(dirname "$0")/.."

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg not found. Install with: brew install ffmpeg"
    exit 1
fi

# Default to dry-run
COMMIT=""
if [[ "$1" == "--commit" ]]; then
    COMMIT="--commit"
    shift
fi

if [[ $# -gt 0 ]]; then
    # Files specified on command line
    python3 -m src.TranscodeMain $COMMIT "$@"
else
    # Read from large_files.txt
    INPUT_FILE="$(dirname "$0")/large_files.txt"
    if [[ -f "$INPUT_FILE" ]]; then
        python3 -m src.TranscodeMain $COMMIT --input-file "$INPUT_FILE"
    else
        echo "No files specified and $INPUT_FILE not found."
        echo ""
        echo "Usage:"
        echo "  ./transcode.command [--commit] file1.mkv file2.mkv"
        echo "  ./transcode.command [--commit]  # reads from scripts/large_files.txt"
        echo ""
        echo "Create large_files.txt with paths to transcode, one per line."
        exit 1
    fi
fi
