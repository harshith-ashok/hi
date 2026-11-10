"""Runs on the Mac, next to Docker: lets the containerized backend use the tools
that need the real machine (hi/host.py lists them). `hi` starts it with the stack.

POST /tool {"name", "args"} runs one allowlisted tool and returns {"result": text}.
Requests need `Authorization: Bearer <HOST_BRIDGE_TOKEN>` (kept in ~/.hi/.env and
given only to the backend, never to the sandbox). Nothing else is executed.

Run directly: python -m hi.host_bridge
"""

from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import hi.config as config
from hi.host import HOST_TOOLS


def ensure_token() -> str:
    """The shared secret, created in ~/.hi/.env on first use."""
    if not config.HOST_BRIDGE_TOKEN:
        config.set_value("HOST_BRIDGE_TOKEN", secrets.token_urlsafe(32))
    return config.HOST_BRIDGE_TOKEN


def _tools() -> dict:
    from hi.agents.butler import mac_control, music, timers
    from hi.context import tools as context_tools
    from hi.agents.term import host_git
    from hi.browser import open_url_in_browser
    from hi.perception.browser import observe_current_tab
    from hi.perception.screen import read_screen
    from hi.perception.vision import ask_about_screen

    found = {
        t.name: t
        for t in [
            *(getattr(mac_control, n) for n in dir(mac_control)),
            *(getattr(music, n) for n in dir(music)),
            *(getattr(timers, n) for n in dir(timers)),
            *(getattr(context_tools, n) for n in dir(context_tools)),
            *(getattr(host_git, n) for n in dir(host_git)),
            open_url_in_browser, observe_current_tab, read_screen, ask_about_screen,
        ]
        if hasattr(t, "invoke") and getattr(t, "name", None) in HOST_TOOLS
    }
    missing = HOST_TOOLS - found.keys()
    if missing:
        raise RuntimeError(f"host tools not found: {sorted(missing)}")
    return found


class Handler(BaseHTTPRequestHandler):
    tools: dict = {}
    token = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"ok": True, "tools": sorted(self.tools)} if self.path == "/health" else {"error": "not found"},
                   200 if self.path == "/health" else 404)

    def do_POST(self) -> None:
        if self.path != "/tool":
            return self._send({"error": "not found"}, 404)
        sent = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(sent.encode(), self.token.encode()):
            return self._send({"error": "unauthorized"}, 401)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            tool, args = self.tools.get(body["name"]), body.get("args") or {}
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._send({"error": "expected {name, args}"}, 400)
        if tool is None or not isinstance(args, dict):
            return self._send({"error": f"unknown tool {body.get('name')!r}"}, 404)
        try:
            self._send({"result": str(tool.invoke(args))})
        except Exception as e:  # a tool failure is a result for the model, not a crash
            self._send({"result": f"{body['name']} failed: {e}"})


def main() -> None:
    Handler.tools, Handler.token = _tools(), ensure_token()
    server = ThreadingHTTPServer((config.HOST_BRIDGE_BIND, config.HOST_BRIDGE_PORT), Handler)
    print(f"host bridge on {config.HOST_BRIDGE_BIND}:{config.HOST_BRIDGE_PORT} ({len(Handler.tools)} tools)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
