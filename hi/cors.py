"""Shared CORS support for `hi`'s loopback-only HTTP servers
(`hi/ipc/server.py`, `hi/orchestrator/pending_http.py`) — added
specifically so the new browser-based `frontend/` (a Vite dev server on
a fixed local port) can reach them; the Swift voice companion never
needed this at all, since `URLSession` has no same-origin/CORS concept.

Deliberately NOT a wildcard `Access-Control-Allow-Origin: *`: these
servers bind to `127.0.0.1` only and are otherwise unreachable from the
network per their own docstrings — but CORS specifically controls
whether **in-browser JavaScript** can read a response, not whether a
request can be sent at all, so a wildcard would let *any* web page the
user happens to have open in another tab read this server's real output
(conversation content, vault paths, model names) just by knowing it
listens on localhost. Scoped to the frontend's own known dev origin
instead, so that property isn't quietly given up for every other site
in the user's browser.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

# frontend/vite.config.ts pins the dev server to this exact port — kept
# in sync with that, not guessed independently.
_ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def send_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    """Call once per response, before `end_headers()` — a no-op if the
    request's Origin isn't the known frontend dev origin."""
    origin = handler.headers.get("Origin")
    if origin in _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")


def send_cors_preflight(handler: BaseHTTPRequestHandler) -> None:
    """A full `OPTIONS` preflight response — the browser sends one of
    these before any POST carrying a `Content-Type: application/json`
    body (not a "simple" request), for every POST route these servers
    have.

    Doesn't call `send_cors_headers()` itself — `hi/ipc/server.py`'s
    `_Handler` (the only caller) overrides `send_response()` to add it
    automatically, and adding it again here would send the header
    twice. If a future caller's handler doesn't have that override,
    this would silently need it added back — not a risk today since
    this is only ever called on that one handler.
    """
    handler.send_response(204)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
