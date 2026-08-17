# hi

A minimal, terminal-first AI assistant with four personas — each one a
dedicated LangGraph ReAct agent, launched straight into a tmux workspace.

![Python](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/managed%20with-uv-DE5FE9)
![LangChain](https://img.shields.io/badge/LangChain-1.3-1C3C3C)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2F%20cloud-000000?logo=ollama&logoColor=white)
![tmux](https://img.shields.io/badge/tmux-native-1BB91F?logo=tmux&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS-000000?logo=apple&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-none-critical)

---

## Philosophy

- The filesystem is the single source of truth — no vector DBs, no hidden
  state, nothing the model remembers that isn't also a file you can open.
- Terminal-first: instant startup, minimal dependencies, no GUI, ever.
- One tmux workspace per persona: your shell stays yours, the assistant
  gets its own pane.

## Personas

| Flag       | Name     | What it's for                                                       | Model                |
| ---------- | -------- | ------------------------------------------------------------------- | -------------------- |
| `--code`   | `code`   | Coding assistant with persistent Markdown memory, dev-flow launcher | `gpt-oss:120b-cloud` |
| `--butler` | `butler` | macOS system control, TODO list — Bluetooth, apps, brightness, lock | `gpt-oss:120b-cloud` |
| `--docs`   | `docs`   | Obsidian vault search — cites and summarizes only your own notes    | `gpt-oss:120b-cloud` |
| `--web`    | `web`    | Search-and-summarize over Wikipedia, on a faster model              | `web`                |

```text
(code) > Explain this error
(code) > I want to work on kaapi

(butler) > Turn Bluetooth off
(butler) > Lock my Mac
(butler) > Add buy milk to my todo list

(docs) > What does my Docker note say about volumes?
(docs) > Save this: <content> to preferences.md

(web) > What is virtual memory?
```

Typing `exit` or `quit` ends the assistant process only — the tmux window
stays open. Typing `clear`/`cls`, or pressing Ctrl-L, clears the terminal
without restarting the persona.

## Installation

Prerequisites: [`uv`](https://docs.astral.sh/uv/), `tmux`, and
[Ollama](https://ollama.com) configured with the models above.

```bash
git clone <this repo>
cd hi
uv tool install --editable .
```

This puts a `hi` shim on `PATH` at `~/.local/bin/hi`, pointing to an
isolated venv `uv` manages — `--editable` means edits to this repo take
effect immediately, no reinstall needed. Make sure `~/.local/bin` is on
your `PATH` (`uv tool update-shell` will add it if it isn't).

## Usage

```bash
cd ~/Projects/whatever
hi --code
```

opens a new tmux window (or session, if you weren't already in one) split
25/75: your shell on the left, the assistant on the right.

```text
+------------------------------+----------------------+
|                              |                      |
| your shell, untouched        | (code) >             |
|                              |                      |
+------------------------------+----------------------+
```

## Data — `~/.hi/`

`hi`'s own config lives under one fixed home directory, regardless of which
project directory you launched it from:

```text
~/.hi/
├── .env             # VAULT_PATH + per-persona model overrides
├── dev_flows.json   # user-managed, read-only to the agent
└── tree_cache.md    # cached `tree -L 4` snapshot of the vault
```

All actual memory — knowledge notes and conversation logs, from every
persona — is written into the user's own Obsidian vault, at the path
configured by `VAULT_PATH` in `~/.hi/.env` (defaults to `~/.hi/vault` if
unset):

```text
<VAULT_PATH>/hi/
├── knowledge/        # Markdown notes, organized by topic, tagged `hi`
└── conversations/    # one dated log per day, every persona, tagged `hi`
```

Every note and conversation log carries Obsidian-compatible YAML frontmatter
(`tags: [hi]`), so the vault's own tag search finds them like any other note.

`docs` can additionally *read* any note anywhere in the vault (not just
`hi/knowledge/`) to answer questions, but only ever *writes* inside
`hi/knowledge/` — your own notes are never edited or overwritten.

## Dev Flows

`code` can open a saved project workspace by name:

```text
(code) > I want to work on kaapi
```

configured in `~/.hi/dev_flows.json`:

```json
{
  "kaapi": {
    "directory": "/path/to/kaapi",
    "tmux": { "left": "bench start", "right": "htop" },
    "apps": ["zed", "open ."]
  }
}
```

This file is entirely yours to manage — there's no tool for the agent to
create or edit entries in it.

## Architecture

```text
hi/cli.py                  argparse + tmux launcher, dispatches to a persona
hi/personas.py              registry: persona name -> agent, on-turn hook
hi/repl.py                  generic input loop shared by every persona
hi/tmux_util.py              shared tmux new-session/new-window helper
hi/config.py                 reads ~/.hi/.env: VAULT_PATH + per-persona models
hi/vault.py                   shared Markdown memory tools, backed by the vault
hi/memory_graph.py            shared grounding graph: select notes -> load -> agent
hi/tree_cache.py               `tree -L 4` snapshot of the vault, for grounding

hi/agents/code/    (graph.py + dev_flow_tool.py)    the `code` persona
hi/agents/butler/  (butler.py)                       the `butler` persona
hi/agents/docs/    (docs.py)                          the `docs` persona
hi/agents/web/     (web.py)                            the `web` persona
```

## Further documentation

- [docs/assistants.md](docs/assistants.md) — terminal interface specification
- [CLAUDE.md](CLAUDE.md) — memory system implementation notes
- [docs/TODO.md](docs/TODO.md) — implementation progress
