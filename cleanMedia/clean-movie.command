#!/bin/bash
# ================================================
# Clean-Movie Runner (Commit Mode)
# ================================================
# This script runs Clean-Movie with --commit flag.
#
# Configuration via environment variables:
#   CLEAN_MOVIE_DIR - Directory to process (default: /Volumes/Seagate/seagate-movie)
#   CLEAN_MOVIE_QUARANTINE - Optional quarantine directory for samples/trailers
#   TMDB_API_KEY - Optional TMDB API key for year lookups
#
# Make executable: chmod +x clean-movie.command

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get parent directory (project root)
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Configuration with defaults
TARGET_DIR="${CLEAN_MOVIE_DIR:-/Volumes/Seagate/seagate-movie}"
QUARANTINE_DIR="${CLEAN_MOVIE_QUARANTINE:-}"

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT" || exit 1

echo "========================================"
echo "Clean-Movie Runner"
echo "========================================"
echo "Project root: $PROJECT_ROOT"
echo "PYTHONPATH:   $PYTHONPATH"
echo "Processing:   $TARGET_DIR"
if [ -n "$QUARANTINE_DIR" ]; then
    echo "Quarantine:   $QUARANTINE_DIR"
fi
if [ -n "$TMDB_API_KEY" ]; then
    echo "TMDB Lookup:  Enabled"
else
    echo "TMDB Lookup:  Disabled (set TMDB_API_KEY to enable)"
fi
echo "Mode:         COMMIT (changes will be applied)"
echo "----------------------------------------"

# Check if target directory exists
if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory does not exist: $TARGET_DIR"
    echo ""
    echo "Set CLEAN_MOVIE_DIR environment variable to specify a different directory:"
    echo "  export CLEAN_MOVIE_DIR=\"/path/to/your/movie/directory\""
    echo ""
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

# Build command
CMD="python3 -m src.MovieMain --directory \"$TARGET_DIR\" --commit"
if [ -n "$QUARANTINE_DIR" ]; then
    CMD="$CMD --quarantine \"$QUARANTINE_DIR\""
fi
if [ -n "$TMDB_API_KEY" ]; then
    CMD="$CMD --lookup"
fi

# Run
eval "$CMD"

echo "----------------------------------------"
echo "Clean-Movie finished."
read -n 1 -s -r -p "Press any key to close..."
