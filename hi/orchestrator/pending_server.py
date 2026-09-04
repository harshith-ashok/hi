"""A dedicated HTTP server for `hi/orchestrator/pending_actions.py`'s
queue (TODO.md Phase 17), started as a background thread whenever
`hi/repl.py`'s `run_router_repl()` begins.

**Why a second server, when `hi/ipc/server.py` also has `/pending`
routes**: an orchestrated run (TODO.md Phase 16) can happen in *either*
process now — the interactive terminal REPL, or (since TODO.md Phase 18
wired `run_orchestrated()` into `hi/ipc/server.py`'s own `/query`) the
voice companion's backend too. Each process's own in-memory queue only
ever holds actions from runs *that process* triggered, so each needs
its own reachable `/pending` surface — there's no single shared queue
to expose from one place. This server exposes the SAME shared route
logic (`hi/orchestrator/pending_http.py`) for the REPL's own process,
on a different port (8766, not the voice companion's 8765) so both can
run at once without conflicting — a normal terminal session alongside
the voice companion is a real, plausible setup, not a hypothetical one.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hi.orchestrator.pending_http import try_handle_pending_get, try_handle_pending_post

HOST = "127.0.0.1"
DEFAULT_PORT = 8766


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # quiet by default, same as hi/ipc/server.py's own handler

    def do_GET(self) -> None:
        if try_handle_pending_get(self):
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        if try_handle_pending_post(self):
            return
        self.send_error(404, "Not found")


def start_pending_server(port: int = DEFAULT_PORT) -> None:
    """Blocks forever (`serve_forever()`) — call this from a daemon
    thread, never the main thread. A bind failure (the port already in
    use — a second `hi` session on the same machine, most likely) is
    swallowed rather than crashing the whole REPL over what's a
    nice-to-have indicator surface, not a required one."""
    try:
        server = ThreadingHTTPServer((HOST, port), _Handler)
    except OSError:
        return
    server.serve_forever()
