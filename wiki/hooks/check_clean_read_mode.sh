#!/usr/bin/env bash
# check_clean_read_mode.sh — PreToolUse hook: check for clean-read mode sentinels
# Called with: check_clean_read_mode.sh <agent-name> <action> <path>
# If a sentinel file exists within its TTL, deny access

AGENT="${1:-}"
ACTION="${2:-read}"
PATH_TARGET="${3:-}"

if [ -z "$AGENT" ]; then
    exit 0
fi

SENTINEL_DIR="$HOME/.pi/session_identity/${AGENT}/sentinels"
if [ -d "$SENTINEL_DIR" ]; then
    for sentinel in "$SENTINEL_DIR"/*.sentinel; do
        [ -f "$sentinel" ] || continue
        
        # Read TTL (seconds)
        TTL=$(head -1 "$sentinel" | tr -d '\r')
        CREATION=$(stat -c %Y "$sentinel" 2>/dev/null || stat -f %m "$sentinel" 2>/dev/null)
        NOW=$(date +%s)
        ELAPSED=$((NOW - CREATION))
        
        if [ "$ELAPSED" -lt "$TTL" ]; then
            # Sentinel is still active
            SENTINEL_NAME=$(basename "$sentinel" .sentinel)
            echo "[CLEAN-READ] Sentinel active: $SENTINEL_NAME (${SENTINEL_NAME}.sentinel, ${TTL}s TTL, ${ELAPSED}s elapsed)" >&2
            exit 1
        fi
        
        # TTL expired — remove sentinel
        rm -f "$sentinel"
    done
fi

exit 0
