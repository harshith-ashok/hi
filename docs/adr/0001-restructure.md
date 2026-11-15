# 0001 — Restructure around tinyui and a layered package (2026-11-15)

Context: `hi/` had grown to about 60 flat modules, three hand-written HTTP servers, several front-ends and
one OpenRouter code path nobody used. Failures were handled one place at a time.

Decisions:

1. **tinyui is the one supported interface.** The REPL, the Textual TUI, the tmux panes and the per-persona
   flags were removed. `hi` starts the stack and opens tinyui.
2. **The Swift voice companion is archived** (git tag `archive/voice-companion`).
3. **Voice stays silent when the configured TTS engine is down.** A different voice is worse than none.
4. **OpenRouter was removed.** Only `local` and `tailscale` Ollama remain; fallback is between those two.
5. **Tracking and synthesis stay core packages**, not opt-in extras.
6. **The backend moved to Starlette + uvicorn.** Same paths and payloads, so tinyui and WhatsApp are unchanged.
7. **docs and web are no longer routing targets.** The router chooses between `butler` and `term`; `docs` and
   `web` remain as forced choices and as orchestrator subagents.

Consequences: fewer moving parts; `hi/core` gives every dependency one health state and one fallback helper;
every finished turn is written through `hi/memory/records.py`.
