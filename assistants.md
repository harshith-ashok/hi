# Terminal Interface Specification

## Philosophy

`hi` should remain a **minimal, terminal-first application**.

It should launch instantly, have minimal dependencies, and integrate naturally into an existing terminal workflow.

There should be **no GUI**.

---

# Startup

Running:

```bash
hi --alfred
```

or

```bash
hi --jarvis
```

or

```bash
hi --vivilio
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
|                                                      | (jarvis) >           |
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
(alfred) >
```

```text
(jarvis) >
```

```text
(vivilio) >
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

hi --jarvis
```

Layout opens.

Left pane:

```bash
vim app.py
```

Right pane:

```text
(jarvis) > Explain this error

(jarvis) > Create a unit test

(jarvis) > Refactor src/models.py

(jarvis) > Open the project README
```

The user can continue editing code while interacting with the assistant.

---

# Alfred Workflow

```bash
hi --alfred
```

```text
(alfred) > Turn Bluetooth off

(alfred) > Open Safari

(alfred) > Increase brightness

(alfred) > Lock my Mac
```

---

# Vivilio Workflow

```bash
cd ~/University

hi --vivilio
```

```text
(vivilio) > Explain virtual memory

(vivilio) > Summarize today's lecture

(vivilio) > Save this explanation
```

New notes are created inside:

```text
Vault/
└── hi/
```

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
