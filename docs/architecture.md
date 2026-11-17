# Architecture

A short, current description. The plan and its history are in [MAKE.md](../MAKE.md).

## One request

```text
tinyui ──POST /query──▶ hi/server/routes/query.py
                          │  one thread per request, streams AG-UI events back (SSE)
                          ▼
                    hi/server/turn.py
   route: fast rules ─▶ (else) classify with a small model, 8 s budget, falls back to term/sonnet
   agent: butler or term (or a forced docs/web), or an orchestrated plan (hi/orchestrator/)
   model: hi/llm/registry.py picks tier -> model, degrading to cheaper tiers, then the other host
                          │
                          ▼
              hi/memory/records.py  record_turn(TurnRecord)
   transcript (raw JSONL) · conversation (Markdown) · journal (Markdown) · memory extraction
```

## Packages

| Package | Owns | May import |
|---|---|---|
| `hi/core` | dependency health, `first_available` fallback, background jobs | nothing else in `hi` |
| `hi/llm` | Ollama providers (local, tailscale), tier registry, reasoning probe, retry/warm-up | core, config |
| `hi/memory` | everything stored in the vault | core, config, llm |
| `hi/agents` | `make_agent` factory, personas, their tools, the run guard | llm, memory, orchestrator, ... |
| `hi/automation` | background work: delivery, profiles, (scheduler, heartbeat, drop) | core, llm, memory, the Mac bridge client |
| `hi/orchestrator` | plan -> DAG of scoped subagents, approval queue | agents, llm, memory |
| `hi/server` | HTTP routes, the turn pipeline | everything below |

## Background work

Runs nobody asked for (schedules, the heartbeat, the drop folder) go through `hi/server/headless.py`: the same turn
pipeline, under the `UNATTENDED` policy (`hi/core/runpolicy.py`). `RunGuard` lets reads through and turns every other
tool call into a proposal in the vault (`hi/proposals.jsonl`) that the user approves from tinyui or the island.
Results are delivered by `hi/automation/deliver.py`: a report in `hi/reports/`, a one-line headline through the
inbox gate (`hi/context/inbox.py`) to the island. Decisions: [adr/0002-automation.md](adr/0002-automation.md).

## Failure handling

| What fails | What happens |
|---|---|
| A model tier is missing on the host | the next cheaper tier is used; a local model is pulled in the background |
| A host is unreachable | the other configured host (local / tailscale) is tried; the failed one is skipped for 30 s |
| The routing model is slow or down | the last route, else `term` on `sonnet`; the answer call reports the real error |
| The Mac bridge or the sandbox is down | tools that need it are not offered to the model |
| One log sink fails | the others still run; the turn is not affected |
| The TTS engine is down | one retry, then silence; text stays on screen |
| SearXNG is down | `web_search` is hidden from the model and `/health` shows `searxng` down |
| The Mac bridge or island is down | the report is still written; the pop-up is lost (a macOS notification if the app is closed) |
| An unattended run wants a risky tool | it is not run; a proposal waits for approval |

`GET /health` reports Ollama, the Mac bridge, the sandbox and the vault.

## Background jobs

Started in one place, the server lifespan (`hi/server/app.py` → `hi/startup.py`): inbox triage and the weekly
retro check (hourly, with backoff on failure), and the model warm-up. Each job's state is in `GET /health` as `job:<name>`.

## Decisions

See [adr/0001-restructure.md](adr/0001-restructure.md).
