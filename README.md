# hi

A minimal, terminal-first AI assistant with four personas — each one a
dedicated LangGraph ReAct agent, launched straight into a tmux workspace —
plus an auto-routing mode that picks the right one (and the right model
tier) for you.

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
| `--butler` | `butler` | macOS control, TODO list — Bluetooth, volume, Wi-Fi, DND, screenshots, clipboard, apps, windows | `gpt-oss:120b-cloud` |
| `--docs`   | `docs`   | Obsidian vault search — cites and summarizes only your own notes    | `gpt-oss:120b-cloud` |
| `--web`    | `web`    | Search-and-summarize over Wikipedia, on a faster model              | `gpt-oss:20b-cloud`  |
| `--term`   | `term`   | Shell (NLP-to-command in your left pane) + general assistant — persistent memory, people notes, dev-flow launcher | `gpt-oss:120b-cloud` |

```text
(butler) > Turn Bluetooth off
(butler) > Lock my Mac
(butler) > Add buy milk to my todo list

(docs) > What does my Docker note say about volumes?
(docs) > Save this: <content> to preferences.md

(web) > What is virtual memory?

(term) > what are the files in this folder
(term) > what are the permissions on the first one
(term) > I want to work on kaapi
(term) > Who do I know?
```

`term` used to be shell-only, with a separate `code` persona for memory,
notes, and dev flows — `code` was removed and its functionality folded
into `term`, so there's one general-purpose persona instead of two with
overlapping responsibility. `term` is the only persona with real
cross-turn memory (recalls a previous command's output or a loaded note
without re-running/re-searching) and the only one grounded in
`hi/knowledge/`/`hi/conversations/` the way `code` used to be.

## Auto-Routing Mode

Running `hi` with no flag opens the same tmux workspace, but the right pane
starts as `(hi) >` instead of a fixed persona. Each prompt is classified —
which persona fits, and which model tier (haiku/sonnet/opus, Claude-style)
the request warrants — and routed automatically; the prompt updates to
show whichever persona just handled the turn:

```text
(hi) > what are the files in this folder
(term) > how many did you find
```

Every turn is classified independently — it's not "locked in" to one
persona for the rest of the session, so a short follow-up with no
persona-specific wording can occasionally route somewhere unexpected (a
known trade-off of per-turn classification, not a bug). `term`'s own
conversation memory is unaffected either way — it picks back up correctly
once a later turn routes back to it.

`--butler`/`--docs`/`--web`/`--term` still work exactly as before, for when
you want to force a specific persona and skip routing/tiering entirely.

Typing `exit` or `quit` ends the assistant process only — the tmux window
stays open. Typing `clear`/`cls`, or pressing Ctrl-L, clears the terminal
without restarting the persona. Pressing Ctrl-V records from the mic,
shows `listening...`, transcribes with `faster-whisper` once you stop
talking, and submits the transcript automatically — works in every
persona, since it's the one shared input loop.

## Installation

Prerequisites: [`uv`](https://docs.astral.sh/uv/), `tmux`, and
[Ollama](https://ollama.com) configured with the models above. Ctrl-V voice
input needs mic access (macOS will prompt for it the first time) and
downloads its `faster-whisper` model on first use.

```bash
git clone <this repo>
cd hi
uv tool install --editable .
```

This puts a `hi` shim on `PATH` at `~/.local/bin/hi`, pointing to an
isolated venv `uv` manages — `--editable` means edits to this repo's
*source* take effect immediately, no reinstall needed. It does **not**
auto-sync new *dependencies* added to `pyproject.toml`, though — after
pulling a change that adds one, run `uv tool upgrade hi` to update that
venv, or `hi` will fail with `ModuleNotFoundError` for the new package even
though `uv run` inside the repo works fine (it uses this repo's own
`.venv`, a separate environment). Make sure `~/.local/bin` is on your
`PATH` (`uv tool update-shell` will add it if it isn't).

## Usage

```bash
cd ~/Projects/whatever
hi --term
```

opens a new tmux window (or session, if you weren't already in one) split
25/75: your shell on the left, the assistant on the right.

```text
+------------------------------+----------------------+
|                              |                      |
| your shell, untouched        | (term) >             |
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
├── knowledge/         # Markdown notes, organized by topic, tagged `hi`
│   └── people/         # one note per person `term` knows about, e.g. Dean_Haidt.md
├── conversations/     # one dated log per day, every persona, tagged `hi`
└── todo.md            # butler's TODO list
```

Every note and conversation log carries Obsidian-compatible YAML frontmatter
(`tags: [hi]`), so the vault's own tag search finds them like any other note.

`docs` can additionally *read* any note anywhere in the vault (not just
`hi/knowledge/`) to answer questions, but only ever *writes* inside
`hi/knowledge/` — your own notes are never edited or overwritten.

## Dev Flows

`term` can open a saved project workspace by name:

```text
(term) > I want to work on kaapi
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
hi/cli.py                  argparse + tmux launcher, dispatches to a persona or router
hi/personas.py              registry: persona name -> agent, on-turn hook, build_agent
hi/repl.py                   generic input loop + auto-routing loop, shared prompt_toolkit setup
hi/router.py                  classifies each router-mode turn into (persona, tier)
hi/models.py                   haiku/sonnet/opus tier -> ChatOllama, pulls on demand
hi/streaming.py                 streams any agent's response token-by-token
hi/tmux_util.py              shared tmux new-session/new-window helper
hi/config.py                 reads ~/.hi/.env: VAULT_PATH + per-persona + tier models
hi/vault.py                   shared Markdown memory tools, backed by the vault
hi/memory_graph.py            shared grounding graph: select notes -> load -> agent
hi/tree_cache.py               `tree -L 4` snapshot of the vault, for grounding
hi/model_warmup.py             background warm-up + retry around Ollama Cloud's
                                 occasional empty done_reason='load' response
hi/voice.py                     Ctrl-V mic capture + faster-whisper transcription

hi/agents/butler/  (butler.py + todo.py + mac_control.py)          the `butler` persona
hi/agents/docs/    (docs.py + vault_rag.py)                         the `docs` persona
hi/agents/web/     (web.py)                                          the `web` persona
hi/agents/term/    (term.py + shell_pane.py + danger.py +             the `term` persona:
                    dev_flow_tool.py + people.py)                     shell + memory + people + dev flows
```

Every persona module exposes both a `model`/`agent` pair built at import
time (used by `--flag` launches) and a `build_agent(model)` factory (used
by the router to build the same persona bound to a different, tier-selected
model) — the direct-flag path is unaffected by the router's dynamic model
selection.

## Further documentation

- [docs/assistants.md](docs/assistants.md) — terminal interface specification
- [CLAUDE.md](CLAUDE.md) — memory system implementation notes
- [docs/TODO.md](docs/TODO.md) — implementation progress
