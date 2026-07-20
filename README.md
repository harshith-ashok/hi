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

| Flag       | Name     | What it's for                                                        | Model                 |
| ---------- | -------- | --------------------------------------------------------------------- | ---------------------- |
| `--code`   | `code`   | Coding assistant with persistent Markdown memory, dev-flow launcher   | `gpt-oss:120b-cloud`  |
| `--butler` | `butler` | macOS system control — Bluetooth, apps, brightness, lock              | `gpt-oss:120b-cloud`  |
| `--docs`   | `docs`   | Study assistant — explains concepts, saves notes to a vault           | `gpt-oss:120b-cloud`  |
| `--web`    | `web`    | Search-and-summarize over Wikipedia, on a faster model                | `web`                  |

```text
(code) > Explain this error
(code) > I want to work on kaapi

(butler) > Turn Bluetooth off
(butler) > Lock my Mac

(docs) > Summarize today's lecture
(docs) > Save this explanation

(web) > What is virtual memory?
```

Typing `exit` or `quit` ends the assistant process only — the tmux window
stays open.

## Installation

Prerequisites: [`uv`](https://docs.astral.sh/uv/), `tmux`, and
[Ollama](https://ollama.com) configured with the models above.

```bash
git clone <this repo>
cd leo
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

Everything `hi` reads or writes lives under one fixed home directory,
regardless of which project directory you launched it from:

```text
~/.hi/
├── memory/
│   ├── knowledge/        # code's Markdown notes, organized by topic
│   └── conversations/    # one dated log per day, human-readable
├── dev_flows.json        # user-managed, read-only to the agent
└── vault/                # docs's study notes
```

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
cli.py             argparse + tmux launcher, dispatches to a persona
personas.py         registry: persona name -> agent, on-turn hook
repl.py             generic input loop shared by every persona
tmux_util.py         shared tmux new-session/new-window helper

graph.py + tools.py + dev_flow_tool.py    the `code` persona
butler.py                                  the `butler` persona
docs.py                                    the `docs` persona
web.py                                      the `web` persona
```

## Further documentation

- [assistants.md](assistants.md) — terminal interface specification
- [CLAUDE.md](CLAUDE.md) — memory system implementation notes
- [TODO.md](TODO.md) — implementation progress
