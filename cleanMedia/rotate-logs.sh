#!/bin/bash
# ================================================
# CleanMedia log rotation (daily)
# ================================================
# Run by the launchd agent com.nulleffect.clean-log-rotate at 00:05 daily.
#
# Strategy: copytruncate. For each log we gzip a timestamped copy, then
# truncate the original IN PLACE (`: > file`). Both writers here append
# (launchd StandardOut/Err open O_APPEND; the per-run `tee -a` likewise),
# so truncating in place is safe — the writer keeps its fd and simply
# resumes appending from offset 0. This avoids the move-aside problem where
# a long-lived launchd fd keeps writing to the renamed inode and the new
# file stays empty.
#
# Keeps ROTATE_KEEP days of gzipped history per log; older ones are pruned.
#
# Manual run (also reclaims space immediately):
#   ./rotate-logs.sh
# ================================================

set -euo pipefail

LOG_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../logs" && pwd )"
ROTATE_KEEP="${ROTATE_KEEP:-7}"
STAMP="$( date +%Y%m%d-%H%M%S )"

# Logs to rotate. The launchd StandardOut duplicates are included so this
# keeps working even before they are retired to /dev/null in the plists.
LOGS=(
    watch-tv.log
    watch-movie.log
    launchd-stdout.log
    launchd-stderr.log
    launchd-movie-stdout.log
    launchd-movie-stderr.log
)

log() { echo "[$( date '+%Y-%m-%d %H:%M:%S' )] $1"; }

rotate_one() {
    local f="$LOG_DIR/$1"
    [ -f "$f" ] || return 0   # nothing to rotate
    [ -s "$f" ] || return 0   # skip empty logs
    gzip -c -- "$f" > "$f.$STAMP.gz"
    : > "$f"                  # truncate in place, preserving any writer fd
    log "rotated $1 -> $1.$STAMP.gz ($( du -h "$f.$STAMP.gz" | cut -f1 ))"
}

prune_one() {
    local base="$1"
    local files
    files=$( ls -1t "$LOG_DIR/$base".*.gz 2>/dev/null || true )
    [ -n "$files" ] || return 0
    echo "$files" | tail -n +$(( ROTATE_KEEP + 1 )) | while read -r old; do
        [ -n "$old" ] || continue
        rm -f -- "$old"
        log "pruned $( basename "$old" )"
    done
}

mkdir -p "$LOG_DIR"
log "=== CleanMedia log rotation start (keep ${ROTATE_KEEP}) ==="
for l in "${LOGS[@]}"; do
    rotate_one "$l"
    prune_one "$l"
done
log "=== CleanMedia log rotation done ==="
