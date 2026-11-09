#!/usr/bin/env bash
# check_access_group.sh — PreToolUse hook: verify agent's groups allow access to path
# Called with: check_access_group.sh <agent-name> <action> <path>
# Returns: 0=allowed, 1=denied

AGENT="${1:-}"
ACTION="${2:-read}"
PATH_TARGET="${3:-}"

if [ -z "$AGENT" ] || [ -z "$PATH_TARGET" ]; then
    exit 0  # No-op if not called with args
fi

TOKEN_FILE="$HOME/.pi/session_identity/${AGENT}/current.txt"
if [ ! -f "$TOKEN_FILE" ]; then
    # No token = no identity = deny
    echo "[ACCESS-DENIED] No capability token for agent: $AGENT" >&2
    exit 1
fi

# Read groups from token
TOKEN_ID=$(cat "$TOKEN_FILE" | tr -d ' \t\n\r')
TOKEN_PATH="$HOME/.pi/session_identity/${AGENT}/${TOKEN_ID}.yaml"
if [ ! -f "$TOKEN_PATH" ]; then
    echo "[ACCESS-DENIED] Token file missing: $TOKEN_ID" >&2
    exit 1
fi

# Check groups
# In a real implementation, parse the YAML and check groups
# For now, check hard-walls
HARD_WALLS=$(grep "hard_walls:" "$TOKEN_PATH" -A 99 | grep "^\s*-" | sed 's/^  *-\s*//' | tr '\n' '|')

# Check if path is in hard-walls
if [ -n "$HARD_WALLS" ]; then
    for wall in $(echo "$HARD_WALLS" | tr '|' ' '); do
        if [[ "$PATH_TARGET" == *"$wall"* ]]; then
            echo "[ACCESS-DENIED] Path in hard-wall: $wall" >&2
            exit 1
        fi
    done
fi

exit 0
