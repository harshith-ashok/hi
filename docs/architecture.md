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
| `hi/agents` | `make_agent` factory, personas, their tools | llm, memory, orchestrator, ... |
| `hi/orchestrator` | plan -> DAG of scoped subagents, approval queue | agents, llm, memory |
| `hi/server` | HTTP routes, the turn pipeline | everything below |

## Failure handling

| What fails | What happens |
|---|---|
| A model tier is missing on the host | the next cheaper tier is used; a local model is pulled in the background |
| A host is unreachable | the other configured host (local / tailscale) is tried; the failed one is skipped for 30 s |
| The routing model is slow or down | the last route, else `term` on `sonnet`; the answer call reports the real error |
| The Mac bridge or the sandbox is down | tools that need it are not offered to the model |
| One log sink fails | the others still run; the turn is not affected |
| The TTS engine is down | one retry, then silence; text stays on screen |

`GET /health` reports Ollama, the Mac bridge, the sandbox and the vault.

## Background jobs

Started in one place, the server lifespan (`hi/server/app.py` → `hi/startup.py`): inbox triage and the weekly
retro check (hourly, with backoff on failure), and the model warm-up.

## Decisions

See [adr/0001-restructure.md](adr/0001-restructure.md).
