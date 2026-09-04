#!/bin/bash
# Convenience launcher: starts the Python backend (hi --voice-daemon) if
# it isn't already listening, builds/packages the app if needed, then
# opens it. The two are independent processes by design (TODO.md: "a
# voice frontend that talks to the same `hi` backend... over local IPC")
# — this script just saves typing two commands.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! curl -s -o /dev/null --max-time 1 http://127.0.0.1:8765/query -X POST -d '{}'; then
    echo "Starting hi --voice-daemon in the background..."
    (cd .. && uv run python -m hi.cli --voice-daemon > /tmp/hi-voice-daemon.log 2>&1 &)
    sleep 1
fi

./Scripts/build_app.sh

open "$(swift build --show-bin-path)/hi Voice.app"
