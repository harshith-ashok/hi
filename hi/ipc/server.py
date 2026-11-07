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
import os
import re
from urllib.parse import parse_qs
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ag_ui.core import events as ag
from ag_ui.encoder import EventEncoder

import hi.config as config
from hi import llm
from hi.agents.term.background_tasks import get_process, list_processes, stop_process
from hi.agents_ondemand import answer_questions, create_run, get_run, list_presets, list_runs
from hi.agui_adapter import stream_agent_as_agui, stream_orchestrated_as_agui_sync
from hi.briefing import build_briefing
from hi.capture.inbox import write_inbox_item
from hi.cors import send_cors_headers, send_cors_preflight
from hi.dashboard import (
    get_last_project,
    get_today_stats,
    get_vault_stats,
    get_vitals,
    record_query_latency,
)
from hi.env_file import ENV_PATH, write_env_var
from hi.ipc.spoken_summary import make_spoken_summary
from hi.mcp_install import _CATALOG as MCP_CATALOG
from hi.mcp_install import _bust_mcp_tools_cache
from hi.mcp_tools import get_mcp_tools_by_server
from hi.models import get_tier_model
from hi.orchestrator.complexity import classify_with_plan
from hi.router import fast_route, remember_route
from hi.speaker import Speaker
from hi import journal, memory, reflection_agent
from hi.orchestrator.graph import latest_run_trace
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
    "AI_MODE", "OLLAMA_HOST", "TAILSCALE_OLLAMA_URL", "TTS_MODEL", "TTS_VOICE",
)
# Accepted on POST /config but never echoed back by GET (reported only as
# `<NAME>_SET: bool`) — same rule as the MCP credentials.
_WRITE_ONLY_FIELDS = ("OPENROUTER_API_KEY",)

# Tier used when the client forces a specific persona (the panel's tab
# row) instead of letting classify_with_plan() pick one — "typical,
# moderately complex requests, the default for most things"
# (hi/router.py's own TIER_DESCRIPTIONS), a reasonable default absent
# any other signal to pick from, same as classify_with_plan() itself
# falls back to on a parse miss. Forcing a persona also always means
# no orchestrated plan — asking for a specific persona is explicitly
# asking NOT to have the request decomposed across several.
_FORCED_PERSONA_TIER = "sonnet"

HOST = os.environ.get("HI_HOST", "127.0.0.1")  # 0.0.0.0 inside the container; the compose file publishes it loopback-only
DEFAULT_PORT = 8765

# Cached per (persona, tier, model_name), same as hi/repl.py's
# run_router_repl() — so cross-turn memory (term's own statefulness) and
# warm/keep_alive model state survive across voice queries in this
# process too. model_name is part of the key, not just (persona, tier),
# specifically so a `POST /config` change to e.g. SONNET_MODEL (Settings
# screen) builds a fresh agent on the very next call instead of quietly
# returning one already built against the tier's *old* model — found
# live while wiring up config hot-reload (hi/models.py's tier_models()
# already re-resolves per call; this cache would have silently
# undermined that one level up if left keyed on tier alone).
_agent_cache: dict[tuple[str, str, str, str], object] = {}
_cache_lock = threading.Lock()


def _get_agent(persona_name: str, tier: str):
    model = get_tier_model(tier)
    key = (persona_name, tier, llm.model_name(model), llm.signature())
    with _cache_lock:
        if key not in _agent_cache:
            _agent_cache[key] = get_agent_builder(persona_name)(model)
        return _agent_cache[key]


def stream_query_as_agui(text: str, forced_persona: str | None = None):
    """Wraps `_stream_query_as_agui` so a failure while setting up the turn
    (no OpenRouter key, unreachable Ollama, missing model) reaches the client
    as a RUN_ERROR event instead of a silently dropped connection."""
    try:
        yield from _stream_query_as_agui(text, forced_persona)
    except Exception as e:
        journal.record_event("error", f"{text[:120]} — {llm.friendly_error(e)}")
        yield ag.RunErrorEvent(message=llm.friendly_error(e))


def _stream_query_as_agui(text: str, forced_persona: str | None = None):
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
    started = time.monotonic()
    reflection_agent.maybe_reflect_yesterday()  # background, at most once a day
    if forced_persona in PERSONAS:
        persona_name, tier, needs_plan = forced_persona, _FORCED_PERSONA_TIER, False
    else:
        routed = fast_route(text)
        persona_name, tier, needs_plan = (*routed, False) if routed else classify_with_plan(text)
    remember_route(persona_name, tier)
    route_s = time.monotonic() - started

    yield ag.CustomEvent(name="persona_selected", value={"name": persona_name, "tier": tier, "plan": needs_plan})

    thread_id = uuid.uuid4().hex
    if needs_plan:
        events = stream_orchestrated_as_agui_sync(text, thread_id)
        log_persona = "orchestrator"
    else:
        events = stream_agent_as_agui(_get_agent(persona_name, tier), text, thread_id)
        log_persona = persona_name

    final_answer = ""
    speaker = Speaker()
    first_token_s: float | None = None
    tool_starts: dict[str, tuple[str, float]] = {}
    tool_times: list[dict] = []
    journal_tools: dict[str, dict] = {}  # call id -> {name, args, result}, for the journal
    for event in events:
        now = time.monotonic()
        if first_token_s is None and isinstance(event, ag.TextMessageContentEvent):
            first_token_s = now - started
        if isinstance(event, ag.TextMessageContentEvent) and not event.subagent_run_id:
            speaker.feed(event.delta)
        if isinstance(event, ag.ToolCallStartEvent):
            journal_tools[event.tool_call_id] = {"name": event.tool_call_name, "args": "", "result": ""}
        elif isinstance(event, ag.ToolCallArgsEvent) and event.tool_call_id in journal_tools:
            journal_tools[event.tool_call_id]["args"] += event.delta
        elif isinstance(event, ag.ToolCallResultEvent) and event.tool_call_id in journal_tools:
            journal_tools[event.tool_call_id]["result"] = str(event.content)
        if isinstance(event, ag.ToolCallStartEvent):
            speaker.block_ended_by_tool()
            tool_starts[event.tool_call_id] = (event.tool_call_name, now)
        elif isinstance(event, ag.ToolCallResultEvent) and event.tool_call_id in tool_starts:
            name, began = tool_starts.pop(event.tool_call_id)
            tool_times.append({"name": name, "s": round(now - began, 2)})
        if isinstance(event, ag.RunFinishedEvent) and isinstance(event.result, str):
            final_answer = event.result
        yield event
        for line in speaker.ready():
            yield ag.CustomEvent(name="spoken_chunk", value={"text": line})

    for line in speaker.finish():
        yield ag.CustomEvent(name="spoken_chunk", value={"text": line})

    yield ag.CustomEvent(
        name="timing",
        value={
            "route_s": round(route_s, 2),
            "first_token_s": round(first_token_s, 2) if first_token_s is not None else None,
            "total_s": round(time.monotonic() - started, 2),
            "tools": tool_times,
        },
    )

    if final_answer:
        log_conversation(log_persona, text, final_answer)
        journal.record_turn(log_persona, tier, text, final_answer, list(journal_tools.values()), time.monotonic() - started)
        memory.extract_async(text, final_answer, [t["name"] for t in journal_tools.values()])
        if not speaker.has_spoken:  # nothing sayable streamed (tool-only answer, one-liner): summarize
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

        if self.path == "/capture":
            self._handle_post_capture()
            return

        if self.path == "/tts":
            self._handle_post_tts()
            return

        if self.path == "/stt":
            self._handle_post_stt()
            return

        if self.path == "/ramble":
            self._handle_post_ramble()
            return

        if self.path == "/agents":
            self._handle_post_agents_create()
            return

        if self.path.startswith("/agents/") and self.path.endswith("/answer"):
            self._handle_post_agents_answer()
            return

        if self.path == "/mcp/configure":
            self._handle_post_mcp_configure()
            return

        if self.path == "/mcp/configure/n8n":
            self._handle_post_mcp_configure_n8n()
            return

        if self.path.startswith("/background/") and self.path.endswith("/stop"):
            task_id = self.path.removeprefix("/background/").removesuffix("/stop")
            ok = stop_process(task_id)
            self._send_json({"stopped": ok})
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
        # Real wall-clock time for the dashboard's "last latency" stat
        # (hi/dashboard.py) — timed around the whole streamed response,
        # not just time-to-first-token, since that's what a user
        # actually waits out for a non-streaming-aware glance at the
        # number. Recorded even on a client-disconnect/empty-text ping,
        # since both are still real completed requests.
        start = time.monotonic()
        try:
            for event in stream_query_as_agui(text, forced_persona=forced_persona):
                self.wfile.write(encoder.encode(event).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected mid-stream — nothing to clean up
        finally:
            record_query_latency(time.monotonic() - start)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, relative: str) -> None:
        """A file saved by run_python. Downloads, not pages: agent-written HTML must never
        run on this origin, which can call the rest of this API."""
        from hi.vault import files_dir

        path = files_dir() / relative
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", relative) or not path.is_file():
            self.send_error(404, "No such file")
            return
        data = path.read_bytes()
        pdf = path.suffix.lower() == ".pdf"
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf" if pdf else "application/octet-stream")
        self.send_header("Content-Disposition", f'{"inline" if pdf else "attachment"}; filename="{path.name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_plot(self, name: str) -> None:
        """A chart saved by run_python (hi/agents/term/sandbox.py)."""
        from hi.vault import plots_dir

        path = plots_dir() / name
        kind = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
        if not re.fullmatch(r"[\w-]+\.(png|jpg|webp)", name) or not kind or not path.is_file():
            self.send_error(404, "No such plot")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        # CORS preflight — the browser sends this before POST /query and
        # POST /config (both carry Content-Type: application/json, a
        # non-"simple" request). GETs never trigger a preflight, so this
        # only needs to exist for that reason.
        send_cors_preflight(self)

    def _handle_post_config(self) -> None:
        """Writes Settings-screen changes to ~/.hi/.env — plain model-
        name/path fields only (see _CONFIG_FIELDS).

        **Now actually hot-reloadable for the fields the voice daemon's
        own request path reads** (BLOCKERS.md's "hi.models.TIER_MODELS
        and hi.vault.KNOWLEDGE_DIR/CONVERSATIONS_DIR are both built once
        at import time" caveat, closed this session): VAULT_PATH,
        HAIKU_MODEL/SONNET_MODEL/OPUS_MODEL, and VISION_MODEL all take
        effect on the very next query, no restart. Mechanically: every
        consumer that used to do `from hi.config import X` (snapshotting
        the value once, at that module's own import time) now does
        `import hi.config as config` and reads `config.X` live at call
        time instead — hi/mcp_tools.py already used this pattern for MCP
        credentials; VAULT_PATH-derived directories (hi/vault.py and
        everything built on it — widgets, people, projects, weekdays,
        retros, orchestrator run logs, ...) and the haiku/sonnet/opus
        tier models (hi/models.py's `tier_models()`) were the two
        genuinely widespread cases. `hi/models.py`'s model cache and this
        module's own `_agent_cache` (below) are keyed by the *resolved
        model name*, not just the tier label, specifically so a changed
        SONNET_MODEL doesn't silently keep returning an agent built
        against the old one — a real bug caught while wiring this up,
        not a hypothetical one.

        **Still genuinely restart-required, and worth knowing why**:
        BUTLER_MODEL/DOCS_MODEL/WEB_MODEL/TERM_MODEL. Not an oversight —
        the voice daemon's forced-persona path (`_get_agent`, below)
        always uses `_FORCED_PERSONA_TIER` ("sonnet"), never these
        fields at all; they're only read by `hi/personas.py`'s
        `get_persona()`, which the *terminal* REPL uses for `hi --term`/
        `--butler`/etc. — a separate process per invocation, so "restart
        to pick up a new BUTLER_MODEL" just means "start your next `hi
        --butler` session," the same already-accepted per-process
        restart story `hi/orchestrator/pending_server.py` documents for
        its own two-servers-by-design split.
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

        unknown = [k for k in body if k not in _CONFIG_FIELDS and k not in _WRITE_ONLY_FIELDS]
        if unknown:
            self.send_error(400, f"Unknown field(s): {', '.join(unknown)}")
            return
        if body.get("AI_MODE", config.AI_MODE) not in config.MODES:
            self.send_error(400, f"AI_MODE must be one of: {', '.join(config.MODES)}")
            return

        # AI_MODE goes first: model names are stored per mode, so the rest of
        # the body must land in the mode being switched *to*.
        ordered = sorted(body.items(), key=lambda item: item[0] != "AI_MODE")
        clearable = {"TAILSCALE_OLLAMA_URL", "OPENROUTER_API_KEY"}
        updated = []
        for field, value in ordered:
            value = str(value).strip()
            if not value and field not in clearable:
                continue
            config.set_value(field, value)
            updated.append(field)
        if updated:  # never log secrets' values
            journal.record_event("settings", "changed " + ", ".join(updated))

        # VAULT_PATH/HAIKU_MODEL/SONNET_MODEL/OPUS_MODEL/VISION_MODEL are
        # now live for this process (see this method's own docstring) —
        # only BUTLER_MODEL/DOCS_MODEL/WEB_MODEL/TERM_MODEL still need a
        # fresh `hi --butler`/`--docs`/`--web`/`--term` terminal session,
        # since the voice daemon never reads them at all.
        restart_needed = sorted(set(updated) & {"BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "TERM_MODEL"})
        note = "Written to ~/.hi/.env and applied immediately — no restart needed."
        if restart_needed:
            note = (
                f"Written to ~/.hi/.env. {', '.join(restart_needed)} only affects a "
                "terminal session forcing that persona (`hi --butler` etc.) — start a "
                "new one to pick it up. Everything else here (vault path, "
                "haiku/sonnet/opus, vision) is already live for the voice daemon."
            )
        self._send_json({"updated": updated, "note": note})

    def _handle_post_capture(self) -> None:
        """The dashboard's quick-capture tile: writes straight into the
        SAME untriaged inbox hi/capture/hotkey.py's global macOS hotkey
        already writes to (hi/capture/inbox.py's write_inbox_item()) —
        no LLM call, no new storage mechanism. hi/capture/triage.py
        turns it into a real task/event at the next session, exactly as
        it already does for a hotkey-captured item.
        """
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
        path = write_inbox_item(text)
        self._send_json({"saved": True, "path": str(path)})

    def _handle_post_tts(self) -> None:
        """Synthesizes `text` via Kokoro (hi/tts_kokoro.py) and returns
        real WAV bytes — per explicit request, replaces the voice
        companion's own on-device AVSpeechSynthesizer (a system voice
        the request itself flagged as not sounding human enough) with
        actual local neural TTS. The client already has the text it
        wants spoken (the `spoken_summary` CUSTOM event on /query's own
        stream) — this endpoint's only job is turning that text into
        audio, synchronously; a couple of seconds for a short sentence
        is normal (see hi/tts_kokoro.py) and not worth SSE/streaming
        machinery for.
        """
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
        try:
            from hi.tts_ollama import synthesize_wav

            wav_bytes = synthesize_wav(text, (body.get("voice") or "").strip() or None)
        except Exception as ollama_error:
            try:  # native installs may still have Kokoro (desktop group)
                from hi.tts_kokoro import synthesize_wav as kokoro_wav

                wav_bytes = kokoro_wav(text)
            except Exception:
                self.send_error(500, f"TTS synthesis failed: {ollama_error}")
                return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self.end_headers()
        self.wfile.write(wav_bytes)

    def _handle_post_ramble(self) -> None:
        """POST /ramble {text} -> {text, original}: the rambler (hi/rambler.py)
        structures a spoken transcript before it is sent as a query."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            original = (json.loads(self.rfile.read(length) or b"{}").get("text") or "").strip()
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        if not original:
            self.send_error(400, "Missing 'text'")
            return
        from hi.rambler import structure

        self._send_json({"text": structure(original), "original": original})

    def _handle_post_stt(self) -> None:
        """POST /stt with a 16 kHz mono WAV body -> {"text": ...}, via the
        native whisper.cpp server (hi/stt.py)."""
        length = int(self.headers.get("Content-Length", 0))
        wav = self.rfile.read(length)
        if not wav:
            self.send_error(400, "Missing audio body")
            return
        try:
            from hi.stt import transcribe_wav

            self._send_json({"text": transcribe_wav(wav)})
        except Exception as e:
            self._send_json({"error": str(e)}, status=502)

    def _handle_post_agents_create(self) -> None:
        """POST /agents {prompt, preset?} — starts a new on-demand agent
        (hi/agents_ondemand.py). Returns the run immediately: either
        `status: "clarifying"` with real questions to show the user, or
        `status: "running"` if none were needed (or a preset skipped
        straight past clarification) — execution itself happens in a
        background thread, the client polls GET /agents/{id} for
        progress, same pattern PendingActionsMonitor.swift already uses.
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        preset = body.get("preset") or None
        prompt = (body.get("prompt") or "").strip()
        mcp_server = body.get("mcp_server") or None
        if not preset and not prompt:
            self.send_error(400, "Missing 'prompt' (or a recognized 'preset')")
            return
        run = create_run(prompt, preset=preset, mcp_server=mcp_server)
        self._send_json(run.to_dict())

    def _handle_post_agents_answer(self) -> None:
        """POST /agents/{id}/answer {answers: [str, ...]} — answers to
        the run's current `questions`, in the same order. May surface
        another (bounded) round of questions, or move the run straight
        to `running`."""
        run_id = self.path.removeprefix("/agents/").removesuffix("/answer")
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        answers = body.get("answers")
        if not isinstance(answers, list):
            self.send_error(400, "Expected {'answers': [str, ...]}")
            return
        run = answer_questions(run_id, [str(a) for a in answers])
        if run is None:
            self.send_error(404, "No agent run with that id.")
            return
        self._send_json(run.to_dict())

    def _handle_post_mcp_configure(self) -> None:
        """POST /mcp/configure {name, credential} — the single-credential
        servers (github/obsidian). A direct write, not routed through
        hi/mcp_install.py's confirm_destructive()-gated agent tool: that
        gate exists for an AI-initiated write during a conversation
        (hi/action_tiers.py's whole reason to exist); a human filling in
        a form on the Agents screen and clicking Save *is* the
        confirmation, the same reasoning already applied to `/config`
        (hi/config.py's own fields) — this just extends that same
        direct-write pattern to the two write-only MCP credentials
        `/config` deliberately excludes (see `_CONFIG_FIELDS`'s own
        comment: never echo a secret back via a GET).
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        name = (body.get("name") or "").strip()
        credential = (body.get("credential") or "").strip()
        if name not in MCP_CATALOG:
            self.send_error(400, f"Unknown server '{name}'. Known servers: {', '.join(MCP_CATALOG)}")
            return
        env_var, _desc = MCP_CATALOG[name]
        if env_var is None:
            self.send_error(400, f"'{name}' needs no credential.")
            return
        if isinstance(env_var, tuple):
            self.send_error(400, f"'{name}' needs multiple values — use POST /mcp/configure/n8n instead.")
            return
        if not credential:
            self.send_error(400, "Missing 'credential'.")
            return
        write_env_var(env_var, credential, path=ENV_PATH)
        setattr(config, env_var, credential)
        _bust_mcp_tools_cache()
        self._send_json({"configured": name})

    def _handle_post_mcp_configure_n8n(self) -> None:
        """POST /mcp/configure/n8n {url, token} — n8n's own two-value
        config, mirroring hi/mcp_install.py's configure_n8n_server() tool
        as a direct write (see _handle_post_mcp_configure's own comment
        for why no confirm_destructive() gate is needed here)."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        url = (body.get("url") or "").strip()
        token = (body.get("token") or "").strip()
        if not url or not token:
            self.send_error(400, "Both 'url' and 'token' are required.")
            return
        write_env_var("N8N_MCP_URL", url, path=ENV_PATH)
        write_env_var("N8N_MCP_TOKEN", token, path=ENV_PATH)
        config.N8N_MCP_URL = url
        config.N8N_MCP_TOKEN = token
        _bust_mcp_tools_cache()
        self._send_json({"configured": "n8n"})

    def do_GET(self) -> None:
        # See the matching comment in do_POST — same queue, same caveat.
        if try_handle_pending_get(self):
            return

        if self.path.startswith("/files/"):
            self._send_file(self.path.removeprefix("/files/"))
            return

        if self.path.startswith("/plots/"):
            self._send_plot(self.path.removeprefix("/plots/"))
            return

        if self.path == "/memory":
            from hi.reflection_agent import latest_reflection

            self._send_json({"memory": memory.read_memory(), "reflection": latest_reflection()})
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
        # Models the Ollama server at ?host=… (default: configured host)
        # reports — the Settings screen's host-aware model picker. Always
        # 200 with an `error` string rather than a 5xx, since "host
        # unreachable" is a normal, expected answer while editing the URL.
        path, _, query = self.path.partition("?")
        params = parse_qs(query)

        if path == "/models":
            mode = params.get("mode", [None])[0]
            host = params.get("host", [None])[0]
            try:
                self._send_json({"models": llm.list_models(mode=mode, host=host), "error": ""})
            except (OSError, ValueError) as e:
                where = host or llm.ollama_host(mode) or (mode or config.AI_MODE)
                self._send_json({"models": [], "error": f"can't reach {where}: {e}"})
            return

        # ?mode=… previews another mode's model names (the settings screen
        # edits a mode before activating it); everything else is live state.
        if path == "/tts/voices":
            from hi.tts_ollama import list_voices

            try:
                self._send_json({"voices": list_voices(), "error": ""})
            except RuntimeError as e:
                self._send_json({"voices": [], "error": str(e)})
            return

        if path == "/config":
            mode = params.get("mode", [config.AI_MODE])[0]
            if mode not in config.MODES:
                self.send_error(400, f"Unknown mode '{mode}'")
                return
            payload = {field: str(getattr(config, field)) for field in _CONFIG_FIELDS}
            payload.update({role: config.model_for(role, mode) for role in config.MODEL_ROLES})
            payload.update({f"{name}_SET": bool(getattr(config, name)) for name in _WRITE_ONLY_FIELDS})
            payload["MODES"] = list(config.MODES)
            self._send_json(payload)
            return

        # Everything below backs the web frontend's home dashboard
        # (ui-vue.html's own template) — see hi/dashboard.py's own
        # docstring for what's real vs. deliberately not exposed (no
        # calendar integration, no Focus/DND read — neither has a real
        # data source, so neither gets a fabricated one here).
        if self.path == "/vitals":
            self._send_json(get_vitals(active_model=config.SONNET_MODEL))
            return

        if self.path == "/vault-stats":
            self._send_json(get_vault_stats())
            return

        if self.path == "/today":
            self._send_json(get_today_stats())
            return

        if self.path == "/last-project":
            self._send_json({"name": get_last_project()})
            return

        if self.path == "/trace":
            trace = latest_run_trace()
            if trace is None:
                self.send_error(404, "No orchestrated run has completed yet.")
                return
            self._send_json({"content": trace})
            return

        # On-demand agents (TODO.md Phase 27) — for the Vue frontend's
        # agent-visualization view: a list to render, presets for the
        # one-click buttons, and per-run polling while clarifying/running.
        if self.path == "/agents":
            self._send_json([r.to_dict() for r in list_runs()])
            return

        if self.path == "/agents/presets":
            self._send_json(list_presets())
            return

        # MCP server management (per explicit request: house this in the
        # Agents view) — /mcp/servers is the catalog + credential status
        # (GET /config's own analog, for the write-only MCP fields that
        # endpoint deliberately excludes); /agents/mcp-servers is
        # narrower — only servers actually connected right now, with
        # real tool counts, for the "assign an MCP server to this agent"
        # picker. Checked before the generic /agents/{id} prefix match
        # below so "mcp-servers" is never mistaken for a run id.
        if self.path == "/mcp/servers":
            servers = []
            for name, (env_var, desc) in MCP_CATALOG.items():
                if env_var is None:
                    configured = shutil.which("npx") is not None
                elif isinstance(env_var, tuple):
                    configured = all(getattr(config, v, None) for v in env_var)
                else:
                    configured = bool(getattr(config, env_var, None))
                servers.append({"name": name, "description": desc, "configured": configured})
            self._send_json(servers)
            return

        if self.path == "/agents/mcp-servers":
            by_server = get_mcp_tools_by_server()
            self._send_json({name: len(tools) for name, tools in by_server.items()})
            return

        if self.path.startswith("/agents/"):
            run = get_run(self.path.removeprefix("/agents/"))
            if run is None:
                self.send_error(404, "No agent run with that id.")
                return
            self._send_json(run.to_dict())
            return

        # Background tasks (hi/agents/term/background_tasks.py) — per
        # explicit request to phase out the old tmux-pane redirect for a
        # long-running command entirely ("spawn terminal instances as
        # separate task... instead of relying on the left pane"): a
        # dev server/watcher started via run_shell_command shows up here
        # instead of in a physical pane, live-tailed and stoppable from
        # the Agents view the same way an on-demand agent run is.
        if self.path == "/background":
            self._send_json([p.to_dict() for p in list_processes()])
            return

        if self.path.startswith("/background/"):
            bp = get_process(self.path.removeprefix("/background/"))
            if bp is None:
                self.send_error(404, "No background task with that id.")
                return
            self._send_json(bp.to_dict())
            return

        self.send_error(404, "Not found")


def run_ipc_daemon(port: int = DEFAULT_PORT) -> None:
    # No terminal to input() on here — every destructive-action confirm
    # goes through the pending queue, answered via POST /pending/{id}/….
    from hi.action_tiers import set_confirm_handler
    from hi.orchestrator.pending_actions import wait_for_approval

    set_confirm_handler(wait_for_approval)
    server = ThreadingHTTPServer((HOST, port), _Handler)
    print(f"Voice companion backend listening on http://{HOST}:{port} (loopback only). Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
