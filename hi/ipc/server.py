"""Local IPC layer for the native macOS voice companion app (TODO.md
Phase 5, "Backend integration"): a loopback-only HTTP server the Swift
app talks to, driving the *exact same* router-mode backend
hi/repl.py's run_router_repl() already uses — hi/router.py's classify()
picks a (persona, tier) per query, hi/personas.py builds/caches the
agent, hi/vault.py logs the conversation. The voice app inherits all of
that instead of duplicating any of it, per this phase's own framing ("it
inherits all the task/memory/agent logic above instead of duplicating
any of it").

Loopback-only (127.0.0.1), fixed local port, never reachable from the
network. Streaming is now AG-UI's own SSE framing (TODO.md Phase 18,
`hi/agui_adapter.py`) over the same plain HTTP/1.0 body-until-close
response as before — no manually-implemented chunked transfer encoding,
no WebSockets, still a strictly one-request/one-streamed-response
protocol. **This replaces the old hand-rolled `{event: persona/token/
done}` NDJSON shape entirely** — the voice companion's own
`BackendClient.swift` needed matching decode-side updates (done in the
same phase, not left as a dangling follow-up).

Run with: hi --voice-daemon
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ag_ui.core import events as ag
from ag_ui.encoder import EventEncoder

import hi.config as config
from hi.agui_adapter import stream_agent_as_agui, stream_orchestrated_as_agui_sync
from hi.briefing import build_briefing
from hi.cors import send_cors_headers, send_cors_preflight
from hi.env_file import ENV_PATH, write_env_var
from hi.ipc.spoken_summary import make_spoken_summary
from hi.models import get_tier_model
from hi.orchestrator.complexity import classify_with_plan
from hi.orchestrator.pending_http import try_handle_pending_get, try_handle_pending_post
from hi.personas import PERSONAS, get_agent_builder
from hi.vault import list_conversations, log_conversation, read_conversation

# Settings the native app's Settings screen can read/write (TODO.md's
# "proper native app" ask) — plain model-name/path fields only, not the
# MCP credentials (GITHUB_PERSONAL_ACCESS_TOKEN/OBSIDIAN_REST_API_KEY):
# those stay write-only, surfaced instead via hi/mcp_install.py's own
# configured/not-configured status, so a GET here never risks echoing a
# secret back to whatever's reading the response.
_CONFIG_FIELDS = (
    "VAULT_PATH", "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "TERM_MODEL",
    "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL", "VISION_MODEL",
)

# Tier used when the client forces a specific persona (the panel's tab
# row) instead of letting classify_with_plan() pick one — "typical,
# moderately complex requests, the default for most things"
# (hi/router.py's own TIER_DESCRIPTIONS), a reasonable default absent
# any other signal to pick from, same as classify_with_plan() itself
# falls back to on a parse miss. Forcing a persona also always means
# no orchestrated plan — asking for a specific persona is explicitly
# asking NOT to have the request decomposed across several.
_FORCED_PERSONA_TIER = "sonnet"

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Cached per (persona, tier), same as hi/repl.py's run_router_repl() —
# so cross-turn memory (term's own statefulness) and warm/keep_alive
# model state survive across voice queries in this process too.
_agent_cache: dict[tuple[str, str], object] = {}
_cache_lock = threading.Lock()


def _get_agent(persona_name: str, tier: str):
    key = (persona_name, tier)
    with _cache_lock:
        if key not in _agent_cache:
            _agent_cache[key] = get_agent_builder(persona_name)(get_tier_model(tier))
        return _agent_cache[key]


def stream_query_as_agui(text: str, forced_persona: str | None = None):
    """Yields AG-UI events for one query — a `persona_selected` CUSTOM
    event first (this project's own extension; AG-UI has no built-in
    field for "which persona/tier answered"), then either
    `stream_agent_as_agui()`'s or (TODO.md Phase 16 orchestrated case)
    `stream_orchestrated_as_agui_sync()`'s real events, then a
    `spoken_summary` CUSTOM event once the real final answer is known
    (the same TTS condensation `hi/ipc/spoken_summary.py` already did
    for the old protocol).

    `forced_persona` (the panel's persona-tab row) skips
    `classify_with_plan()` entirely when set to one of `PERSONAS` — the
    same "force a specific persona" behavior `hi --term`/`--butler`/etc.
    already give the terminal, reachable from the voice companion's UI
    too, and (see module docstring) never triggers an orchestrated plan.
    """
    if forced_persona in PERSONAS:
        persona_name, tier, needs_plan = forced_persona, _FORCED_PERSONA_TIER, False
    else:
        persona_name, tier, needs_plan = classify_with_plan(text)

    yield ag.CustomEvent(name="persona_selected", value={"name": persona_name, "tier": tier, "plan": needs_plan})

    thread_id = uuid.uuid4().hex
    if needs_plan:
        events = stream_orchestrated_as_agui_sync(text, thread_id)
        log_persona = "orchestrator"
    else:
        events = stream_agent_as_agui(_get_agent(persona_name, tier), text, thread_id)
        log_persona = persona_name

    final_answer = ""
    for event in events:
        if isinstance(event, ag.RunFinishedEvent) and isinstance(event.result, str):
            final_answer = event.result
        yield event

    if final_answer:
        log_conversation(log_persona, text, final_answer)
        yield ag.CustomEvent(name="spoken_summary", value={"text": make_spoken_summary(final_answer)})


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # body-until-close framing, see module docstring

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # quiet by default — a genuine failure still reaches the client via send_error

    def send_response(self, code: int, message: str | None = None) -> None:
        # Overridden, not just called-manually-per-route: BaseHTTPRequestHandler's
        # own send_error() (used for every 400/404 in this file, e.g.
        # /query's "missing text" — which is exactly what the frontend's
        # own ping() deliberately triggers every 5s to check reachability)
        # calls send_response() internally and sends its OWN response,
        # bypassing whatever CORS header a route handler thinks it added
        # manually afterward. Found live: ping()'s deliberate empty-text
        # 400 came back with no Access-Control-Allow-Origin at all,
        # which a browser treats as a hard CORS failure — a real gap,
        # not a frontend bug. Centralizing here (every response, success
        # or error, calls this exactly once) is what actually guarantees
        # it's never missed again; the individual send_cors_headers()
        # calls that used to sit next to each route's own end_headers()
        # were removed as redundant once this exists.
        super().send_response(code, message)
        send_cors_headers(self)

    def do_POST(self) -> None:
        # /pending/<id>/approve|deny (TODO.md Phase 17), shared with
        # hi/orchestrator/pending_server.py — see that module's own
        # docstring for the full reasoning. Now that TODO.md Phase 18
        # wires the orchestrator into /query below, a destructive action
        # from a plan triggered THROUGH THIS process would correctly
        # show up here too — the two servers' routes both stay correct,
        # this one just also has something real to show now for that one
        # specific path (not for hi/wake.py's or a forced-persona
        # request, which still never trigger a plan — see
        # stream_query_as_agui()).
        if try_handle_pending_post(self):
            return

        if self.path == "/config":
            self._handle_post_config()
            return

        if self.path != "/query":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        text = (body.get("text") or "").strip()
        if not text:
            self.send_error(400, "Missing 'text'")
            return
        forced_persona = body.get("persona") or None

        encoder = EventEncoder()
        self.send_response(200)
        self.send_header("Content-Type", encoder.get_content_type())
        self.end_headers()
        try:
            for event in stream_query_as_agui(text, forced_persona=forced_persona):
                self.wfile.write(encoder.encode(event).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected mid-stream — nothing to clean up

    def _send_json(self, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        # CORS preflight — the browser sends this before POST /query and
        # POST /config (both carry Content-Type: application/json, a
        # non-"simple" request). GETs never trigger a preflight, so this
        # only needs to exist for that reason.
        send_cors_preflight(self)

    def _handle_post_config(self) -> None:
        """Writes Settings-screen changes to ~/.hi/.env — plain model-
        name/path fields only (see _CONFIG_FIELDS). **Honest limitation,
        not silently glossed over**: hi/models.py's TIER_MODELS and
        hi/vault.py's KNOWLEDGE_DIR/CONVERSATIONS_DIR are both built once
        at import time from these same values — updating hi.config's
        in-memory attribute here (so a GET /config right after reflects
        the change) does NOT retroactively change an already-cached
        model/agent or already-computed vault path this process is using.
        Same restart-required caveat hi/mcp_install.py's credential
        writes already carry, for the same underlying reason.
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        if not isinstance(body, dict):
            self.send_error(400, "Expected a JSON object of {field: value}")
            return

        unknown = [k for k in body if k not in _CONFIG_FIELDS]
        if unknown:
            self.send_error(400, f"Unknown field(s): {', '.join(unknown)}")
            return

        updated = []
        for field, value in body.items():
            value = str(value).strip()
            if not value:
                continue
            write_env_var(field, value, path=ENV_PATH)
            # VAULT_PATH is a real Path object on hi.config, not a plain
            # string (every other field here is a string) — setattr'ing
            # a bare str would silently break any code expecting Path
            # operations (hi/vault.py's VAULT_PATH / "hi" / "knowledge").
            setattr(config, field, Path(value) if field == "VAULT_PATH" else value)
            updated.append(field)

        self._send_json({
            "updated": updated,
            "note": (
                "Written to ~/.hi/.env. Restart hi (and the voice daemon) "
                "for model/vault-path changes to actually take effect — "
                "they're read once at process startup, not live-reloaded."
            ),
        })

    def do_GET(self) -> None:
        # See the matching comment in do_POST — same queue, same caveat.
        if try_handle_pending_get(self):
            return

        if self.path == "/briefing":
            # Same gathering hi/repl.py's run_router_repl() runs once at
            # session start — plain filesystem lookups plus one haiku-tier
            # call, cheap enough to just run fresh per request rather than
            # caching/invalidating a snapshot.
            briefing = build_briefing()
            if briefing is None:
                self._send_json(None)
            else:
                context, suggestion, action = briefing
                self._send_json({"context": context, "suggestion": suggestion, "action": action})
            return

        # TODO.md "proper native app": conversation history for a
        # sidebar — the SAME dated logs every persona turn already
        # writes via hi/vault.py's log_conversation(), just read back
        # rather than a new storage mechanism.
        if self.path == "/conversations":
            dates_text = list_conversations.invoke({})
            dates = [] if dates_text == "No conversation logs exist yet." else dates_text.splitlines()
            self._send_json(sorted(dates, reverse=True))
            return

        if self.path.startswith("/conversations/"):
            date = self.path.removeprefix("/conversations/")
            content = read_conversation.invoke({"date": date})
            if content.startswith("No conversation log for"):
                self.send_error(404, content)
                return
            self._send_json({"date": date, "content": content})
            return

        # TODO.md "proper native app": a Settings screen backed by the
        # same ~/.hi/.env hi/config.py already reads — plain model-
        # name/path fields only; MCP credentials stay write-only (see
        # _CONFIG_FIELDS' own comment above).
        if self.path == "/config":
            # str(), not the raw attribute — VAULT_PATH is a real Path
            # object (config.py's own type), not JSON-serializable as-is;
            # every other field here is already a plain string.
            self._send_json({field: str(getattr(config, field)) for field in _CONFIG_FIELDS})
            return

        self.send_error(404, "Not found")


def run_ipc_daemon(port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((HOST, port), _Handler)
    print(f"Voice companion backend listening on http://{HOST}:{port} (loopback only). Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
