#!/bin/bash
# ================================================
# Clean-TV Runner (Commit Mode)
# ================================================
# This script runs Clean-TV with --commit flag.
# Make sure it has executable permission:
#   chmod +x run_clean_tv_commit.command

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Get parent directory (project root)
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Directory to process - you can modify this
TARGET_DIR="/Volumes/Seagate/seagate-qBittorrent"

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT" || exit 1

echo "Running Clean-TV in COMMIT mode..."
echo "Project root: $PROJECT_ROOT"
echo "PYTHONPATH:   $PYTHONPATH"
echo "Processing:   $TARGET_DIR"
echo "-----------------------------------"

# Run Main.py with --commit flag
python3 -m src.Main --directory "$TARGET_DIR" --commit

echo "-----------------------------------"
echo "Clean-TV finished."
read -n 1 -s -r -p "Press any key to close..."