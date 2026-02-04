#!/bin/bash
# ================================================
# Clean-TV Runner (Commit Mode)
# ================================================
# This script runs Clean-TV with --commit flag.
#
# Configuration via environment variables:
#   CLEAN_TV_DIR - Directory to process (default: /Volumes/Seagate/seagate-qBittorrent)
#   CLEAN_TV_QUARANTINE - Optional quarantine directory for samples
#
# Make executable: chmod +x clean-tv.command

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get parent directory (project root)
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Configuration with defaults
TARGET_DIR="${CLEAN_TV_DIR:-/Volumes/Seagate/seagate-qBittorrent}"
QUARANTINE_DIR="${CLEAN_TV_QUARANTINE:-}"

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT" || exit 1

echo "========================================"
echo "Clean-TV Runner"
echo "========================================"
echo "Project root: $PROJECT_ROOT"
echo "PYTHONPATH:   $PYTHONPATH"
echo "Processing:   $TARGET_DIR"
if [ -n "$QUARANTINE_DIR" ]; then
    echo "Quarantine:   $QUARANTINE_DIR"
fi
echo "Mode:         COMMIT (changes will be applied)"
echo "----------------------------------------"

# Check if target directory exists
if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory does not exist: $TARGET_DIR"
    echo ""
    echo "Set CLEAN_TV_DIR environment variable to specify a different directory:"
    echo "  export CLEAN_TV_DIR=\"/path/to/your/tv/directory\""
    echo ""
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

# Build command
CMD="python3 -m src.Main --directory \"$TARGET_DIR\" --commit"
if [ -n "$QUARANTINE_DIR" ]; then
    CMD="$CMD --quarantine \"$QUARANTINE_DIR\""
fi

# Run
eval "$CMD"

echo "----------------------------------------"
echo "Clean-TV finished."
read -n 1 -s -r -p "Press any key to close..."
