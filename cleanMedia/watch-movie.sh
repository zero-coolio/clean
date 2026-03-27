#!/bin/bash
# ================================================
# Clean-Movie File Watcher
# ================================================
# Uses fswatch to monitor movie directory and
# trigger clean-movie when files are added.
#
# Requirements:
#   brew install fswatch
#
# Usage:
#   ./watch-movie.sh              # Run in foreground
#   ./watch-movie.sh --once       # Run clean once then exit
#
# ================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WATCH_DIR="${CLEAN_MOVIE_DIR:-/Volumes/Seagate/seagate-movie}"
LOG_FILE="$SCRIPT_DIR/../logs/watch-movie.log"
LOCK_FILE="$SCRIPT_DIR/../logs/.watch-movie.lock"
PENDING_FILE="$SCRIPT_DIR/../logs/.watch-movie-pending.txt"
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
    
    # Lock: skip if already running (validate PID is still alive)
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid
        lock_pid=$(cat "$LOCK_FILE" 2>/dev/null)
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            log "Skipping (already running, PID $lock_pid)"
            return
        else
            log "Removing stale lock file (PID $lock_pid no longer exists)"
            rm -f "$LOCK_FILE"
        fi
    fi
    
    # Create lock file with PID
    echo "$$" > "$LOCK_FILE"
    trap "rm -f '$LOCK_FILE'" EXIT
    
    LAST_RUN=$now
    log "Running clean-movie..."

    # Build file list from accumulated pending files
    local file_msg="Processing new files..."
    if [ -f "$PENDING_FILE" ] && [ -s "$PENDING_FILE" ]; then
        local names
        names=$(sort -u "$PENDING_FILE" | xargs -I{} basename "{}" | head -5)
        local total
        total=$(sort -u "$PENDING_FILE" | wc -l | tr -d ' ')
        local shown
        shown=$(echo "$names" | wc -l | tr -d ' ')
        local joined
        joined=$(echo "$names" | paste -sd ', ' -)
        if [ "$total" -gt "$shown" ]; then
            file_msg="$joined and $((total - shown)) more"
        else
            file_msg="$joined"
        fi
        > "$PENDING_FILE"
    fi

    notify "Clean-Movie" "Processing: $file_msg"

    # Run clean-movie
    cd "$SCRIPT_DIR/.."
    export PYTHONPATH="$SCRIPT_DIR/.."
    
    # Build command with optional TMDB lookup
    CMD="python3 -m src.MovieMain --directory \"$WATCH_DIR\" --commit"
    if [ -n "$TMDB_API_KEY" ]; then
        CMD="$CMD --lookup"
    fi
    
    eval "$CMD" 2>&1 | tee -a "$LOG_FILE"
    local exit_code=${PIPESTATUS[0]}
    
    if [ $exit_code -eq 0 ]; then
        notify "Clean-Movie" "✓ Finished successfully"
    else
        notify "Clean-Movie" "✗ Finished with errors"
    fi
    
    # Remove lock file
    rm -f "$LOCK_FILE"
    trap - EXIT
    
    log "Clean-movie finished."
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
log "Clean-Movie Watcher Starting"
log "========================================"
log "Watching: $WATCH_DIR"
log "Debounce: ${DEBOUNCE_SECONDS}s"
log "Log file: $LOG_FILE"
if [ -n "$TMDB_API_KEY" ]; then
    log "TMDB:     Enabled"
else
    log "TMDB:     Disabled (set TMDB_API_KEY to enable)"
fi
log "----------------------------------------"

# Run once at startup
run_clean

# Watch for changes
# -r: recursive
# -L: follow symlinks
# --event Created, Updated, MovedTo, Renamed: new, touched, moved/renamed files
fswatch -r -L \
    --exclude '\.jsonl$' \
    --exclude '\.DS_Store$' \
    --event Created --event Updated --event MovedTo --event Renamed \
    "$WATCH_DIR" | while read -r file; do
    log "Change detected: $file"
    echo "$file" >> "$PENDING_FILE"
    run_clean
done
