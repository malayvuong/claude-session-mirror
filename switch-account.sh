#!/usr/bin/env bash
# One shot after signing in with another Claude account on this Mac: pull every Code-tab session and scheduled task
# of the other account profiles into the signed-in profile, then restart the Claude desktop app.
# Run it from Terminal.app, not from inside a Claude session (the restart would end that session).
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude_session_mirror.py" switch "$@"
