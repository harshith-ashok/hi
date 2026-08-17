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

---

## Phase 7 – Obsidian Vault Integration + Tweaks (see root `TODO.md`)

- [x] `hi/config.py`: read `~/.hi/.env` for `VAULT_PATH` + per-persona model
      overrides (`CODE_MODEL`, `BUTLER_MODEL`, `DOCS_MODEL`, `WEB_MODEL`)
- [x] `hi/vault.py`: shared Markdown memory tools (replacing the separate
      `code`/`docs` copies), storing knowledge and conversation logs inside
      `<VAULT_PATH>/hi/{knowledge,conversations}/` with Obsidian `tags: [hi]`
      frontmatter
- [x] Every persona (`code`, `butler`, `docs`, `web`) now logs conversations,
      not just `code`
- [x] `hi/memory_graph.py`: extracted the note-grounding LangGraph (select
      relevant notes/logs -> load context -> agent) out of `code` so `docs`
      uses the same grounded-answer pipeline
- [x] `hi/tree_cache.py`: `tree -L 4` snapshot of the vault, refreshed and
      fed into the grounding prompt as extra structural context
- [x] Migrated the pre-existing `~/.hi/memory/` data (1 knowledge note, 3
      conversation logs) into the vault and removed the stale directory
- [x] Fixed `open_dev_flow`'s tmux split: short-lived pane commands (e.g.
      `source .venv/bin/activate`) were closing the pane/window before the
      split happened — now each command keeps the pane alive afterward, and
      `split-window` targets the new window's captured id explicitly instead
      of relying on implicit "current window" continuity
- [x] `docs` reworked into a strict, whole-vault, citation-only RAG tool
      (`hi/agents/docs/vault_rag.py`): it searches every note in the vault
      (not just `hi/knowledge/`), always cites what it drew from, and
      refuses to answer from general knowledge when nothing relevant is
      found — separate grounding graph from `code`'s, which can still
      fall back to general knowledge
- [x] `hi/model_warmup.py`: retry helper for Ollama Cloud's intermittent
      empty `done_reason='load'` responses, used both for a startup
      warm-up call and for the note-selection call in the grounding graphs

---

## Phase 8 – REPL Responsiveness + Butler TODO List

- [x] Persona startup no longer blocks on a model warm-up network call —
      it now runs in a background thread, so the prompt appears and
      accepts input immediately after launch
- [x] `clear`/`cls` typed commands, plus a Ctrl-L keybinding (bound for
      both GNU readline and macOS's libedit-backed `readline` module,
      which need different bind syntax), clear the terminal without
      restarting the persona
- [x] `hi/agents/butler/todo.py`: `add_task`/`complete_task`/`remove_task`/
      `list_tasks` tools backed by a Markdown checklist at
      `<VAULT_PATH>/hi/todo.md`
- [x] `butler` greets the user with a "Today's Tasks:" summary of pending
      items at session start (via a new `Persona.greeting` field in
      `hi/personas.py`, printed once by `hi/repl.py` before the prompt loop)
