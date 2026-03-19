#!/bin/bash
# ================================================
# Install/Uninstall Clean Media Watchers
# ================================================
# Usage:
#   ./install-watcher.sh install [tv|movie|all]
#   ./install-watcher.sh uninstall [tv|movie|all]
#   ./install-watcher.sh status
#   ./install-watcher.sh logs [tv|movie]
# ================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_DIR="$SCRIPT_DIR/../logs"

TV_PLIST="com.nulleffect.clean-tv-watcher.plist"
MOVIE_PLIST="com.nulleffect.clean-movie-watcher.plist"

install_watcher() {
    local type=$1
    local plist_name=$2
    local watch_script=$3
    
    echo "Installing Clean-${type} Watcher..."
    
    local plist_src="$SCRIPT_DIR/$plist_name"
    local plist_dst="$HOME/Library/LaunchAgents/$plist_name"
    
    # Make script executable
    chmod +x "$SCRIPT_DIR/$watch_script"
    
    # Copy plist
    cp "$plist_src" "$plist_dst"
    echo "  Copied plist to $plist_dst"
    
    # Load LaunchAgent
    launchctl load "$plist_dst"
    echo "  LaunchAgent loaded."
    
    echo "✓ Clean-${type} Watcher installed!"
}

uninstall_watcher() {
    local type=$1
    local plist_name=$2
    
    echo "Uninstalling Clean-${type} Watcher..."
    
    local plist_dst="$HOME/Library/LaunchAgents/$plist_name"
    
    if [ -f "$plist_dst" ]; then
        launchctl unload "$plist_dst" 2>/dev/null
        rm "$plist_dst"
        echo "  LaunchAgent removed."
        echo "✓ Clean-${type} Watcher uninstalled."
    else
        echo "  Clean-${type} Watcher not installed."
    fi
}

check_status() {
    local type=$1
    local plist_name=$2
    local log_file=$3
    
    local plist_dst="$HOME/Library/LaunchAgents/$plist_name"
    
    echo "$type Watcher:"
    
    if [ -f "$plist_dst" ]; then
        echo "  Installed: Yes"
    else
        echo "  Installed: No"
    fi
    
    if launchctl list 2>/dev/null | grep -q "${plist_name%.plist}"; then
        echo "  Running:   Yes"
    else
        echo "  Running:   No"
    fi
    
    if [ -f "$LOG_DIR/$log_file" ]; then
        local last_entry=$(tail -1 "$LOG_DIR/$log_file" 2>/dev/null)
        echo "  Last log:  $last_entry"
    fi
    echo ""
}

case "$1" in
    install)
        # Check fswatch
        if ! command -v fswatch &> /dev/null; then
            echo "ERROR: fswatch not found."
            echo "Install with: brew install fswatch"
            exit 1
        fi
        
        # Create logs directory
        mkdir -p "$LOG_DIR"
        
        # Make command scripts executable
        chmod +x "$SCRIPT_DIR/clean-tv.command" 2>/dev/null
        chmod +x "$SCRIPT_DIR/clean-movie.command" 2>/dev/null
        
        case "${2:-all}" in
            tv)
                install_watcher "TV" "$TV_PLIST" "watch-tv.sh"
                ;;
            movie)
                install_watcher "Movie" "$MOVIE_PLIST" "watch-movie.sh"
                ;;
            all)
                install_watcher "TV" "$TV_PLIST" "watch-tv.sh"
                echo ""
                install_watcher "Movie" "$MOVIE_PLIST" "watch-movie.sh"
                ;;
            *)
                echo "Unknown type: $2"
                echo "Usage: $0 install [tv|movie|all]"
                exit 1
                ;;
        esac
        
        echo ""
        echo "Watchers will auto-start when Seagate drive is mounted."
        echo "Logs: $LOG_DIR/"
        ;;
        
    uninstall)
        case "${2:-all}" in
            tv)
                uninstall_watcher "TV" "$TV_PLIST"
                ;;
            movie)
                uninstall_watcher "Movie" "$MOVIE_PLIST"
                ;;
            all)
                uninstall_watcher "TV" "$TV_PLIST"
                uninstall_watcher "Movie" "$MOVIE_PLIST"
                ;;
            *)
                echo "Unknown type: $2"
                echo "Usage: $0 uninstall [tv|movie|all]"
                exit 1
                ;;
        esac
        ;;
        
    status)
        echo "Clean Media Watcher Status"
        echo "==========================="
        echo ""
        
        if [ -d "/Volumes/Seagate" ]; then
            echo "Seagate Drive: Mounted ✓"
        else
            echo "Seagate Drive: Not mounted"
        fi
        echo ""
        
        check_status "TV" "$TV_PLIST" "watch-tv.log"
        check_status "Movie" "$MOVIE_PLIST" "watch-movie.log"
        ;;
        
    logs)
        case "${2:-tv}" in
            tv)
                log_file="$LOG_DIR/watch-tv.log"
                ;;
            movie)
                log_file="$LOG_DIR/watch-movie.log"
                ;;
            *)
                echo "Unknown type: $2"
                echo "Usage: $0 logs [tv|movie]"
                exit 1
                ;;
        esac
        
        if [ -f "$log_file" ]; then
            tail -f "$log_file"
        else
            echo "No log file yet: $log_file"
        fi
        ;;
        
    *)
        echo "Clean Media Watcher Manager"
        echo ""
        echo "Usage: $0 {install|uninstall|status|logs} [tv|movie|all]"
        echo ""
        echo "Commands:"
        echo "  install [tv|movie|all]    Install watcher(s) (default: all)"
        echo "  uninstall [tv|movie|all]  Remove watcher(s) (default: all)"
        echo "  status                    Check status of all watchers"
        echo "  logs [tv|movie]           Tail log file (default: tv)"
        echo ""
        echo "Examples:"
        echo "  $0 install                # Install both watchers"
        echo "  $0 install tv             # Install only TV watcher"
        echo "  $0 uninstall movie        # Remove only movie watcher"
        echo "  $0 logs movie             # Tail movie watcher log"
        exit 1
        ;;
esac
