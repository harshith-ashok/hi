"""Shared HTTP route logic for the pending-approval queue (TODO.md
Phase 17) — factored out so both `hi/ipc/server.py` (the voice
companion's own process) and `hi/orchestrator/pending_server.py` (the
terminal REPL's own dedicated server — see that module's docstring for
why a second server exists at all) expose the identical `/pending`
routes without duplicating the actual handling logic, only which port
each binds.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from hi.orchestrator.pending_actions import list_pending, resolve

# Neither route below calls hi/cors.py's send_cors_headers() itself —
# hi/ipc/server.py's own _Handler overrides send_response() to add it
# automatically for every response (including these, since Python
# dispatches handler.send_response(...) to whatever the actual instance
# overrides), and hi/orchestrator/pending_server.py's REPL-only handler
# (the other caller of these functions) deliberately has no CORS at
# all — port 8766 is never meant to be reached from a browser. Calling
# it explicitly here would either double the header (the first case) or
# wrongly add it where it was never wanted (the second).


def try_handle_pending_get(handler: BaseHTTPRequestHandler) -> bool:
    """Returns True if this request was `GET /pending` and has already
    been fully responded to — the caller's own `do_GET` should return
    immediately in that case, or fall through to its other routes if
    this returns False."""
    if handler.path != "/pending":
        return False
    payload = [
        {"id": a.id, "description": a.description, "created_at": a.created_at}
        for a in list_pending()
    ]
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def try_handle_pending_post(handler: BaseHTTPRequestHandler) -> bool:
    """Same contract as `try_handle_pending_get()`, for
    `POST /pending/{id}/approve|deny`."""
    parts = handler.path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "pending" or parts[2] not in ("approve", "deny"):
        return False
    ok = resolve(parts[1], approved=(parts[2] == "approve"))
    if not ok:
        handler.send_error(404, f"No pending action '{parts[1]}' (already resolved, or never existed)")
        return True
    handler.send_response(204)
    handler.end_headers()
    return True
