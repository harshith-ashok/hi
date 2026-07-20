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
