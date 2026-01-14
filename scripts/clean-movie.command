#!/bin/bash
# ================================================
# Clean-Movie Runner (Commit Mode)
# ================================================
# This script runs Clean-Movie with --commit flag.
# Make sure it has executable permission:
#   chmod +x clean-movie.command

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get parent directory (project root)
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Directory to process - modify as needed
TARGET_DIR="/Volumes/Seagate/seagate-movie"

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT" || exit 1

echo "Running Clean-Movie in COMMIT mode..."
echo "Project root: $PROJECT_ROOT"
echo "PYTHONPATH:   $PYTHONPATH"
echo "Processing:   $TARGET_DIR"
echo "-----------------------------------"

# Run MovieMain.py with --commit flag
python3 -m src.MovieMain --directory "$TARGET_DIR" --commit

echo "-----------------------------------"
echo "Clean-Movie finished."
read -n 1 -s -r -p "Press any key to close..."
