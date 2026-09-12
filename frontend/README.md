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

- MCP-UI widgets aren't rendered (an iframe/sandboxed view for the
  `mcp_ui_widget` CUSTOM event) — same standing caveat as everywhere
  else in this project: no real MCP-UI server exists to build or verify
  that against yet.

**Note on the two bullets that used to be here** ("no History/Settings
sidebar," "no markdown rendering"): both were true when this section was
first written, before the later home-dashboard redesign added
`SettingsView.vue`/`HistoryView.vue` and `lib/markdown.ts`'s real
Markdown rendering — left stale here until now. Flagged rather than
silently correcting the historical record without saying so.

## Agents (TODO.md Phase 27)

`AgentTasksView.vue` (a new `agents` topbar link) — spin up a scoped,
on-demand agent from a plain-language task, backed by
`hi/agents_ondemand.py`. Per explicit request: before it commits to
running, it asks clarifying questions if the task is genuinely
ambiguous (skipped for the preset one-click buttons, which are already
well-specified). Runs live-poll for status; a finished run renders its
real Markdown result. Deliberately distinct from `AgentsColumn.vue`,
which shows the four fixed personas' live status and pending
approvals — a different concept from a user-spawned, one-off agent.

**MCP servers now live here too, per explicit follow-up request**: a
collapsible panel lists the known catalog (playwright/github/obsidian/n8n)
with live status and inline configure forms — a single credential field
for the single-value servers, a URL+token pair for n8n's own two-value
config — backed by new `POST /mcp/configure`/`POST /mcp/configure/n8n`
endpoints (direct writes, not routed through the agent-tool
`confirm_destructive()` gate — filling in a form and clicking Save
already *is* the confirmation). A dropdown lets you assign one connected
server's tools to the next spawned agent (`GET /agents/mcp-servers` —
only servers actually reachable right now, not just credentialed), and
an assigned run shows its server as a small badge on its card.

**Background tasks, replacing the old tmux-pane redirect entirely**
(TODO.md Phase 28, per explicit request — reported live as a real bug,
then phased out rather than just patched): a dev server or watcher
`term` starts via `run_shell_command` used to redirect into a brand-new
tmux pane, which only worked inside a specific two-pane launch layout —
this view now has its own "Background tasks" section instead (`GET
/background`, live-polled the same way agent runs are), each a card with
live-tailed output and a stop button (`POST /background/{id}/stop`), no
terminal pane involved anywhere in the chain.
