# MAKE.md — Architecture plan for `hi`

This plan covers how to restructure `hi` without breaking it. It is based on a read of the codebase as of 2026-11-15: about 16k lines of Python in `hi/`, plus tinyui (Vue), the Swift voice companion, the WhatsApp bridge, and the Docker services.

Work through it top to bottom. Each phase leaves the app working and can ship on its own.

### Decisions (2026-11-15)

| # | Decision | What it changes |
|---|---|---|
| D1 | **tinyui is the one supported front-end.** | The TUI, prompt-toolkit REPL and tmux panes are removed. `hi` (no flags) stays as the launcher that starts the stack and opens tinyui. |
| D2 | **Archive the Swift `voice_companion/`.** | Moved off `main` (tag `archive/voice-companion`, then delete the folder). |
| D3 | **Voice stays silent when the configured TTS engine is down.** | No cross-engine voice fallback (no Kokoro, no browser voice). The reply is still shown as text. |
| D4 | **Remove OpenRouter. Only `local` and `tailscale` remain.** | Delete the OpenRouter provider, settings, defaults and UI, and the `langchain-openrouter` dependency. Provider fallback is local ↔ tailscale only. |
| D5 | **Tracking and synthesis are core.** | They become regular domain packages (`hi/tracking/`, `hi/synthesis/`), not a `features/` bucket. |
| D6 | **Move the backend HTTP server to Starlette** (served by uvicorn). | Replaces the stdlib `BaseHTTPRequestHandler` servers. |

---

## 1. Where things stand

### What already works well (keep it)

- **The filesystem is the source of truth.** Everything durable lives as Markdown or JSONL in the vault. Keep this rule.
- **`hi/llm.py` is the only module that knows which provider is behind a model.** This is the right seam, and other modules should use it the same way.
- **`hi/toolkit.py` selects tools by group and priority.** This cut term from 134 visible tools to 10. It is the right way to scale the tool count.
- **The host bridge and sandbox split** (`hi/host.py`, `hi/host_bridge.py`, `sandbox/`) has a clear security boundary: the sandbox cannot reach the backend, and only the backend has the bridge token.
- **The deterministic fast paths** (`fast_commands.py`, `router.fast_route`) skip model calls for obvious turns.
- **Retries cover model calls only, never tool calls** (`hi/retry.py`). Keep this rule: a tool that failed may have half-done something.

### Problems

| # | Problem | Evidence |
|---|---------|----------|
| P1 | **The `hi/` package is flat.** About 60 top-level modules sit next to 14 subpackages, and core, providers, interfaces, daemons and platform code are all mixed together. | `ls hi/`: `tts_ollama.py` next to `router.py` next to `dashboard.py` |
| P2 | **One concern is split across many modules, and some names collide.** | The model layer is 5 files (`llm`, `chat_model`, `models`, `model_warmup`, `retry`). TTS is 6 files (`tts`, `tts_engine`, `tts_ollama`, `tts_hf`, `tts_kokoro`, `voices`). STT is split across `voice.py` (faster-whisper) and `stt.py` (whisper.cpp). There are two `inbox.py` files (`capture/`, `context/`), two `hotkey.py` files (`capture/` uses pynput, `menubar/` uses Carbon), two `browser.py` files (`hi/` opens URLs, `perception/` reads the current tab), and two reflections (`reflection_agent.py`, `synthesis/reflection.py`). |
| P3 | **There are four write paths for "what happened".** Each one formats and stores its own data. | `vault.log_conversation`, `journal.py`, `transcript.py`, `memory.py`, plus `widget_store.py` and orchestrator run traces |
| P4 | **Config is mutable module globals.** Some modules snapshot values at import, so a settings change doesn't reach them. | `config.set_value` mutates `globals()`. The agent modules do `from hi.config import TERM_MODEL, KEEP_ALIVE` and build their default model at import. The server builds per-turn agents from live config, so this mostly affects the default instances (and was real for the suggestion flags and the Whisper model). |
| P5 | **Imports have side effects.** | Agents build their model when imported (`from hi.agents.term.term import agent, model`). `chat_model.py` reads its cache at import. `personas.get_persona()` starts three background threads (triage, retro, warm-up) as a side effect of building a persona. |
| P6 | **There are three hand-written HTTP servers.** One of them is a 961-line chain of `if self.path == ...` branches. | `ipc/server.py`, `host_bridge.py`, `orchestrator/pending_server.py` (which exists only because the REPL and the IPC server are separate processes) |
| P7 | **Fallbacks are ad hoc and uneven.** | Model calls are retried, but there is no provider or tier fallback. TODO.md says TTS falls back to Kokoro, but `tts.py` says it never falls back and `tts_engine.py` has no chain. There are 40 `except Exception` blocks with mixed behaviour. Nothing records whether a dependency is up or down. `ensure_available()` can start a multi-GB `ollama pull` inside a request and report progress with `print`. |
| P8 | **There is almost no logging.** | 60 `print(` calls. Only 2 modules use `logging`. |
| P9 | **There are no tests.** | No `tests/` directory. The refactors below need a safety net first. |
| P10 | **Docstrings hold project history.** | 115 references to `TODO.md Phase N` or `BLOCKERS.md` inside code. Docstrings such as the one in `models.get_tier_model_fast` explain past debugging instead of current behaviour. |
| P11 | **Personas have drifted from the router.** | `PERSONAS` still lists 4, but `router.collapse()` sends everything to `butler` or `term`, so `docs` and `web` are dead routes kept alive by the classifier prompt. |
| P12 | **There are too many front-ends with no stated status.** | tinyui, TUI, prompt-toolkit REPL, tmux panes, Python menubar and island, Swift `voice_companion/`, WhatsApp. The Python menubar now does what the Swift app was built for. |
| P13 | **The repo root is cluttered.** | `Details.pdf`, `backdate_commits.sh`, `clone_graph_solution.py`, `archive/`, `ui.html`, `ui-vue.html`, `tinyui/hi minimal.html`, a 148 MB `ggml-base.en.bin`, `dev_flows.json`, and both `TODO.md` and `docs/TODO.md`. |
| P14 | **CLAUDE.md is stale.** | It describes an MVP with `memory/conversations` and `memory/knowledge`. The code uses `<VAULT>/hi/{knowledge,conversations,journal,transcripts,...}`. |

---

## 2. Design principles for the next version

1. **Dependencies point one way: interfaces → app → domain → infra.** Nothing in `core/` or `memory/` may import from `server/`, `interfaces/` or `platform/mac`.
2. **One concern per package, with one public entry point.** For example, `hi.voice.tts.speak()`, `hi.llm.chat("sonnet")` and `hi.memory.record_turn()`. Everything else in the package is private.
3. **Importing a module does nothing.** No model clients, threads or file I/O at import. Build things in factories and start threads in an explicit `startup()` per process.
4. **Read config live, from one object.** Use `settings()` and never `from hi.config import X`.
5. **Every external dependency has a declared fallback and a health state.** See §4.
6. **Docstrings describe what the code does now.** Move history and rationale into `docs/adr/`.
7. **Keep it small.** Don't add a framework where a function will do. The new dependencies are Starlette and uvicorn (D6), plus `pytest` for development. `langchain-openrouter` is removed (D4).

---

## 3. Target folder structure

### Repository

```text
hi/                      # the Python package (below)
clients/
  tinyui/                # web UI (moved from ./tinyui) — the supported front-end (D1)
  whatsapp/
                         # voice_companion/ (Swift) archived to tag archive/voice-companion (D2)
services/
  sandbox/               # code-execution container
  tts-gpu/               # was ./tts
docker/
  Dockerfile             # backend image
  docker-compose.yml     # or keep at root for `docker compose up` ergonomics
  google-mcp.sh
docs/
  architecture.md        # the short version of this file, kept current
  adr/                   # decisions + history pulled out of docstrings
  assistants.md
  roadmap.md             # merge TODO.md + docs/TODO.md + BLOCKERS.md
scripts/
tests/
  unit/ integration/ fixtures/vault/
models/                  # gitignored: ggml-*.bin, downloaded weights
README.md  CLAUDE.md  MAKE.md  pyproject.toml  uv.lock
```

Delete or move out of the repo: `Details.pdf`, `backdate_commits.sh`, `clone_graph_solution.py`, `archive/`, `ui.html`, `ui-vue.html`, `tinyui/hi minimal.html`. Move `dev_flows.json` to `~/.hi/` or the vault. Check each one before deleting.

### Python package

```text
hi/
  core/
    settings.py          # Settings dataclass + load/save (~/.hi/.env, host env layering)
    paths.py             # every ~/.hi and <vault>/hi path, in one place
    log.py               # logging setup (file + stderr), replaces print()
    errors.py            # HiError, ProviderUnavailable, ToolDenied, ...
    health.py            # dependency health registry (see §4)
    fallback.py          # first_available()/with_fallback() helpers
    events.py            # turn/tool/approval event dataclasses shared by all sinks
  llm/
    providers.py         # Ollama client construction for local + tailscale hosts (was llm.py; OpenRouter removed, D4)
    registry.py          # role/tier -> model name -> cached client (was models.py)
    reasoning.py         # thinking-support probe (was chat_model.py)
    resilience.py        # retry middleware, warm-up, keepalive, fallback chain
  memory/
    vault.py             # low-level safe read/write/append within the vault (pathlib only)
    notes.py             # knowledge notes: create/append/read/list
    records.py           # ONE record_turn(event) fanning out to the sinks below
    sinks/               # conversation.md, journal.md, transcript.jsonl, widgets
    extraction.py        # was memory.py
    reflection.py        # merge reflection_agent.py + synthesis/reflection.py
    context.py           # vault_context + tree_cache + note_preview
    skills.py
  agents/
    base.py              # build_agent(name, model, tools, prompt) — the one factory
    router.py            # fast_route + classify, returns Route(persona, tier, plan)
    personas/
      term/  (agent.py, prompt.md)
      butler/(agent.py, prompt.md)
    tools/               # tools grouped by domain, each module exports TOOLS + GROUP
      shell.py files.py git.py github.py sandbox.py vault.py people.py
      web.py mac.py music.py timers.py todo.py tracking.py synthesis.py ...
    toolkit.py           # ToolSelector, groups, priorities
    safety.py            # danger.py + action_tiers.py + reviewer.py
  orchestrator/          # keep: planner, graph, subagent, aggregator, budget, blackboard
    approvals.py         # pending_actions + pending_http (no separate server)
  voice/
    stt/      __init__.py (transcribe + chain), whispercpp.py, faster_whisper.py
    tts/      __init__.py (synthesize with the configured engine, else silent), phonon.py, hf.py, voices.py
                         # kokoro removed: no cross-engine voice fallback (D3)
    playback.py          # SpeechQueue, barge-in (was tts.py)
    speaker.py rambler.py wake.py
  perception/            # keep: screen, vision, browser_tab (renamed), diff_watch, privacy
  proactive/
    daemon.py            # was context/daemon.py
    nudges.py            # was proactive.py
    suggest.py           # was suggest/engine.py
    watchdogs/           # keep
    briefing.py notifications.py (was context/inbox.py)
  capture/               # quick capture: store, schema, triage, inbox
  integrations/
    mcp.py mcp_install.py
  platform/
    mac/      control.py music.py hotkey.py (Carbon) open_url.py (was hi/browser.py)
    host_bridge/  client.py (was host.py) server.py (was host_bridge.py)
  server/
    app.py               # Starlette app: routes, CORS middleware, lifespan startup/shutdown (D6)
    routes/              # query.py config.py memory.py voice.py mcp.py agents.py dashboard.py approvals.py
    agui.py              # was agui_adapter.py; streams via StreamingResponse
  tracking/              # core (D5): applications, deadlines, leetcode, pipeline, team_ops
  synthesis/             # core (D5): arbiter, retro, reflection, longcontext, negotiation
  dashboard.py visualise.py agents_ondemand.py   # move under server/routes or tools as they're touched
  interfaces/
    cli.py               # the `hi` launcher: start the Docker stack + host bridge, open tinyui (D1)
    menubar/             # Mac-side helper (hotkey, island) — keep only if it stays a thin tinyui/backend client
```

Removed under D1: `repl.py`, `tui/`, `tmux_util.py`, `streaming.py` (terminal streaming), `cancellation.py`'s terminal key handling, `voice.py` (REPL Ctrl-V dictation), and the `--tui`, `--tmux`, `--code`, `--butler`, `--docs`, `--web` and `--term` flags. `textual` and `prompt-toolkit` leave `pyproject.toml`.

**Layering rule (enforce with a tiny test, §6):**

```text
interfaces, server  ─►  agents, orchestrator, voice, proactive, features
                    ─►  memory, llm, perception, integrations, platform
                    ─►  core
```

### Notes on a few of these moves

- **Personas:** only `term` and `butler` remain as agents. `docs` and `web` already work as tool groups inside term, so their tools move to `agents/tools/vault.py` and `agents/tools/web.py`. The router then classifies between two personas, which also makes its prompt shorter and more accurate.
- **One `build_agent()`:** every persona's `build_agent(model)` repeats the same steps (prompt, tools, host passthrough, retry middleware, tool selector). `agents/base.py` does those once, so a persona becomes data: a prompt file, a list of tool groups, and a default model role.
- **Two different "inbox" concepts:** `capture/inbox.py` holds raw captures and `context/inbox.py` holds notifications. Rename the second to `proactive/notifications.py`.
- **Two hotkey implementations:** keep the Carbon one (it needs no Accessibility permission). Port `--capture-daemon` to it and remove pynput if nothing else uses it.

---

## 4. Fallbacks and resilience

### 4.1 One mechanism

Add `hi/core/health.py` and `hi/core/fallback.py`, about 80 lines together:

```python
# health.py — process-wide, thread-safe
def mark_ok(dep: str) -> None
def mark_down(dep: str, error: Exception, cooldown_s: float = 30) -> None
def is_up(dep: str) -> bool          # False while in cooldown (a simple circuit breaker)
def snapshot() -> dict[str, dict]    # served at GET /health, shown in tinyui status

# fallback.py
def first_available(chain: list[tuple[str, Callable[[], T]]]) -> T:
    """Try each (dep_name, fn) whose dep is up; mark results; raise the last error if all fail."""
```

Each subsystem declares its chain once, in its package's `__init__.py`. Call sites don't need to know about fallbacks.

### 4.2 Fallback table

| Dependency | Primary | Fallback chain | Behaviour when everything fails |
|---|---|---|---|
| **Chat model (provider)** | active `AI_MODE` (`local` or `tailscale`) | The other Ollama host, if configured. The model name is mapped per mode, because the two hosts carry different models. There is no hosted fallback (D4). | A clear error event in the UI ("No model reachable: local down (conn refused), tailscale URL not set"). Never hang. |
| **Tier** | requested tier | opus → sonnet → haiku, on the same provider | Same as above. |
| **Model availability** | model present | Local mode: **don't pull inside a request.** Answer with the next tier and start the pull in the background, reporting progress as an event. Tailscale mode: use the next tier and suggest pulling. | Error event. |
| **Empty or `done_reason=load` reply** | `invoke_with_retry` (exists) | Fold it into `llm/resilience.py` as middleware so every agent gets it, not just the call sites that remember it. | Retried up to `MAX_ATTEMPTS`. |
| **Reasoning probe** | cached answer | If the probe fails with an unrelated error, assume no reasoning and don't cache (this is the current behaviour, keep it) | — |
| **Router classify** | `fast_route` → haiku classify | If classify times out (add a 3 s budget) or the haiku tier is down, use the sticky last route, otherwise `term sonnet` | Never blocks the turn. |
| **Planner / orchestrator** | DAG run | If planning fails, run a single-agent turn on the same prompt | The run trace still gets written. |
| **TTS** | `TTS_BACKEND` (phonon on Ollama, or hf) | **None, by design (D3).** Retry the configured engine once, then stay silent. | The reply is shown as text, with a small "voice offline" status in tinyui. Remove Kokoro and tinyui's browser-voice fallback, and fix the TODO.md/README lines that promise them. |
| **STT** | whisper.cpp server | whisper.cpp → faster-whisper (in-process, lazy-loaded) | "Couldn't transcribe" status, and the audio is kept so you can retry. |
| **Host bridge** (Docker → Mac tools) | bridge reachable | None, since Mac tools can't run anywhere else. The fix is to **hide** Mac-only tool groups from the toolkit while the bridge is down, so the model doesn't call tools that will fail. | The tool returns a short "Mac bridge offline" message. |
| **Sandbox** | sandbox container | None (it's a security boundary). Hide the `run_python` group while it's down. | Same pattern as the host bridge. |
| **MCP servers** | configured servers | If one server fails to start, drop only that server. Today `get_mcp_tools` can take down every MCP tool when one fails. Check this. | Logged and marked down in `/health`. |
| **Vault path** | `VAULT_PATH` | If it is missing or unwritable, use `~/.hi/vault` and show a loud warning in `/health` and the UI | Never write outside the vault root (path-traversal guard in `memory/vault.py`). |
| **Background memory work** (extraction, reflection, triage, retro) | runs after the answer | Already off the hot path. Add a per-job failure counter and back off after repeated failures. | Never affects the turn. |

### 4.3 Error-handling rules (to replace the 40 `except Exception` blocks)

- **At a boundary** (HTTP route, tool wrapper, background job, daemon loop), catch `Exception`, log it with a traceback, and turn it into a user-visible event or tool result.
- **Inside the domain**, catch specific exceptions only (`OSError`, `httpx.HTTPError`, `ValueError`) or let them propagate.
- Use `contextlib.suppress(OSError)` for best-effort cache writes. Never write `except Exception: pass`.
- Tool failures go back to the model as `"error: <short reason>"`, as they do today. Don't retry them.

### 4.4 Timeouts

Give every outbound call an explicit timeout set in `core/settings.py`: model first-token, router classify, TTS, STT, host bridge, sandbox, MCP start. At least two of these have no timeout today (classify, and the pull inside `ensure_available`).

---

## 5. Cross-cutting design

### 5.1 Settings

```python
@dataclass(frozen=True)
class Settings:
    ai_mode: Literal["local", "tailscale"]
    vault_path: Path
    models: dict[str, str]        # role -> model name, already resolved for ai_mode
    keep_alive: int | str
    tts_backend: str
    ...

def settings() -> Settings        # current snapshot (cheap, cached until changed)
def update(key: str, value: str)  # persists to ~/.hi/.env, swaps the snapshot atomically
def on_change(fn)                 # e.g. llm.registry clears its client cache
```

- Keep `env_file.py` and the layering (real env → host credentials → `~/.hi/.env`). It is correct.
- **Fix P4 first:** replace the `from hi.config import X` copies with `config.X`. Correction to the first draft: for the four agent modules (`term`, `butler`, `docs`, `web`) this changes nothing by itself, because they also build their model at import. That is fixed by removing import-time construction in phase 5. The runtime flags (`DIFF_WATCH_ENABLED`, `SMART_SUGGESTIONS_ENABLED`, `WHISPER_MODEL`) were fixed in phase 1.
- Keep the per-mode defaults tables, but move them to `hi/core/defaults.py` (or a TOML file) so `settings.py` holds logic only.

### 5.2 Process model and startup

Write down the processes that exist, and give each one an explicit `main()` that is the only place threads start:

| Process | Entry | Starts |
|---|---|---|
| backend (Docker or native) | `uvicorn hi.server.app:app` | Starlette app. Its lifespan starts model keepalive and the background job runner. |
| host bridge (Mac) | `hi.platform.host_bridge.server:main` | bridge HTTP (also Starlette, sharing the auth middleware) |
| menubar (Mac) | `hi.interfaces.menubar:main` | island, hotkey, supervisor |
| context daemon (Mac) | `hi.proactive.daemon:main` | screen context loop, nudges |

With the REPL and TUI removed (D1), every conversation goes through the backend. The second pending-approval server (`orchestrator/pending_server.py`) goes away, and approvals have one queue, shown in tinyui.

Add a small `hi/core/jobs.py`: a background job runner with named jobs, intervals and failure backoff. Use it to replace the threads started inside `get_persona()`, the weekly-retro "on Sunday when a session starts" trigger, and `model_warmup.start_keepalive`. It is a plain thread loop with no new dependency. CLAUDE.md's "no background jobs" applied to the memory MVP; these jobs already exist, and this only gives them one owner.

### 5.3 HTTP server

Move to **Starlette + uvicorn** (D6):

- `server/app.py` builds `Starlette(routes=[...], middleware=[CORSMiddleware], lifespan=lifespan)`. The `lifespan` function is the only place backend threads and jobs start (§5.2).
- Split the 961-line `ipc/server.py` into `server/routes/*.py`, one module per area, each exporting `routes: list[Route]`. Handlers stay plain functions that call domain code. No business logic lives in routes.
- Keep every existing path and payload shape so tinyui and WhatsApp don't need changes. `test_server_routes.py` (using Starlette's `TestClient`) checks this before the old server is deleted.
- Streaming (`/query`, AG-UI events): `StreamingResponse` over the existing generator. Agent runs are synchronous, so run them with `iterate_in_threadpool`, or a worker thread feeding an `asyncio.Queue`, and keep cancellation on client disconnect.
- Replace `hi/cors.py` with `CORSMiddleware(allow_origins=HI_CORS_ORIGINS)`.
- The host bridge moves to the same stack with a bearer-token middleware. `orchestrator/pending_server.py` is deleted.
- Add `GET /health` (from `core.health.snapshot()`) and `GET /version`.

### 5.4 One event model, many sinks (fixes P3)

```python
@dataclass
class TurnRecord:
    id: str; ts: datetime; persona: str; tier: str; route_s: float
    user: str; answer: str; tools: list[ToolCall]; error: str | None; notes_touched: list[Path]
```

`memory.records.record_turn(rec)` writes to every sink: the conversation Markdown, the journal, the transcript JSONL, widgets, and the memory-extraction queue. Each sink is a small function `def write(rec: TurnRecord) -> None`. The AG-UI adapter and the terminal streamer emit `TurnRecord`s; they don't each call four loggers.

### 5.5 Logging

- `hi/core/log.py` sets up logging to `~/.hi/logs/hi.log` (rotating) plus stderr at WARNING. uvicorn's access log goes to the same file.
- Replace the `print(` calls in library code with `log.info` or `log.warning`. Keep `print` only in `interfaces/`.
- Give each turn a `turn_id` that is attached to log records and used as the `TurnRecord.id`, so a transcript line and its logs can be matched up.

### 5.6 Tools

- Each tool module exports `TOOLS: list[BaseTool]` and `GROUP`, and `toolkit.py` collects them. The current 60-line import block at the top of `term.py` goes away.
- Mark Mac-only tools with `@mac_only` (instead of the hard-coded list in `host.py`) and sandbox tools with `@needs("sandbox")`. The toolkit hides a group when its dependency is down (§4.2).
- `safety.py` combines `danger.py`, `action_tiers.py` and `orchestrator/reviewer.py` into one `gate(tool, args) -> Allow | Confirm | Deny`, used by both interactive turns and orchestrated subagents.

### 5.7 Docs and docstrings

- One PR moves the history-style docstrings (the 115 `TODO.md Phase` / `BLOCKERS.md` references) into `docs/adr/NNNN-title.md` and leaves a one- or two-line docstring describing current behaviour.
- Merge `TODO.md`, `docs/TODO.md` and `BLOCKERS.md` into `docs/roadmap.md`.
- Rewrite `CLAUDE.md` to describe the real layout, the layering rule and the "no import side effects" rule. It currently tells agents to build a `memory/` folder that doesn't exist (P14).

---

## 6. Testing

Start small. The goal is a safety net for the moves, not coverage numbers.

- `pyproject.toml`: add `[dependency-groups] dev = ["pytest", "pytest-timeout"]`.
- `tests/conftest.py`: a `tmp_vault` fixture (it sets `VAULT_PATH` to a tmp dir and refreshes settings) and a `FakeChatModel` that returns canned replies. No network in unit tests.
- **First tests**, the ones that protect the refactor:
  1. `test_imports.py`: every module imports with no network access, no threads started (`threading.active_count()` unchanged) and no files written.
  2. `test_layering.py`: walks the AST and fails if `core/` imports upward, or if `memory/` imports `server` or `interfaces`.
  3. `test_settings.py`: env layering, per-mode model keys, and `update()` reaching consumers (catches P4).
  4. `test_router.py`: `fast_route` rules, the sticky window, and fallback to `term sonnet` when classify raises.
  5. `test_vault.py`: create, append, read and list notes, and reject `../` paths.
  6. `test_fallback.py`: chain order, cooldown, and the error message when all fail.
  7. `test_server_routes.py`: every route in the table answers (with fakes injected).
- `tests/integration/`, marked `@pytest.mark.live`: one real turn against local Ollama. Skipped by default.

---

## 7. Migration plan

Each step is one PR, and the app keeps working after each one. Moves keep a **re-export shim** at the old path (`hi/tts.py` → `from hi.voice.playback import *`) for one release, so imports, tinyui and the Swift app don't break midway.

| Phase | Work | Risk |
|---|---|---|
| **0. Hygiene** | Remove root clutter (P13). Move `ggml-base.en.bin` to `models/`. Merge the TODO files. Remove `__pycache__` from the tree. Update `.gitignore`. Tag and remove `voice_companion/` (D2). | none |
| **0b. Remove unsupported paths** | Remove OpenRouter (D4): `llm.py` branches, `_OPENROUTER_DEFAULTS`, the `openrouter` mode and keys in `config.py`, the `docker-compose.yml` env, the tinyui `Settings.vue`/`App.vue` option, `tui/settings.py`, `context/daemon.py`, `cli.py`, the README, and `langchain-openrouter`. A saved `AI_MODE=openrouter` falls back to `local`, with a warning. Remove the TUI, REPL and tmux front-ends (D1). | low |
| **1. Safety net** | pytest setup and the first 7 tests in §6. Fix the nine snapshot imports (P4). | low |
| **2. Core** | `core/settings.py` (wrapping today's `config.py`; `config.py` becomes a shim), `core/paths.py`, `core/log.py`, `core/errors.py`. Replace `print` in library code. | low |
| **3. LLM + fallbacks** | `llm/` package from the 5 model modules. `core/health.py` and `core/fallback.py`. Local ↔ tailscale and tier chains, router timeout, no pulls inside a request. `GET /health`. | medium |
| **4. Memory** | `memory/` package, `TurnRecord` and `record_turn()`, merge the two reflections, path guard. | medium |
| **5. Agents** | `agents/base.py`, tools split by domain, personas reduced to `term` and `butler`, `safety.py`, dependency-aware tool hiding. | medium |
| **6. Server** | Starlette + uvicorn (D6): `server/app.py`, `server/routes/*`, approvals folded into the one server, `pending_server.py` deleted. Route tests pass before `ipc/server.py` is removed. Dockerfile CMD becomes `uvicorn`. | medium |
| **7. Voice** | `voice/stt` chain, `voice/tts` with no voice fallback (D3), Kokoro and tinyui's browser voice removed, one hotkey implementation. | low |
| **8. Proactive + jobs** | `core/jobs.py`. Move the daemons, suggest, watchdogs and notifications into `proactive/`. Remove the threads started inside `get_persona()`. | low |
| **9. Repo layout** | Move to `clients/`, `services/`, `docker/`. Promote `tracking/` and `synthesis/` as core packages (D5). Update compose paths and the README. Remove the shims. | low (mostly paths) |
| **10. Docs** | Move docstring history to ADRs. Write `docs/architecture.md`. Rewrite `CLAUDE.md`. | none |

Phases 1–3 deliver most of the value: the config bug is fixed, failures are visible and degrade cleanly, and later moves have tests behind them.

---

## 8. Progress

Branch `restructure/make-plan`. Done:

- Phase 0: root clutter removed; Swift app archived under tag `archive/voice-companion`; `Details.pdf` moved to `docs/`. Not done: merging the TODO files, and `ggml-base.en.bin` is still in the repo root (gitignored; `hi/stt.py` expects `~/.hi/models/`).
- Phase 0b: OpenRouter removed (D4); REPL, TUI, tmux and persona flags removed (D1).
- Phase 1: pytest and unit tests for vault, router, config, CLI, fallbacks, probes and routing fallback. The layering and full-import tests are not written yet.
- Phase 3 (part): `hi/core/health.py`, `hi/core/fallback.py`, `GET /health`, and a routing fallback with an 8 s budget (`classify_or_default`).

Not started: the package moves (core/llm/memory/agents/voice/proactive), `TurnRecord`, Starlette, voice chains, `core/jobs.py`, repo layout, ADRs and the CLAUDE.md rewrite.

## 9. Open questions

D1–D6 are decided; see the table at the top. Still open:

- **Q1. Menubar and island (`hi/menubar/`):** keep the Python Mac helper (hotkey, island, its own `/query` call) as a thin client of the backend, or remove it so tinyui is the only way in?
