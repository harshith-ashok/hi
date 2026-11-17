# GAMEPLAN.md: `hi` does the work before you ask

An implementation plan for Claude. Read `CLAUDE.md`, `docs/architecture.md` and `MAKE.md` first; every rule
there still applies. This file says **what** to build, **where** it goes, and **how you know it is done**.

## The goal in one paragraph

`hi` already knows what is on the screen (`hi/context/`) and what is in the vault (`hi/memory/`). Today it
only uses that when you ask it something. This plan makes it act on its own, safely: it runs tasks on a
schedule, checks in every half hour to see whether something is worth preparing, files what you drop into
the vault, searches the web through a private SearXNG, and hands you **finished work plus a one-click
approval** instead of questions. Success is measured in work you no longer do, not in messages sent.

### A day with `hi` when this is done

- 08:00 A scheduled brief lands in the island: "3 things today. PR #41 has failing CI, the Acme follow-up is
  due, the standup notes are drafted." The full report is a note in the vault.
- 10:40 You have been on the same stack trace in iTerm for 20 minutes. The heartbeat has already searched the
  error (SearXNG), read the relevant files, and written a report with a proposed patch. The island says:
  "Found a likely fix for the `KeyError: 'tier'` you are looking at. Review?"
- 13:15 You save a voice memo from your phone into `vault/hi/drop/`. Two minutes later it is transcribed,
  filed as a note, and its two action items are in your task list.
- 17:00 The heartbeat drafted the follow-up email. It is a **proposal**: nothing was sent. You approve it from
  the island with one click.

## Scope

In scope, in build order:

| Phase | What | Source item |
|---|---|---|
| 0 | Foundations: headless turns, run policy, delivery, redaction, job health | (needed by all) |
| 1 | Web search through SearXNG | 2.9 |
| 2 | Output fitted to the surface (island, notification, tinyui, vault, voice) | 1.4 |
| 3 | Fast, concise defaults per surface | 2.10 |
| 4 | Approvals without tinyui open; proposals from unattended runs | 1.3 |
| 5 | Scheduled tasks you create by talking | 2.5 |
| 6 | Heartbeat: screen- and vault-aware check-ins that prepare work | 2.6 |
| 7 | Inbound media: the drop folder, screenshots, attachments | 2.7 |
| 8 | Hardening: always on, health per component, dedupe, limits, redaction | hardening |

Out of scope: messaging apps (Telegram, Discord, WhatsApp, iMessage), embeddings or a vector store, a
database, voice fallback across TTS engines. Don't add them.

## Architecture

### Where things run (as of today)

`hi` runs in two places, and this plan keeps that split:

- **The Docker backend** (`hi/server/`, port 8765). It has the vault mounted at `/vault`, the models, the agents
  and the background jobs (`hi/startup.py`). Its `~/.hi` is the `hi-home` Docker volume, **not** the Mac's
  `~/.hi`.
- **The Mac.** The menu bar app (`hi/menubar/`) supervises the context daemon (which writes
  `~/.hi/context/now.json` and `history.jsonl`, and runs the 5-minute `proactive.nudge`) and the host bridge
  (port 8766, `hi/host_bridge.py`). The island shows messages posted to `~/.hi/context/inbox.jsonl`.

The backend reaches the Mac **only through the host bridge** (`hi/host.py`, `HOST_TOOLS`). The Mac reaches
the backend over `http://127.0.0.1:8765`.

### Target picture

```text
┌──────────────────────────────────── Mac (native) ─────────────────────────────────────┐
│ menu bar app  (LaunchAgent, KeepAlive)                              [Phase 8]         │
│   island ── toasts, replies, Approve/Deny buttons, "open full report" link [2, 4]     │
│   context daemon ── now.json, history.jsonl; proactive.nudge every 5 min (unchanged) │
│   host bridge :8766 ── current_context, recent_activity [6], post_to_inbox [0]       │
│ inbox gate  hi/context/inbox.py ── dedupe · interruption budget · quiet_for  [0, 8]  │
└──────────────▲─────────────────────────────────────────────┬──────────────────────────┘
               │ bridge (bearer token)                       │ POST /pending/{id}/..., /proposals/{id}/...
┌──────────────┴──────────────── Docker backend :8765 ───────▼──────────────────────────┐
│ lifespan → hi/startup.py start_background_jobs()                                      │
│                                                                                       │
│   scheduler tick, 30 s ─────┐                                                         │
│   heartbeat, 30 min ────────┼──► hi/automation  ──run_turn()──► hi/server/headless.py │
│   drop-folder poll, 60 s ───┘    (decides what to run;           (same turn pipeline, │
│                                   never imports hi.server:        origin + policy)    │
│                                   the runner is injected)               │             │
│                                        │                                ▼             │
│                       context pack: vault + screen (gated)       agents + tools       │
│                                                                  UnattendedGuard ──►  │
│                                                                  proposals.jsonl      │
│   delivery: report → vault · headline → bridge post_to_inbox · tinyui Inbox view      │
└───────────────────────────────────────────────────────────────────────────────────────┘
    searxng (compose service, not published)      /vault (Obsidian, iCloud)      Ollama
```

### Layers

`hi/automation/` is a new package that sits next to `agents` and `orchestrator`:

```text
server / cli  →  automation, agents, orchestrator  →  memory, llm  →  core
```

- `hi/automation` may import `core`, `config`, `llm`, `memory`, and `hi/host.py` (the bridge client). It
  **never imports `hi.server`** (enforced by `tests/unit/test_layering.py`, which already forbids it).
  The backend passes it a `run_turn` callable at startup (dependency injection), so automation can start
  agent turns without importing the server.
- New stores that live in the vault go in `hi/memory/` (`schedules.py`, `proposals.py`, `reports.py`).
- Pure helpers with no `hi` imports go in `hi/core/` (`redact.py`).
- Add `"automation": {"core", "config", "llm", "memory", "host"}` to `ALLOWED` in `test_layering.py`.
  If `hi/host.py` imports something higher, move the plain bridge client into its own module first.

### Files on disk

Everything `hi` remembers is in the vault. Runtime counters go in `~/.hi/state/` (they are not memory).

| Path | Written by | Format |
|---|---|---|
| `<vault>/hi/schedules/<id>.md` | scheduler, the user in Obsidian | YAML frontmatter (`hi/memory/frontmatter.py`) + the task prompt as the body |
| `<vault>/hi/schedules/runs.jsonl` | scheduler | `{schedule_id, slot, status: claimed\|done\|failed\|missed, started, finished, report, error}` |
| `<vault>/hi/proposals.jsonl` | UnattendedGuard, approval routes | append-only events: `created, approved, denied, executing, executed, failed, expired` |
| `<vault>/hi/reports/YYYY-MM-DD/HHMM-<slug>.md` | delivery | frontmatter `{id, origin, headline, priority, links, proposals}` + Markdown body |
| `<vault>/hi/heartbeat/YYYY-MM-DD.jsonl` | heartbeat | `{ts, fingerprint, skipped_reason?, decisions, delivered}` |
| `<vault>/hi/drop/` | you (Finder, phone via iCloud) | any file |
| `<vault>/hi/drop/processed/`, `drop/index.jsonl` | drop processor | moved originals; `{sha256, name, note, ts}` |
| `~/.hi/state/usage.jsonl` (backend) | limits | `{ts, origin, model, hosted: bool, tool_calls, seconds}` |
| `~/.hi/context/inbox.jsonl` (Mac) | inbox gate | existing, gains `kind, priority, dedupe_key, payload` |

Write files atomically (temp file + `os.replace`), except append-only JSONL. Exclude `hi/reports/`,
`hi/drop/`, `hi/heartbeat/` and `hi/schedules/` from note matching (add them to `SKIP_PREFIXES` in
`hi/memory/context.py`), so automation output does not crowd out your own notes.

## Rules that apply to every phase

1. **Screen-derived data only goes to local models.** This covers screen text, OCR, window titles, activity
   summaries and screenshots. Today this check is `local_model_ok()` in `hi/context/daemon.py`. Move it to
   `hi/llm/registry.py` as `is_local(tier) -> bool` and use it everywhere. If no local model is configured,
   background runs leave the screen out and say so in the run log. They do not silently send it to a cloud
   model.
2. **Unattended runs never take an irreversible action.** Scheduled, heartbeat and drop-folder runs use the
   `unattended` policy (Phase 0). Anything outside the policy becomes a **proposal**.
3. **Never retry tool calls** (CLAUDE.md). Retrying a background *run* is also off: a failed run is recorded
   and reported, and the next slot runs normally.
4. **Read settings live** (`import hi.config as config`). Every new setting goes in `hi/config.py` with a
   default, and in the Settings view if a user would change it.
5. **Make every failure visible**: `hi/core/health.py`, `GET /health`, a line in the run log, and a delivery
   when the user would otherwise wait for something that never comes.
6. **Tests**: unit tests next to each change, no network, no real vault (`tmp_vault`). Fake the bridge, the
   model (a stub `BaseChatModel` or a callable), SearXNG (`httpx.MockTransport` or monkeypatch) and the clock
   (pass `now` into functions; don't call `time.time()` deep inside decision logic).
7. One commit per phase, after `uv run pytest` passes. Update `docs/architecture.md` (packages, background
   jobs, failure table) and tick `TODO.md` items as you go. Record the design in
   `docs/adr/0002-automation.md` in Phase 0.

---

## Phase 0: Foundations

Everything later depends on these five pieces. Build them first, each with tests.

### 0.1 Origin and headless turns

- Add `origin: str` to the turn pipeline: `"ui" | "island" | "voice" | "schedule" | "heartbeat" | "drop"`.
  `stream_query_as_agui` gains `origin="ui"` and `policy: RunPolicy | None`. `POST /query` accepts an
  optional `origin` in its body (the island sends `"island"`).
- Add `origin` to `TurnRecord` (`hi/memory/records.py`). The journal line shows it, e.g. `[schedule: morning brief]`.
- New `hi/server/headless.py`:

  ```python
  @dataclass
  class RunResult:
      answer: str
      tools: list[dict]          # name, args, result (as the journal stores them)
      proposals: list[str]       # proposal ids created during the run
      error: str
      timing: dict
  def run_turn(text: str, *, origin: str, policy: RunPolicy, persona: str | None = None,
               tier: str | None = None, context: str = "") -> RunResult
  ```

  It consumes the events from `_stream_query_as_agui` without a client. It never creates a `Speaker` or
  makes a spoken summary, and it starts each run with a fresh history (`fresh=True`) so background runs
  never leak into your chat thread.
- `_agent_cache` in `turn.py` is keyed by `(persona, tier, model, signature)`. Add the policy name to the
  key, so an agent built for unattended use is never reused for an interactive turn, or the reverse.

### 0.2 Run policy and the UnattendedGuard

- `hi/toolkit.py`: add `READ_ONLY: frozenset[str]`, an explicit allowlist (vault and project reads,
  `search_vault`, `read_note`, `list_notes`, `current_context`, `use_skill`, `fetch`, `web_search`,
  `search_wikipedia`, GitHub reads, `list_*`/`get_*` style reads). For MCP tools, also treat a tool whose
  annotations set `readOnlyHint: true` as read-only. **A tool not on the list is not read-only.**
- `RunPolicy` (frozen dataclass in `hi/toolkit.py`): `name`, `allowed: frozenset[str]` (tools beyond
  read-only), `max_tool_calls`, `timeout_s`, `allow_web: bool`, `allow_screen: bool`. Two presets:
  `INTERACTIVE` (no guard, today's behaviour) and `UNATTENDED` (read-only plus `write_report`).
- `UnattendedGuard(AgentMiddleware)`: in `wrap_tool_call`, a call to a tool outside the policy is **not
  executed**. Instead it appends a proposal (Phase 4 store; a stub that writes `created` is enough in
  Phase 0) and returns a `ToolMessage`: `"Not run: queued for the user's approval as proposal P-1a2b. Carry
  on without it and mention it in your answer."` It also enforces `max_tool_calls`.
- `confirm_destructive` must deny inside an unattended run. Set a `contextvars.ContextVar` in the guard and
  check it in `action_tiers.confirm_destructive`. Write a test proving the variable reaches a sync tool run
  by the agent. If it does not propagate, give the guard a per-agent flag instead. Never fall through to
  `wait_for_approval`.
- `write_report(title, body)` tool: writes under `<vault>/hi/reports/` only (Phase 2 store).

### 0.3 Delivery (the shape; Phase 2 fills it in)

- `hi/automation/deliver.py`:

  ```python
  @dataclass(frozen=True)
  class Delivery:
      headline: str              # ≤ 25 words, plain text, no Markdown/paths/URLs
      body: str = ""             # Markdown; becomes the report
      kind: str = "info"         # info | digest | approval | reminder | failure
      priority: str = "normal"   # low | normal | urgent
      dedupe_key: str = ""       # same key, same day → shown once
      origin: str = ""
      proposals: tuple[str, ...] = ()
  def deliver(d: Delivery) -> str   # returns the report id ("" if no body)
  ```

- New host-bridge tool `post_to_inbox(message, kind, priority, dedupe_key, payload_json)` (add it to
  `HOST_TOOLS`). On the Mac it calls `inbox.deliver` (extended below). Its result says whether the island
  showed it, the budget dropped it, or the island is not running. If the island is not running, the Mac side
  shows a plain macOS notification, as `inbox.py` already documents.
- `hi/context/inbox.py` becomes **the single delivery gate**: it checks `dedupe_key` against today's entries,
  the interruption budget (move `_budget_left`/`_record_notification` from `hi/suggest/engine.py` here, with
  one budget shared by nudges, heartbeat and schedules), and `quiet_for()`. `urgent`, `approval` and
  `reminder` skip the budget and `quiet_for`. They never skip dedupe.

### 0.4 Redaction

- `hi/core/redact.py`: `redact(text: str, known: Iterable[str] = ()) -> str` and
  `contains_secret(text, known=()) -> bool`. It covers private key blocks, `sk-…`, `ghp_…`/`github_pat_…`,
  `xox[abp]-…`, `AKIA…`, JWTs, `Bearer …`, `KEY=value` lines whose key ends in `TOKEN|KEY|SECRET|PASSWORD`,
  and the exact values in `known`.
- `hi/config.py`: `secret_values() -> list[str]` returns the values of every setting whose name ends in
  `_TOKEN`, `_KEY`, `_SECRET` or `PASSWORD` (non-empty, at least 8 chars), read live.
- Phase 8 lists where it is applied. In Phase 0, apply it in `deliver()` (headline and body) and to every
  report.

### 0.5 Job health

- `hi/core/jobs.every` records `health.mark_ok(f"job:{name}")` after a success and `mark_down` with the error
  after a failure, plus a `last_run` timestamp. `GET /health` shows the jobs. `hi/core` still imports nothing
  else from `hi`.

**Done when:** `run_turn("list my notes", origin="schedule", policy=UNATTENDED)` returns an answer in a test
with a stub model. A stub model that calls `write_project_file` produces a proposal, and the file is
untouched. `deliver()` with a fake bridge posts once per `dedupe_key`. `/health` lists `job:*` entries. The
ADR is written.

---

## Phase 1: Web search through SearXNG (2.9)

### Service

- `docker-compose.yml`: add `searxng` with a **pinned dated image tag** of `searxng/searxng`. Look up a
  current tag when you implement this; never use `latest`. Settings:
  - `restart: unless-stopped`, mount `./searxng/settings.yml:/etc/searxng/settings.yml:ro`,
    `SEARXNG_SECRET` from `~/.hi/.env`. `hi` generates the secret on first start, the same way
    `host_bridge.ensure_token` does.
  - Not published to the host by default. The backend reaches it at `http://searxng:8080`. For native mode
    (`hi --voice-daemon`), document `docker compose up -d searxng` plus an optional loopback publish
    `127.0.0.1:8888:8080`.
- `searxng/settings.yml`: `use_default_settings: true`, `search.formats: [html, json]` (JSON is off by
  default and the tool needs it), `server.limiter: false` (private instance, no Redis), `server.secret_key`
  from the environment. Keep the default engines; make sure `wikipedia`, `github` and `stackoverflow` are on.
- `config.SEARXNG_URL` (default `http://searxng:8080` in compose, `http://127.0.0.1:8888` natively).

### Tool

- `hi/agents/web/search.py`: `web_search(query: str, limit: int = 5, time_range: str = "", category: str = "general") -> str`
  - `GET {SEARXNG_URL}/search?q=…&format=json&categories=…&time_range=…`, with an 8 s timeout.
  - Returns numbered results: `[1] Title, url, snippet (engine)`. On zero results it says so plainly.
  - Caches results in-process for 10 minutes by `(query, params)`.
  - **Refuses** (returns an error string, makes no request) if `contains_secret(query, config.secret_values())`.
  - In an unattended run it works only if `policy.allow_web`. Every query is written to the journal.
- Health: `required_dependency("web_search") == "searxng"`. A failure marks it down for the cooldown, and
  `ToolSelector` hides the tool while it is down (the existing mechanism).
- `hi/toolkit.py`: new group `Group("search", 1, ("web_search",))`. Offer it to `term`, `web` and `butler`.
- Prompt rules (term and web prompts, plus the shared persona): use `web_search` for anything current or
  outside the vault, read the top 1–2 results with `fetch` before answering, and cite sources as `[n]` with
  the URLs at the end. Never search for screen text or vault content verbatim; search for the public part
  (an error message, a library name).

**Tests:** parsing the JSON response, empty results, timeout → health marked down and tool hidden, a query
containing a secret is refused and no request is made, cache hit.

**Done when:** "what changed in Python 3.14's free-threading?" returns an answer with `[1]` citations, and
stopping the `searxng` container makes `/health` show it down and removes the tool from the next turn.

---

## Phase 2: Output fitted to the surface (1.4)

The rule from TODO §1 is "say short, show the rest". Here it applies to every surface.

| Surface | Gets | Length |
|---|---|---|
| Island / macOS notification | `headline` + an "Open" link to the report in tinyui; Approve/Deny for `kind=approval` | ≤ 25 words |
| Voice | `headline` only, and only when `priority == "urgent"` or the turn was spoken | ≤ 2 sentences |
| tinyui | the full Markdown body; the Inbox view lists reports and proposals | full |
| Vault | report note `<vault>/hi/reports/...` with `[[links]]` to notes used | full |

Build:

- `hi/memory/reports.py`: `write_report(origin, headline, body, links, proposals) -> (id, path)`,
  `list_reports(day=None)`, `read_report(id)`.
- `hi/automation/deliver.py`: `deliver()` writes the report if there is a body, then posts the headline
  through the bridge. If the bridge is down, the report still exists: mark `host_bridge` down and keep going.
- Headline from a long answer: if the answer is ≤ 160 chars and has no Markdown, use it as is. Otherwise call
  `hi/server/spoken_summary.make_spoken_summary`. Move the summarizer into `hi/llm/` or `hi/memory/` if
  automation needs it without importing `server`. A digest (several items) uses the headline
  `"N things ready: <first item>"`.
- Charts and files produced by `run_python` in a background run are saved next to the report and linked.
- Routes `GET /reports`, `GET /reports/{id}`. tinyui gets an **Inbox** view with three tabs: Reports,
  Proposals (Phase 4) and Schedules (Phase 5). The island's "Open" link goes to `#/inbox/<id>`.
- Island (`hi/menubar/island.py`): render `kind`. A digest shows the headline and the item count; a click
  opens tinyui. `approval` shows Approve/Deny (Phase 4).

**Done when:** a stub background run with a 2 KB answer produces a vault report, a ≤ 25-word island toast
with a working link, no speech, and the full text in the tinyui Inbox.

---

## Phase 3: Fast, concise defaults (2.10)

A profile per origin, read in one place (`hi/automation/profiles.py`, used by `turn.py` too):

| Origin | Tier | Reasoning | Style | Timeout |
|---|---|---|---|---|
| `island` | haiku (sonnet when `fast_route` says tools are needed) | off | ≤ 3 sentences, no headings | 30 s |
| `voice` | current routing | off for haiku | spoken rules from TODO §1 | current |
| `ui` | current routing (unchanged) | current | current | current |
| `heartbeat` triage | haiku, **local** if screen data is included | off | JSON only | 20 s |
| `heartbeat` prepare | sonnet | default | report style | 180 s |
| `schedule` | the schedule's `tier`, default sonnet | default | report style | 300 s |
| `drop` | haiku for describing, sonnet for filing | off / default | report style | 120 s |

- Add `CONCISE_STYLE` (a short prompt block) for `island`. Report style asks for: a one-line headline first,
  then sections, sources cited, and no questions at the end (the reader is not in a chat).
- Use the per-turn `timing` event (it already exists) and write `first_token_s` and `total_s` per origin to
  `~/.hi/state/usage.jsonl`. Target: a warm local haiku answers an island question with first token
  < 1.5 s.
- Don't escalate tiers automatically in the middle of a run. If a haiku run hits `max_tool_calls`, the answer
  says so and the next turn routes normally.

**Tests:** origin → profile mapping, with the screen-included heartbeat profile resolving to a local model,
or to "no screen" when none is configured.

---

## Phase 4: Approvals without tinyui; proposals (1.3)

Two kinds of approval, one UI.

**Live approvals** (an interactive turn waiting in `wait_for_approval`, 300 s timeout, deny on timeout):

- When `wait_for_approval` queues an action, also `deliver(Delivery(kind="approval", priority="urgent",
  headline=description, dedupe_key=f"approval:{id}"))`. The island shows Approve/Deny and calls
  `POST http://127.0.0.1:8765/pending/{id}/approve|deny`. tinyui keeps its card. The first answer wins
  (`resolve` already returns False for the second).
- Remove the `curl … :8766` reminder prints from `pending_actions.py`: that port is now the host bridge, so
  the hint is wrong.

**Proposals** (from unattended runs; they wait for you, possibly for days):

- `hi/memory/proposals.py`, an append-only `<vault>/hi/proposals.jsonl`:
  `create(origin, persona, tool, args, reason, report_id) -> id`, `pending()`, `get(id)`,
  `mark(id, status, result="")`. The current status is the last event for that id.
- Routes: `GET /proposals`, `POST /proposals/{id}/approve`, `POST /proposals/{id}/deny`.
- **Executing** an approved proposal happens in the server layer (`hi/server/proposals_exec.py`):
  1. Under a process lock, check the status is `created`. Otherwise return 409.
  2. Append `executing` **before** calling the tool.
  3. Look the tool up by name in the persona's tool list (`get_agent_builder(persona)`). Call it once with
     the stored args (the user approved exactly these args, which tinyui shows in full).
  4. Append `executed` with the result, or `failed` with the error. Never retry.
  5. On startup, a proposal stuck at `executing` becomes `failed: "interrupted; check manually"`. It is
     never re-run.
- Proposals expire after `PROPOSAL_TTL_DAYS` (default 7): an `expired` event, written by the heartbeat.
- A run that created proposals includes them in its delivery. The island shows "1 action needs approval",
  with Approve/Deny if there is exactly one. Otherwise it opens tinyui.

**Tests:** guard → proposal → approve → the tool is called exactly once. A second approve returns 409. A deny
never calls the tool. Restart recovery for `executing`. Live approval resolved from the island path.

**Done when:** a heartbeat-prepared "send follow-up email" shows up as a proposal with the full draft, and
approving it from the island sends it once.

---

## Phase 5: Scheduled tasks (2.5)

### Schedules are notes

One file per schedule, `<vault>/hi/schedules/<id>.md`, editable in Obsidian:

```markdown
---
id: morning-brief
when: "0 8 * * 1-5"          # 5-field cron, or "once 2026-11-20T15:00"
enabled: true
kind: task                    # task (runs the agent) | reminder (delivers the body verbatim, no model)
persona: term
tier: sonnet
deliver: notify               # notify | report | silent
context: [vault, screen]      # what the context pack includes
allow_web: true
allow: []                     # tools beyond read-only, granted when the schedule was made
catch_up: 2h                  # run a missed slot if we are back within this window
created: 2026-11-17T10:12
---
Brief me for today: overdue and due tasks, deadlines this week, open loops from yesterday's reflection,
PRs or CI that need me, and anything I left half-done yesterday (from the journal). Draft my standup.
```

### Build

- `uv add croniter` for cron parsing. Times are local time. **The container must know your timezone**:
  add `TZ: ${TZ:-UTC}` to the backend in `docker-compose.yml`, have `hi` set `TZ` from the host, and show the
  zone in `/health`.
- `hi/memory/schedules.py`: `load_all()`, `save(schedule)`, `delete(id)`, `next_fires(schedule, n, now)`,
  runs log `claim(id, slot) -> bool` (False if the slot is already in `runs.jsonl`), `finish(id, slot, ...)`.
- `hi/automation/scheduler.py`: `tick(now, run_turn, deliver)`, called every 30 s by `jobs.every("scheduler", …)`.
  - For each enabled schedule, work out the due slots since its last run. Run **only the most recent** missed
    slot if it is within `catch_up`. Mark older ones `missed` (one log line, no flood after a sleep).
  - `claim` the slot before running (dedupe). Runs go through a single background worker (a queue with one
    thread), so two schedules never load Ollama at once.
  - `kind: reminder` → `deliver(Delivery(kind="reminder", headline=body))`. No model call.
  - `kind: task` → build the context pack (Phase 6.1), then `run_turn(prompt, origin="schedule",
    policy=UNATTENDED + allow + allow_web)`, then deliver the result (`deliver: silent` writes the report only).
  - A `once` schedule sets `enabled: false` after it runs.
  - A failed run → `finish(status="failed")` + `deliver(kind="failure", headline="Morning brief failed:
    model host unreachable")`.
- Tools for `term` and `butler` (group `schedule`, P2, keywords `remind|every|each|schedule|daily|weekly|at \d`):
  - `schedule_task(task, when, kind="task", deliver="notify", context="vault", allow_web=False)` validates
    `when` and returns the id and **the next three fire times in words** ("Mon 18 Nov 08:00, Tue 19 Nov
    08:00, …"). The model must repeat the first one to you. You convert natural language to cron in the
    model; the tool rejects anything it cannot parse, with an example.
  - `list_schedules()`, `pause_schedule(id)`, `delete_schedule(id)`, `run_schedule_now(id)`.
  - `allow` with non-read-only tools needs `confirm_destructive` **at creation**, while you are present.
    After that the schedule may use those tools unattended.
- Routes for the tinyui Schedules tab: list, toggle, run now, delete, and the last runs.
- Seed nothing by default. Document three examples in `docs/automation.md`: morning brief, end-of-day
  journal summary, weekly review on Sunday 18:00 (this can replace the hardcoded `weekly-retro` job later;
  don't remove that job in this plan).

**Tests:** cron and `once` parsing; next fires; catch-up runs the newest slot only; a claimed slot never
runs twice (two ticks with the same `now`); a reminder makes no model call; a failure is delivered; editing
the note's frontmatter takes effect on the next tick without a restart.

---

## Phase 6: Heartbeat (2.6)

The heartbeat cuts your workload. It doesn't chat. Every 30 minutes it asks: *is there something I can
**prepare** for you right now, from what is on your screen and in your vault?* Most of the time the answer is
no, and that costs no model call.

### 6.1 The context pack

`hi/automation/context_pack.py`: `build(parts: set[str], now) -> ContextPack(text, screen_included: bool, sources)`.

- **vault**: `memory.context.build_context(query)` (for schedules: the prompt), today's and yesterday's
  journal headings, `reflection.latest_open_loops()`, tasks due or overdue, deadlines within 2 days
  (`hi/tracking/deadlines.py`), today's weekday note (`hi/context/weekday.py`), the recent report headlines
  (so it does not prepare the same thing twice).
- **screen** (only if `is_local(tier)`): through new bridge tools `current_context` (exists) and
  `recent_activity(minutes=30)` (new: `now.recent_history` grouped by app/project, with time spent).
- **calendar**: events in the next 3 hours if the Google MCP is configured. If not, skip quietly.
- Every part is capped (`MAX_CONTEXT_CHARS` style) and run through `redact()` before it goes to a hosted
  model.

### 6.2 One beat

`hi/automation/heartbeat.py`: `beat(now, run_turn, deliver) -> BeatResult`, called by
`jobs.every("heartbeat", HEARTBEAT_EVERY, …)` (default 1800 s).

1. **Gates (cheap, no model):** inside `HEARTBEAT_HOURS` (default `08-22`); `HEARTBEAT=on`; the screen
   context is not paused or private; the runs this hour are under the cap.
2. **Signals (deterministic):** collect the pieces above as a list of `Signal(key, text, weight)`. Reuse the
   deterministic checks in `hi/suggest/engine.py` (`_deadline_suggestions`, `_application_suggestions`,
   `_idle_repo_suggestions`, `_diff_watch_suggestions`) by moving them into `hi/automation/signals.py`.
   `engine.py` then imports them from there. Other signals: the same error-like screen text for more than
   15 minutes; a meeting within 60 minutes; new drop-folder items; proposals waiting more than 1 day.
3. **Fingerprint:** a hash of the signal keys. If it equals the previous beat's fingerprint, stop
   (`skipped_reason: unchanged`). Log the beat.
4. **Triage (haiku; local if screen included, JSON output):** given the signals, the recently delivered
   headlines and recently ignored ones (`inbox_log.jsonl` outcomes via the bridge), return at most 3
   decisions: `{action: prepare|nudge|none, task, why, evidence}`.
   - **Grounding (in code, as `proactive._grounded` does):** `evidence` must be a ≥ 12-char quote found
     in the signal text. Otherwise the decision is dropped.
   - `prepare` tasks are concrete work: "summarize the failing CI log for PR #41 and propose a fix",
     "collect my notes on Acme and the last thread with them for the 15:00 call", "draft the follow-up email
     due today".
5. **Prepare:** each `prepare` runs `run_turn(task, origin="heartbeat", policy=UNATTENDED, allow_web=True)`
   with the context pack. Its outputs are a report, plus proposals for anything that would act (send, write,
   push).
6. **Deliver once per beat:** one digest (`kind="digest"`, `dedupe_key` = fingerprint) listing what was
   prepared, with proposals attached. If nothing was prepared but there is a valid `nudge`, deliver it as one
   line. Otherwise deliver nothing.
7. **Housekeeping:** expire old proposals; mark `missed` schedule slots.

### Relationship to what already exists

- `proactive.nudge` (Mac, every 5 min, screen only) stays as it is: it reacts *now*. The heartbeat
  *prepares*. They share one interruption budget and one dedupe through the inbox gate (Phase 0.3), so they
  can't double-notify.
- `hi --suggest-daemon` overlaps with the heartbeat. Once the heartbeat ships, make `run_suggest_daemon`
  print a deprecation line pointing to `HEARTBEAT`, and remove it in a later cleanup (record that in the ADR).

**Tests:** gates; an unchanged fingerprint makes no model call; ungrounded decisions are dropped; screen
signals are excluded when no local model is configured (assert on the prompt text); one digest per beat;
budget exhausted → report written, nothing posted; ignored items lower the next beat's output (the prompt
includes them).

**Done when:** with a stub model and a fake bridge reporting 20 minutes on a stack trace plus a meeting in
40 minutes, one beat produces two reports, one digest, and zero side effects.

---

## Phase 7: Inbound media (2.7)

Media arrives without a chat app through three paths.

1. **The drop folder** `<vault>/hi/drop/` (`DROP_PATH` to override). The vault is in iCloud, so on the
   iPhone "Save to Files → vault/hi/drop" is the phone path: voice memos, photos, PDFs, shared web pages.
   - `hi/automation/drop.py`: `poll(now, run_turn, deliver)` via `jobs.every("drop", 60, …)`.
   - A file is ready when its size and mtime are unchanged across two polls. Skip `.icloud` placeholders,
     dotfiles and partial downloads (`.download`, `.part`, `.crdownload`).
   - Dedupe by `sha256` in `drop/index.jsonl`: a file already processed is moved, not reprocessed.
   - Extract with the existing `hi/attachments.py` readers (PDF, DOCX, images through the vision model, audio
     through whisper, zip). If automation must not import a top-level module that pulls in more, move the
     readers to `hi/memory/media.py` and have `attachments.py` use them.
   - Then one `run_turn(origin="drop", policy=UNATTENDED + {"create_note", "add_task"})`: write a note
     (`<vault>/hi/drop/notes/YYYY-MM-DD-<slug>.md` with the transcript or description, a summary and a link
     to the original), add the action items as tasks (reuse `hi/capture/ambient.normalize_ambient` for
     task extraction), and suggest a vault folder. Moving the note there is a proposal.
   - Move the original to `drop/processed/YYYY-MM/` and deliver "Filed voice memo: 2 tasks added".
2. **Screenshots** (opt-in, `SCREENSHOT_WATCH=off` by default): watch `/host/Desktop` for macOS screenshot
   names. Screenshots often contain secrets and private text, so **local vision model only**. If none is
   configured, the setting can't be turned on, and the Settings view says why.
3. **tinyui attachments** already work for interactive turns. Add a "File it" action on an uploaded
   attachment that sends it through the same drop pipeline.

**Tests:** stability check; `.icloud` skipped; sha256 dedupe; audio → transcript → note + tasks (stub
whisper and model); a failed transcription leaves the file in `drop/` and records the error once (no retry
loop on every poll: back off per file).

---

## Phase 8: Hardening

Parts of this landed in earlier phases. This phase completes and verifies it.

### Always on

- The backend already has `restart: unless-stopped`. Add a compose `healthcheck` hitting `/health` so Docker
  restarts a hung backend.
- Mac side: `hi --install-agent` / `hi --uninstall-agent` writes and loads
  `~/Library/LaunchAgents/<label>.plist` for the menu bar app (`RunAtLoad`, `KeepAlive`, logs to `~/.hi/logs/`).
  The app already supervises the context daemon and host bridge. This closes TODO §4 "context daemon under
  launchd".
- After the Mac sleeps, the scheduler's catch-up rule (Phase 5) applies. The heartbeat skips a beat that is
  more than 2× late instead of running twice.

### Health per component

`GET /health` and a tinyui health strip show: `ollama:*`, `host_bridge`, `sandbox`, `vault`, `searxng`,
`whisper`, `vision`, `island` (posting returned "not running"), `job:scheduler`, `job:heartbeat`,
`job:drop`, plus the last run time and last error for each job, the container timezone, and how many
proposals are pending. When a component is down, the feature that needs it says so in its delivery or tool
result. No feature fails silently.

### Dedupe

| Thing | Key | Where |
|---|---|---|
| Scheduled run | `(schedule_id, slot)` claimed before running | `runs.jsonl` |
| Heartbeat digest | signal fingerprint | `heartbeat/*.jsonl` + inbox `dedupe_key` |
| Notification | `dedupe_key`, per day | inbox gate (Mac) |
| Drop file | `sha256` | `drop/index.jsonl` |
| Proposal execution | status `created` → `executing` under a lock | `proposals.jsonl` |
| Search | `(query, params)` for 10 min | in-process cache |

### Rate and cost limits

`hi/automation/limits.py`, with counters in `~/.hi/state/usage.jsonl`, all configurable:

- Background runs per hour: `MAX_BACKGROUND_RUNS_PER_HOUR` (default 6). Heartbeat prepares per beat: 3.
- Per run: `max_tool_calls` (default 15, passed as the LangGraph `recursion_limit` and enforced by the guard)
  and a wall-clock timeout from the profile. A run past its timeout is reported as failed.
- Hosted (cloud) model calls by unattended work per day: `MAX_HOSTED_CALLS_PER_DAY` (default 50). After the
  cap, unattended work uses local tiers only or skips, and the skip is delivered once.
- Interruption budget: one shared budget at the inbox gate (default 3/hour; urgent, approval and reminder are
  exempt).

### Secret redaction

Apply `redact()` (with `config.secret_values()`) at every boundary where text leaves `hi`'s control:

- deliveries (headline, report body) and the island/notification text;
- `web_search` queries (refuse rather than redact) and `fetch` URLs;
- prompts sent by unattended runs to **hosted** models;
- anything the drop pipeline writes into notes from OCR, transcripts or documents.

`hi/memory/extraction.py`'s `_SECRET` filter stays (it drops whole memories). Make it also call
`contains_secret` so both checks agree.

**Tests:** health snapshot contents; each limit trips and is reported once; redaction cases (each pattern,
known values, no false positive on a normal 40-char git SHA); a `KeyError` in one job never stops the others.

---

## Settings added (all in `hi/config.py`, read live)

`SEARXNG_URL`, `SEARXNG_SECRET`, `HEARTBEAT` (on/off), `HEARTBEAT_EVERY`, `HEARTBEAT_HOURS`, `DROP_PATH`,
`SCREENSHOT_WATCH`, `PROPOSAL_TTL_DAYS`, `MAX_BACKGROUND_RUNS_PER_HOUR`, `MAX_HOSTED_CALLS_PER_DAY`,
`MAX_NOTIFICATIONS_PER_HOUR` (moved from `suggest/engine.py`), `TZ` (compose).

## Defaults for open questions

You don't need to ask about these unless the code shows they are wrong:

- **Schedules as Markdown notes, not one JSONL file.** They are editable in Obsidian, and that matches the
  vault-first principle.
- **One background worker.** Runs are queued, never parallel. Ollama on one machine can't usefully run two.
- **Heartbeat off at night** (`08-22`) and off while screen context is paused.
- **No auto-execution, ever, from unattended runs**, including "reversible" vault edits outside
  `hi/reports/`, `hi/drop/` and tasks. Widen this only with an explicit `allow` on a schedule.
- If `hi/host.py` can't be imported by `hi/automation` without breaking layering, split the bridge client
  out before Phase 0.3. Don't add an exception to the layering test.
