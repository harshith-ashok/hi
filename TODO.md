# TODO

## Phase 1 – Project Setup

- [x] Create project structure
- [x] Set up Ollama with LangChain + LangGraph
- [x] Create `memory/` directory
- [x] Create `memory/conversations/`
- [x] Create `memory/knowledge/`

---

## Phase 2 – Filesystem Tools

- [x] Create `create_note(path, content)`
- [x] Create `append_note(path, content)`
- [x] Create `read_note(path)`
- [x] Create `list_notes()`

---

## Phase 3 – Agent

- [x] Create the LangGraph agent
- [x] Load the system prompt
- [x] Register filesystem tools
- [x] Save every conversation to `memory/conversations/`
- [x] Allow the agent to create and update notes in `memory/knowledge/`
- [x] Test with a few conversations to verify notes are organized correctly
- [x] Recall relevant notes/conversation logs automatically before answering
- [x] Proactively save durable facts to knowledge/ without an explicit "remember"

---

## Phase 4 – Terminal Interface (`hi` CLI, see assistants.md)

- [x] `hi` console-script entry point + `--alfred` / `--jarvis` / `--vivilio` argparse
- [x] tmux launcher (new-session/new-window + `split-window -h -p 25`)
- [x] Generic REPL loop: persona prompt `(name) >`, exit/quit handling
- [x] Wire Jarvis persona (reuse the memory-backed coding agent from graph.py)
- [x] Alfred persona: macOS system-control tools (bluetooth, open app, brightness, lock)
- [x] Vivilio persona: study-note tools writing to `Vault/hi/`

---

## Phase 5 – Renamed Personas, Dev Flows, Web Persona

- [x] Rename personas: jarvis → code, alfred → butler, vivilio → docs
- [x] `open_dev_flow(project)` tool: reads user-managed `dev_flows.json` (read-only,
      no agent-facing add/edit) and opens its directory/apps/tmux layout
- [x] Shared `tmux_util.run_tmux` helper (used by both cli.py and the dev-flow tool)
- [x] Web persona (`--web`): Wikipedia search + summarize, using a separate
      Ollama model

---

## Phase 6 – `~/.hi/` Home Directory + Real Install

- [x] Move memory/, dev_flows.json, and Vault to a fixed `~/.hi/` home
      (`~/.hi/memory/`, `~/.hi/dev_flows.json`, `~/.hi/vault/`), independent
      of whatever directory `hi` is run from
- [x] Migrate existing real data (conversation log, knowledge note, dev
      flows) into `~/.hi/` and remove the now-stale repo-local copies
- [x] Install `hi` as a real `PATH` command via `uv tool install --editable .`
      (`/usr/bin` isn't writable on macOS — SIP-protected)
