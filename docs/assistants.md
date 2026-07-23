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
hi --code
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
|                                                      | (code) >             |
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
(code) >
```

```text
(docs) >
```

```text
(web) >
```

The prompt should be simple and fast.

No banners.

No ASCII art.

No startup animations.

---

# User Experience

Typical workflow:

```bash
cd ~/Projects/Kaapi

hi --code
```

Layout opens.

Left pane:

```bash
vim app.py
```

Right pane:

```text
(code) > Explain this error

(code) > Create a unit test

(code) > Refactor src/models.py

(code) > Open the project README
```

The user can continue editing code while interacting with the assistant.

---

# Butler Workflow

```bash
hi --butler
```

```text
(butler) > Turn Bluetooth off

(butler) > Open Safari

(butler) > Increase brightness

(butler) > Lock my Mac
```

---

# Docs Workflow

```bash
cd ~/University

hi --docs
```

```text
(docs) > Explain virtual memory

(docs) > Summarize today's lecture

(docs) > Save this explanation
```

New notes are created inside `~/.hi/vault/`, regardless of which directory
`hi --docs` is run from.

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

# Dev Flows

The `code` persona can also open a saved development workspace for a
project by name:

```text
(code) > I want to work on kaapi
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

`dev_flows.json` is user-managed only — the assistant can read and act on
it, but has no tool to create, edit, or add entries to it.

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
