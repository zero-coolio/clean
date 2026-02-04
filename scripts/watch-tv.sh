#!/bin/bash
# ================================================
# Clean-TV File Watcher
# ================================================
# Uses fswatch to monitor qBittorrent directory and
# trigger clean-tv.command when files are added.
#
# Requirements:
#   brew install fswatch
#
# Usage:
#   ./watch-tv.sh              # Run in foreground
#   ./watch-tv.sh --once       # Run clean once then exit
#
# ================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WATCH_DIR="${CLEAN_TV_DIR:-/Volumes/Seagate/seagate-qBittorrent}"
LOG_FILE="$SCRIPT_DIR/../logs/watch-tv.log"
LOCK_FILE="$SCRIPT_DIR/../logs/.watch-tv.lock"
DEBOUNCE_SECONDS=30
LAST_RUN=0

# Create logs directory
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

notify() {
    local title="$1"
    local message="$2"
    osascript -e 'display notification "'"$message"'" with title "'"$title"'"'
    afplay /System/Library/Sounds/Glass.aiff &
}

run_clean() {
    local now=$(date +%s)
    local elapsed=$((now - LAST_RUN))
    
    # Debounce: skip if we ran recently
    if [ $elapsed -lt $DEBOUNCE_SECONDS ]; then
        log "Skipping (ran ${elapsed}s ago, debounce is ${DEBOUNCE_SECONDS}s)"
        return
    fi
    
    # Lock: skip if already running
    if [ -f "$LOCK_FILE" ]; then
        log "Skipping (already running)"
        return
    fi
    
    # Create lock file with PID
    echo "$$" > "$LOCK_FILE"
    trap "rm -f '$LOCK_FILE'" EXIT
    
    LAST_RUN=$now
    log "Running clean-tv..."
    notify "Clean-TV" "Processing new files..."
    
    # Run clean-tv
    cd "$SCRIPT_DIR/.."
    export PYTHONPATH="$SCRIPT_DIR/.."
    python3 -m src.Main --directory "$WATCH_DIR" --commit 2>&1 | tee -a "$LOG_FILE"
    local exit_code=${PIPESTATUS[0]}
    
    if [ $exit_code -eq 0 ]; then
        notify "Clean-TV" "✓ Finished successfully"
    else
        notify "Clean-TV" "✗ Finished with errors"
    fi
    
    # Remove lock file
    rm -f "$LOCK_FILE"
    trap - EXIT
    
    log "Clean-tv finished."
}

# Check for fswatch
if ! command -v fswatch &> /dev/null; then
    log "ERROR: fswatch not found. Install with: brew install fswatch"
    exit 1
fi

# Check if watch directory exists
if [ ! -d "$WATCH_DIR" ]; then
    log "ERROR: Watch directory does not exist: $WATCH_DIR"
    log "Is the Seagate drive mounted?"
    exit 1
fi

# One-shot mode
if [ "$1" == "--once" ]; then
    log "Running once..."
    LAST_RUN=0
    run_clean
    exit 0
fi

log "========================================"
log "Clean-TV Watcher Starting"
log "========================================"
log "Watching: $WATCH_DIR"
log "Debounce: ${DEBOUNCE_SECONDS}s"
log "Log file: $LOG_FILE"
log "----------------------------------------"

# Run once at startup
run_clean

# Watch for changes
# -r: recursive
# -L: follow symlinks  
# --event Created, MovedTo, Renamed: new/moved/renamed files
fswatch -r -L --event Created --event MovedTo --event Renamed "$WATCH_DIR" | while read -r file; do
    log "Change detected: $file"
    run_clean
done
