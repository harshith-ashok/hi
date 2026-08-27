# Terminal Interface Specification

## Philosophy

`hi` should remain a **minimal, terminal-first application**.

It should launch instantly, have minimal dependencies, and integrate naturally into an existing terminal workflow.

There should be **no GUI**.

---

# Installation

`hi` is installed as a real command on `PATH` via:

```bash
uv tool install --editable .
```

run from the repo root. `--editable` means edits to this repo's source take
effect immediately, without reinstalling. This puts a shim at
`~/.local/bin/hi` (uv's tool bin directory), pointing at an isolated venv uv
manages separately from this repo's own `.venv/` — `~/.local/bin` needs to
be on `PATH` for this to work (`uv tool update-shell` can add it). `/usr/bin`
is not a valid target on macOS: it's protected by System Integrity
Protection and not writable, even as root.

All of `hi`'s data — memory, conversations, dev flows, and study notes —
lives under `~/.hi/`, fixed regardless of which directory `hi` is run from
(see below). That's deliberate: since `hi` is a real installed command now,
per-project-directory storage would scatter assistant files across
whatever project you happened to run it from.

---

# Startup

Running:

```bash
hi --term
```

or

```bash
hi --butler
```

or

```bash
hi --docs
```

or

```bash
hi --web
```

or, for auto-routing mode (no flag — each prompt is classified and routed
to a persona automatically, see Auto-Routing Mode below):

```bash
hi
```

should automatically launch a dedicated tmux workspace.

If the user is not already inside a tmux session, create one.

If already inside tmux, create a new window.

The layout should be:

```bash
tmux new-session \; split-window -h -p 25
```

The right pane should launch the interactive assistant.

The left pane remains completely under the user's control.

Example layout:

```text
+------------------------------------------------------+----------------------+
|                                                      |                      |
|                                                      | (term) >             |
|                                                      |                      |
| User terminal                                        | Assistant            |
|                                                      |                      |
| vim                                                  |                      |
| cargo build                                          |                      |
| pytest                                               |                      |
| git status                                           |                      |
|                                                      |                      |
+------------------------------------------------------+----------------------+
```

The user should never lose access to their shell.

---

# Prompt

The assistant prompt should always indicate the active mode.

Examples:

```text
(butler) >
```

```text
(term) >
```

```text
(docs) >
```

```text
(web) >
```

Auto-routing mode starts as `(hi) >` and updates to show whichever persona
just handled the turn.

The prompt should be simple and fast.

No banners.

No ASCII art.

No startup animations.

---

# User Experience

Typical workflow:

```bash
cd ~/Projects/Kaapi

hi --term
```

Layout opens.

Left pane:

```bash
vim app.py
```

Right pane:

```text
(term) > Explain this error

(term) > what's in this directory

(term) > remember that this project uses Postgres, not SQLite

(term) > Open the project README
```

The user can continue editing code while interacting with the assistant.

---

# Butler Workflow

```bash
hi --butler
```

If there are pending tasks on the TODO list (kept as one Markdown file per
task under `hi/tasks/` in the vault — see `hi/capture/schema.py`), the
session opens with a summary of them before the prompt:

```text
Today's Tasks:
1. Buy Milk
2. Fix something
(butler) >
```

```text
(butler) > Turn Bluetooth off

(butler) > Open Safari

(butler) > Increase brightness

(butler) > Lock my Mac

(butler) > Add "buy milk" to my todo list

(butler) > Check off the milk task

(butler) > Remove the "fix something" task
```

---

# Docs Workflow

`docs` is a search-and-cite tool for the user's Obsidian vault, not a
general study assistant: it only answers from what's actually written in
the vault's notes, and says so plainly when it can't find anything —
it never falls back to its own general knowledge.

```bash
cd ~/University

hi --docs
```

```text
(docs) > What does my notes say about virtual memory?

(docs) > Summarize today's lecture note

(docs) > Save this: <content> to preferences.md
```

It can read any note anywhere in the vault (configured via `VAULT_PATH` in
`~/.hi/.env`) to find an answer, but it only ever creates or edits notes
inside `hi/knowledge/` under that vault — the user's own notes are never
written to, regardless of which directory `hi --docs` is run from.

---

# Web Workflow

```bash
hi --web
```

```text
(web) > What is virtual memory?

(web) > Summarize the Wikipedia article on the Byzantine Empire
```

Web is a dedicated search-and-summarize assistant: it looks up the relevant
Wikipedia article and returns a summary. It runs on a separate, faster
cloud-hosted Ollama model (named `web`) rather than the model the other
personas use, since lookups should feel closer to instant.

---

# Term Workflow

```bash
hi --term
```

```text
(term) > what are the files in this folder

(term) > what are the permissions on the first one
```

Term turns what you ask into real shell commands and runs them **visibly
in your left pane** — the same shell you're already using — rather than
invisibly in its own process. It remembers the conversation within a
session (unlike every other persona, which only sees the current turn), so
a follow-up question like "the first one" can be resolved from a previous
command's output; it decides for itself whether it already has enough
context to answer, or needs to run something new (possibly a more targeted
command informed by what it already knows) to find out.

Before running anything that looks destructive or hard to reverse — `rm`,
`mv`, `sudo`, `chmod`, force-pushes, `kill`, shell redirection, and the
like — it prints the command and asks for a `y`/`N` confirmation first.
Read-only/informational commands run immediately, no confirmation needed.

If a command never finishes (a dev server left running on purpose is the
common case), term normally waits up to its timeout with the prompt
unresponsive that whole time. Pressing Ctrl-J stops that wait immediately
without killing the command — it's presumed still running in the left
pane. For anything you already expect to run forever, ask term to split
it into its own pane instead (see Splitting Panes below) rather than
waiting on it at all.

Term is also the general-purpose assistant: it has the same persistent,
Markdown-based memory `code` used to have (there is no separate `code`
persona anymore — its functionality was folded into `term`), grounded in
`hi/knowledge/` and `hi/conversations/` the same way, plus per-person notes
and the dev-flow launcher below:

```text
(term) > remember that this project uses Postgres, not SQLite

(term) > who do I know

(term) > I want to work on kaapi
```

Term is aware of the directory `hi` was launched from — the implicit
active project for anything not otherwise scoped, so "commit and push" or
"what does this project do" don't require naming the directory. Shell
commands already ran there regardless (the left pane's real shell starts
there); this is about term's own reasoning.

For a genuinely ambiguous request — more than one reasonable
interpretation, or missing something needed to act safely — term asks a
short clarifying question instead of guessing, rather than risk guessing
wrong on something like a destructive shell command. The conversation
persists across turns, so the original request and the answer both stay
in context for the next turn to resolve correctly.

Term requires the standard two-pane `hi` tmux layout — it needs a sibling
pane to run commands in, so it can't run standalone outside tmux.

---

# Dev Flows

`term` can also open a saved development workspace for a project by name:

```text
(term) > I want to work on kaapi
```

Dev flows are configured in `~/.hi/dev_flows.json` — a project name mapped
to its directory, the apps to open it in, and a two-pane tmux layout to
start there:

```json
{
  "kaapi": {
    "directory": "/Users/harshith/Frappe/frappe-16/apps/kaapi",
    "tmux": {
      "left": "bench start",
      "right": "htop"
    },
    "apps": ["zed", "open ."]
  }
}
```

`term` can also save the directory it was launched from as a new dev flow:

```text
(term) > save this directory as a dev flow called kaapi
```

`dev_flows.json` remains a plain file the user can hand-edit anytime
either way — a flow saved this way starts with just a name and directory
(tmux layout and apps are optional), refined by hand afterward if wanted.

---

# Splitting Panes

Term can grow the current workspace beyond the fixed left/right layout —
splitting a new pane in the same window (not a new window) for something
that's meant to keep running, like a dev server or a log tail, so it
doesn't tie up the pane term runs ordinary commands in:

```text
(term) > split a pane and run npm run dev
```

The command runs immediately in the new pane, visible alongside the
others. There's no tool to close a pane this way — exit it normally (type
`exit`, or tmux's own pane-close shortcut) like any other pane.

---

# Daily Briefing

Auto-routing mode (`hi`, no flag) opens with a one-line briefing before
the first prompt: pending TODO items, the most recently edited vault note,
and the most recently opened project under `~/Dev/Projects/`, distilled
into one concrete, actionable suggestion phrased as a yes/no question —
e.g. "Want to check off the push-the-repo task?". Answering with a bare
`y`/`yes`/`sure`/etc. as the very first input carries out the suggested
action for real, through the normal classify-and-route pipeline. Any other
first input is treated as an ordinary turn and the suggestion is dropped.

---

# Exit

Typing

```text
exit
```

or

```text
quit
```

should terminate the assistant process only.

The tmux window should remain open.

---

# Clearing the Screen

Typing `clear` or `cls`, or pressing Ctrl-L, clears the terminal without
restarting the assistant or losing its memory of the conversation so far.

---

# Voice Input

Pressing Ctrl-V, in any persona, starts recording from the default
microphone. The prompt shows `listening...` while it records; once the
user stops talking (silence detected after they've spoken), it transcribes
what was said with a local `faster-whisper` model and submits it
immediately — the same as typing it and pressing Enter.

There's no push-to-talk or manual stop: recording ends on its own once
speech is detected and then silence follows, capped at a maximum length so
a stuck-open mic can't hang the assistant indefinitely.

---

# Performance Goals

The application should feel instantaneous.

- Fast startup
- Low memory usage
- Streaming responses
- Minimal Python overhead
- No background daemons
- No unnecessary services
- No web server
- No GUI

The assistant should behave like a native terminal tool rather than a desktop application.

---

# Future Expansion

The terminal interface should be modular enough to support additional panes in the future (such as logs, memory inspection, or tool output), but the initial implementation should remain a simple two-pane layout with the user shell on the left and the assistant on the right.
