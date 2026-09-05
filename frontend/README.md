# hi — web frontend

A third way into the same backend as the terminal REPL and the native
`voice_companion` app — a real browser tab, styled to match `/ui.html`
(the same dark palette `voice_companion/Sources/HiVoice/Theme.swift`
already ports), with one addition neither of those has: full visibility
into what's happening in the background while a request runs, not just
the final answer.

## Run it

```bash
hi --voice-daemon   # in one terminal — the backend this talks to
cd frontend
npm install
npm run dev         # fixed at http://localhost:5173, matching hi/cors.py's allowlist
```

## What it shows, live, per turn

- **Thinking** — the model's real reasoning content (`hi/agui_adapter.py`
  now surfaces this as AG-UI's own `THINKING_*` events, not just the
  terminal's dimmed-text trick), collapsible, auto-collapses once the
  real answer starts.
- **Tool calls** — name, streamed args, and result, each its own card.
- **Subagent spawning** — for a genuinely multi-step request, each
  parallel subagent gets its own live status card (started → retrying →
  finished/error), not a single opaque "thinking…" spinner.
- **Pending approvals** — a destructive action queued from an
  orchestrated run renders as a real inline Approve/Deny card.

All of it reuses the exact same AG-UI event stream the native app
consumes — this is a second renderer of the same real events, not a
separate mechanism.

## What's deliberately not built here

- No History/Settings sidebar (the native app already has this — see
  `voice_companion/README.md`); this frontend is scoped to the live
  chat + background-activity view specifically asked for.
- MCP-UI widgets aren't rendered (an iframe/sandboxed view for the
  `mcp_ui_widget` CUSTOM event) — same standing caveat as everywhere
  else in this project: no real MCP-UI server exists to build or verify
  that against yet.
- No markdown rendering — text segments render as plain text (matching
  what the terminal itself shows), not parsed `**bold**`/lists. Kept
  simple deliberately; add a renderer later if it's actually wanted.
