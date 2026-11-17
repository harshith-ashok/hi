# Working on `hi`

`hi` is a personal assistant that runs on Ollama (local, or another machine over Tailscale), with LangChain
and LangGraph. tinyui (`tinyui/`) is the one supported interface; it talks to a Starlette backend (`hi/server/`).

## Principles

- **The filesystem is the single source of truth.** Everything `hi` remembers is a Markdown or JSONL file in
  the vault (`<VAULT_PATH>/hi/...`). The model stores nothing itself. No embeddings, vector store or database.
- **Importing a module does nothing.** No model clients, threads or file writes at import. Build things in
  factories; processes start their background work explicitly (`hi/server/app.py` lifespan, `hi/startup.py`).
- **Read settings live.** Use `import hi.config as config` and read `config.X` at call time. Never
  `from hi.config import X` (a runtime settings change would not reach you).
- **Every outside dependency can fail.** Record it in `hi/core/health.py`, try alternatives with
  `hi/core/fallback.py`, and make the failure visible (`GET /health`, a clear error event). Model calls are
  retried; tool calls are never retried (a tool that failed may have half-done something).
- **No cross-engine voice fallback.** If the configured TTS engine is down, `hi` stays silent.
- Keep functions small, add type hints, use `pathlib`, avoid new classes unless they help. Docstrings say what
  the code does now; history and reasoning go in `docs/adr/`.

## Layout

```text
hi/core/          health registry, fallback helper, background jobs (imports nothing else in hi)
hi/llm/           providers (local + tailscale Ollama), tier registry with fallbacks, reasoning probe, retry
hi/memory/        the vault: notes, conversation log, journal, transcript, extraction, reflection, context
hi/agents/        agent factory (base.py) and the personas: term, butler, docs, web
hi/orchestrator/  multi-step plans run as a DAG of scoped subagents
hi/automation/    background work: scheduler, heartbeat, drop folder, delivery, limits (never imports hi.server)
hi/server/        Starlette app: routes/ (one module per area), turn.py (one query end to end)
hi/cli.py         `hi` launcher and daemon flags
tinyui/           the web UI (Vue)
tests/unit/       unit tests; no network, no real vault
```

Layers: `server` / `cli` → `agents`, `orchestrator`, `automation`, others → `memory`, `llm` → `core`. A lower layer never
imports a higher one; `tests/unit/test_layering.py` enforces the parts that are already clean.

The restructuring plan and what is done are in `MAKE.md`. The package overview is `docs/architecture.md`.

## Commands

```bash
uv sync                       # install (desktop group = Mac voice extras; dev group = pytest)
uv run pytest                 # unit tests
hi                            # start the stack (Docker) and open tinyui
hi --voice-daemon             # run the backend natively on :8765, no Docker
cd tinyui && npx vue-tsc --noEmit -p tsconfig.app.json    # type-check the UI
```

## Before you commit

Run `uv run pytest`. Add or update a test next to any behaviour you change. Do not commit `.env` or anything
from `~/.hi`. Tests must never write to the real vault: use the `tmp_vault` fixture.
