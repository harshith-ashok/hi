<div align="center">

![hi](hi_banner.png)

### A terminal-first AI assistant that lives in a tmux pane next to your shell.

No GUI. No browser tab. Nothing to Alt-Tab to — just a prompt, right where you're already working.

![Python](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/managed%20with-uv-DE5FE9)
![LangChain](https://img.shields.io/badge/LangChain-1.3-1C3C3C)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2F%20cloud-000000?logo=ollama&logoColor=white)
![tmux](https://img.shields.io/badge/tmux-native-1BB91F?logo=tmux&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS-000000?logo=apple&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-none-critical)

</div>

---

![demo](demo.png)

*One real session, no cuts: `butler` explaining what's running, `web` reading a live dev-server URL back, `term` creating a file, confirming a destructive-looking command, and splitting a new pane — all in the same right-hand tmux pane, left pane never touched.*

## Why `hi`

Most AI coding assistants want their own window, their own editor, their own everything. `hi` doesn't. It opens as a 25%-width pane next to whatever you're already doing and stays out of the way until you talk to it.

- **The filesystem is the single source of truth.** No vector DB, no hidden state — anything `hi` remembers is a Markdown file you can open, edit, or delete yourself, stored in your own Obsidian vault.
- **Terminal-first, always.** Instant startup, no GUI, ever — that's a hard constraint, not a launch-day placeholder.
- **Your shell stays yours.** One tmux pane per persona; the assistant runs commands in a pane it never takes away from you.

## Features

| | |
|---|---|
| **5 ways in** | Four dedicated personas (shell + general assistant, macOS control, vault search, web lookup) plus an auto-routing mode that classifies each prompt and picks one for you |
| **Claude-style model tiers** | Every auto-routed turn also picks a haiku/sonnet/opus-equivalent Ollama model sized to the request — pulled on demand if you don't have it yet |
| **Real streaming** | Token-by-token output, not a wall of text after a long wait |
| **Persistent memory** | Notes, per-person context, and full conversation history — grounded automatically before every answer, no vector search required |
| **Strict, cited vault search** | `docs` only ever answers from what's actually written in your notes, and says so plainly when it can't find anything |
| **Real shell execution** | Commands run *visibly* in your own left-hand pane, not hidden in a subprocess — heredocs, pagers, and multi-step chains (`git add` → `commit` → `push`) all handled |
| **Voice input** | Ctrl-V records, transcribes locally with `faster-whisper`, and drops the text in the input line for you to edit before sending |
| **Deep macOS control** | Bluetooth, volume, Wi-Fi, Do Not Disturb, screenshots, clipboard, brightness, lock, app/window management |
| **Dev-flow launcher** | Reopen a saved project's directory, apps, and tmux layout by name — or save your current directory as a new one, hands-free |
| **A daily briefing** | Auto-routing mode opens with your pending tasks, deadlines, idle-repo flags, application follow-ups, most recently touched note, and most recent project, boiled down into one actionable yes/no suggestion |
| **Real browsing + MCP servers** | `term` can navigate real web pages via Playwright (no setup needed), and connect to GitHub or Obsidian once you provide your own credentials — one config layer, more servers are just a config entry away |
| **Never stuck on a runaway process** | Dev servers and watch-mode commands are detected and redirected to their own tmux pane automatically, before you ever have to wait on one — `check_dev_servers` checks their health on demand |
| **Global quick-capture** | A system-wide hotkey (`hi --capture-daemon`) drops a raw thought into an untriaged inbox from anywhere, no `hi` pane needed — classified into a real task or event automatically at the next session |
| **"Where was I"** | `term`'s `resume_context` (or just launching `hi --term` inside a known project) surfaces recent commits, working-tree status, recent conversation mentions, and the project's own note |
| **Deadline / LeetCode / application tracking** | One structured vault note per item — deadlines aggregated from anywhere in the vault, a daily LeetCode pick opened straight in the browser with streak/weak-topic stats, application follow-up nudges |
| **"What should I work on"** | `what_next` gives ONE deterministic recommendation + a one-line reason (deadline proximity, priority, idle projects) — never a ranked list, so it actually removes the decision |
| **Auto-generated weekly retro** | Every Sunday, a dated note aggregates the week's tasks, git activity, deadlines, and LeetCode streak — also runnable on demand |
| **Continuous suggestion engine** | `hi --suggest-daemon` runs independently of any `hi` session, checking idle repos/deadlines/LeetCode/applications on an interval and surfacing real macOS notifications — confidence-gated and deduped so it doesn't nag |
| **Team ops + pipelines** | Task ownership, plain-text status drafts, and deadline pings for a team; a generic named-pipeline tracker (custom stages) for anything else shaped like a funnel |
| **Perception** | `observe_current_tab`/`read_screen`/`ask_about_screen` — callable directly whenever asked, on-demand only (never a background watcher), and auto-refuse near a password manager or a private/incognito window |
| **Real project file access** | `read_project_file`/`list_project_files`/`search_files` (by name or content, `.gitignore`-respecting) — direct filesystem access `term` never had before, independent of any shell/tmux, so it also works from the voice companion. `save_project_to_vault` reads a project's README/manifest/structure and writes a real, model-synthesized summary note in one call |
| **Content-aware vault grounding** | Both grounding graphs (`term`'s and `docs`'s) now see a real content preview of each note before deciding relevance, not just its filename — a note with a non-descriptive name is no longer invisible to retrieval |
| **Ambient voice loop** | `hi --wake-daemon` listens only for "Hey Jarvis" (local, ONNX-based, no account needed), then transcribes your command, routes it, and speaks the answer back sentence-by-sentence as it streams — fully hands-free, no typing or Ctrl-V. A fresh wake-word trigger barges in on whatever's still being spoken |
| **Local text-to-speech** | Every streamed response can be spoken aloud via macOS's built-in `say`, sentence-by-sentence as it generates rather than after the fact — shared by the wake-word loop and available to any future caller of `hi/streaming.py` |
| **Gated background awareness** | `hi --suggest-daemon` now also notices state changes on its own — staying on the same app 20+ minutes without switching — as one more confidence-gated, deduped `Suggestion`, never a separate notification path. An explicit opt-in (`DIFF_WATCH_ENABLED`, off by default) adds screenshot-hash change detection too — never OCR'd, never stored, gated through the same privacy refusal every perception tool already uses |
| **Real coding-agent loop** | `term` can propose and apply real file edits (`edit_project_file`'s targeted find/replace, or `write_project_file` for a new file/full rewrite), then run tests via `run_shell_command` and iterate on the actual failure output — not just read/explain code. Overwriting an existing file's whole content asks to confirm first; a targeted edit doesn't (the exact text removed is always visible in the tool call, so it's trivially reversible) |
| **Smarter opt-in reasoning layers** | Real model calls now sit alongside every deliberately-deterministic default, never replacing it: `what_next_smart()`/`generate_retro_smart()` (a narrative justification instead of a fixed formula), `reflect_on_week()` (proposes durable preferences from the week's conversations), `synthesize_vault()` (a genuine whole-vault synthesis, not a relevance-selected subset), and an opt-in model-judgment pass over `hi --suggest-daemon`'s own suggestions. A real lightweight planner also decomposes an ambitious multi-step, multi-persona request ("check my deadlines, then look X up, then save a note about it") into ordered steps run through the normal persona router, then synthesizes one final answer — instead of requiring several separate turns |
| **Visible model thinking** | Every persona's model streams its real `thinking`/reasoning content live (dimmed, prefixed) before its answer, not silently dropped — probed once per model so it's only enabled where the model actually supports it |
| **Multi-turn arbiter negotiation** | "What should I work on" → a recommendation → "no, something else" now works as a real back-and-forth: the next pick excludes whatever was just turned down, re-running the same real scoring pass instead of suggesting the identical task again or losing the thread entirely |
| **Multi-agent orchestration** | A genuinely complex, multi-part request ("search X and Y, then compare them in a note") is decomposed into a real task DAG — not just an ordered list — and independent tasks actually run *concurrently* via a real LangGraph `StateGraph`, each a scoped subagent with only the tools its one task needs. A dependent task gets the real upstream results threaded into its own prompt, not just told to run after them. Checkpointed (a crash mid-DAG can resume), and every run is written as a dated trace note under `hi/conversations/runs/` |
| **Pending-approval queue for autonomous actions** | A destructive action an orchestrated subagent hits can't block on a terminal `input()` no one's watching — it queues instead, printing the exact `curl` commands to approve/deny it, and the voice companion's menu bar shows a live "N awaiting approval" indicator with per-action Approve/Deny. A normal interactive turn's own confirm prompt is completely unaffected — same `input()` as always |

## Quick Start

Prerequisites: [`uv`](https://docs.astral.sh/uv/), `tmux`, and [Ollama](https://ollama.com) configured with the models below.

```bash
git clone <this repo>
cd hi
uv tool install --editable .
```

This puts a `hi` shim on `PATH` at `~/.local/bin/hi`, pointing to an isolated venv `uv` manages — `--editable` means edits to this repo's *source* take effect immediately, no reinstall needed. It does **not** auto-sync new *dependencies* added to `pyproject.toml`, though — after pulling a change that adds one, run `uv tool upgrade hi`, or `hi` will fail with `ModuleNotFoundError` for the new package even though `uv run` inside the repo works fine (that uses this repo's own `.venv`, a separate environment). Make sure `~/.local/bin` is on your `PATH` (`uv tool update-shell` will add it if it isn't).

Ctrl-V voice input needs mic access (macOS will prompt the first time) and downloads its `faster-whisper` model on first use.

```bash
cd ~/Projects/whatever
hi
```

opens a new tmux window (or session, if you weren't already in one) split 25/75: your shell on the left, the assistant on the right — auto-routing by default, or add a flag below to force a specific persona.

```text
+------------------------------+----------------------+
|                              |                      |
| your shell, untouched        | (hi) >               |
|                              |                      |
+------------------------------+----------------------+
```

## Personas

| Flag       | Name     | What it's for                                                       | Model                |
| ---------- | -------- | ------------------------------------------------------------------- | -------------------- |
| `--term`   | `term`   | Shell (NLP-to-command in your left pane) + general assistant — persistent memory, people notes, dev-flow launcher | `gpt-oss:120b-cloud` |
| `--butler` | `butler` | macOS control, TODO list — Bluetooth, volume, Wi-Fi, DND, screenshots, clipboard, apps, windows | `gpt-oss:120b-cloud` |
| `--docs`   | `docs`   | Obsidian vault search — cites and summarizes only your own notes    | `gpt-oss:120b-cloud` |
| `--web`    | `web`    | Search-and-summarize over Wikipedia, on a faster model              | `gpt-oss:20b-cloud`  |

```text
(term) > what are the files in this folder
(term) > what are the permissions on the first one
(term) > I want to work on kaapi
(term) > Who do I know?

(butler) > Turn Bluetooth off
(butler) > Lock my Mac
(butler) > Add buy milk to my todo list

(docs) > What does my Docker note say about volumes?
(docs) > Save this: <content> to preferences.md

(web) > What is virtual memory?
```

`term` is the general-purpose default — there used to be a separate `code` persona for memory, notes, and dev flows, which was removed and folded into `term`, so there's one persona for that instead of two with overlapping jobs. It's the only persona with real cross-turn memory (recalls a previous command's output or a loaded note without re-running/re-searching) and the only one grounded in `hi/knowledge/`/`hi/conversations/`.

## Auto-Routing Mode

Running `hi` with no flag starts the right pane as `(hi) >` instead of a fixed persona. Each prompt is classified — which persona fits, and which model tier the request warrants — and routed automatically; the prompt updates to show whichever persona just handled the turn:

```text
(hi) > what are the files in this folder
(term) > how many did you find
```

Every turn is classified independently — it's not "locked in" to one persona for the rest of the session, so a short follow-up with no persona-specific wording can occasionally route somewhere unexpected (a known trade-off of per-turn classification, not a bug). `term`'s own conversation memory is unaffected either way — it picks back up correctly once a later turn routes back to it.

`--butler`/`--docs`/`--web`/`--term` still work exactly as shown above, for when you want to force a specific persona and skip routing/tiering entirely.

Auto-routing mode also opens with a one-line briefing — pending TODO items, the most recently edited vault note, and the most recently opened project, distilled into one actionable suggestion:

```text
Today's Tasks:
1. Buy milk
Most recently edited vault note: hi/conversations/2026-08-18.md
Most recently opened project: hi

Want to check off the buy milk task?
(hi) > yes
```

Answering with a bare `y`/`yes`/`sure`/etc. as the very first input runs the suggested action for real, through the normal routing pipeline — anything else is treated as a normal turn and the suggestion is dropped.

### Smarter Reasoning Layers

Two more real model passes sit inside auto-routing mode, both gated so the common single-step turn pays no extra cost:

- **Multi-agent DAG orchestration.** A single classification call already picks a persona/tier per turn; the same call also decides whether the request genuinely needs to be broken into several sub-tasks (most don't — no extra latency for an ordinary turn). When it does, a real `opus`-tier call decomposes it into an actual dependency graph, not just an ordered list — tasks with no shared dependency run **concurrently** (a real LangGraph `StateGraph`, not a hand-rolled scheduler), each a scoped subagent limited to only the tools its one task needs, and a dependent task gets the real upstream results threaded into its own prompt:
  ```text
  (hi) > search wikipedia for what a kubernetes pod is, and separately search
         wikipedia for what a docker container is, then save a note comparing them

  This looks like a multi-step request — planning a task DAG...
  [t1 (web) and t2 (web) run concurrently; t3 (docs) waits for both, then runs]

  <synthesized comparison answer>

  (ran 3 tasks — see hi/conversations/runs/ for the full trace)
  ```
  Checkpointed (a crash mid-run can resume), and every run is written as a dated trace note under `hi/conversations/runs/` — the real DAG shape, which subagent called which tools, and each task's actual result.
- **Multi-turn arbiter negotiation.** "What should I work on" → a recommendation → "no, something else" now works as a real back-and-forth instead of three unrelated turns: the router remembers which task the arbiter just recommended, and a rejection ("no", "something else", "not that") re-runs the same real scoring pass with that task excluded — never repeating the same answer, and never needing a model call just to notice it's a pushback.

Every persona also now streams the model's real `thinking`/reasoning content live (dimmed, prefixed `(thinking) ...`) before its actual answer, wherever the underlying model supports it — probed once per model and cached, so it's silently skipped for a model that doesn't. `what_next_smart()`/`generate_retro_smart()`/`reflect_on_week()`/`synthesize_vault()` (all `term` tools) are further opt-in "smart" layers over the existing deterministic defaults — see [Personas](#personas), above, for when to reach for each.

## Keyboard & Commands

| Key / word | Effect |
|---|---|
| `exit` / `quit` | End the assistant process only — the tmux window stays open |
| `clear` / `cls`, **Ctrl-L** | Clear the terminal without restarting the persona |
| **Ctrl-V** | Record from the mic, transcribe with `faster-whisper`, drop the text in the input line for you to review or edit — Enter submits it same as typing |
| **Ctrl-J** | Stop and talk over whatever's currently happening — a shell command that's never going to finish (a dev server left running on purpose is the common case, `term` only) without killing it, **or** a response that's still generating, in any persona — one shared interrupt for both, not two separate mechanisms |

Outside any `hi` pane, `hi --wake-daemon` runs a standalone, fully hands-free loop: say "Hey Jarvis," then speak your request — it's transcribed, routed, and the answer is spoken back sentence-by-sentence as it streams. Saying "Hey Jarvis" again while it's still talking barges in immediately. No typing needed at any point; Ctrl-C stops the daemon.

## Configuration — `~/.hi/`

`hi`'s own config lives under one fixed home directory, regardless of which project directory you launched it from:

```text
~/.hi/
├── .env             # VAULT_PATH + per-persona + tier model overrides +
│                    # DIFF_WATCH_ENABLED / SMART_SUGGESTIONS_ENABLED
│                    # (both off by default — see Gated Background
│                    # Awareness and Smarter Opt-In Reasoning, above)
├── dev_flows.json   # project name -> directory, apps, tmux layout
└── tree_cache.md    # cached `tree -L 4` snapshot of the vault
```

All actual memory — knowledge notes and conversation logs, from every persona — is written into your own Obsidian vault, at the path configured by `VAULT_PATH` in `~/.hi/.env` (defaults to `~/.hi/vault` if unset):

```text
<VAULT_PATH>/hi/
├── knowledge/         # Markdown notes, organized by topic, tagged `hi`
│   └── people/         # one note per person `term` knows about, e.g. Dean_Haidt.md
├── conversations/     # one dated log per day, every persona, tagged `hi`
└── tasks/             # one Markdown file per task/event, see hi/capture/schema.py
    ├── inbox/           # untriaged raw captures from the global hotkey
    ├── leetcode/         # one daily attempt log per date
    └── applications/     # one note per tracked job/internship application
```

Every note, conversation log, task, and event carries Obsidian-compatible YAML frontmatter (`tags: [hi, ...]`), so the vault's own tag search finds them like any other note. Any note can also carry a `due:` field to declare a deadline (`hi/frontmatter.py`) — tasks use it as their canonical example, but it isn't limited to them. `docs` can additionally *read* any note anywhere in the vault (not just `hi/knowledge/`) to answer questions, but only ever *writes* inside `hi/knowledge/` — your own notes are never edited or overwritten.

### Dev Flows

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

`term` is also aware of the directory `hi` was launched from (it's the implicit "active project" for anything you don't otherwise scope), and can save it as a new dev flow itself:

```text
(term) > save this directory as a dev flow called kaapi
```

`dev_flows.json` stays a plain file you can hand-edit anytime either way — this just gives `term` a way to add to it too. `term` can also split a new pane in the current workspace for something meant to keep running (a log tail, a second shell), rather than tying up the pane it runs ordinary commands in:

```text
(term) > split a pane and run tail -f server.log
```

Dev servers and watch-mode commands (`npm run dev`, `vite`, `bench start`, and similar) are detected automatically and redirected to their own pane the moment you ask for them through `run_shell_command` — you don't need to explicitly ask for `add_pane` for those specifically, it happens either way.

### MCP Servers

`term` can connect to [MCP](https://modelcontextprotocol.io) servers for capabilities beyond what's built in — one client layer (`hi/mcp_tools.py`), so adding another server later is a config entry, not new plumbing.

| Server | Needs | Status |
|---|---|---|
| Playwright (real web browsing) | Node.js + `npx` | Enabled by default, no setup — verified live: real navigation, real page titles back |
| GitHub (repos, issues, PRs, Actions) | `GITHUB_PERSONAL_ACCESS_TOKEN` in `~/.hi/.env`, Docker actually running | Off until you add a token; needs Docker (e.g. Rancher Desktop) started separately |
| Obsidian | The community ["Local REST API"](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin installed in Obsidian itself, then `OBSIDIAN_REST_API_KEY` in `~/.hi/.env` from its settings | Verified live: real vault listing, both directly and through `term` via natural language |

A server that isn't configured is simply absent — no crash, `term` works the same either way. A server that fails to connect (Docker not running, a bad token) is skipped with a logged warning, not a hard failure for the whole persona. The Obsidian plugin's self-signed local certificate needs certificate verification disabled specifically for that connection (`hi/mcp_tools.py`) — reasonable since it's loopback-only (127.0.0.1), never leaves the machine.

## Perception

`term` can look at your current browser tab or take a one-off screenshot and read/describe it — for "what am I looking at" or "what does this error say" type questions. Callable directly whenever a prompt calls for it, no enable step required — an earlier version needed one and it was removed at explicit request, since the friction of a separate permission grant before an obviously-relevant tool wasn't wanted. Still deliberately narrow, not a general "watch what I do" feature:

- **On-demand only, never a background watcher.** Every read is triggered by one specific tool call answering one specific question — there is no interval loop, no history log, nothing running when you're not actively asking. Being reachable without a prior enable step is not the same as running unprompted.
- **Browser observation reads metadata only** — every *running* supported browser's (Safari/Chrome/Brave/Edge) current tab title and URL via AppleScript, never page content. Checks which browsers are actually running, not which one happens to be frontmost — asking through `hi`'s own terminal pane necessarily makes the terminal frontmost, not your browser, so a frontmost-only check would report "no browser" on nearly every real question (a real bug, caught live and fixed). If you want actual page content, that's what `term`'s Playwright tools are for (a separate, already-existing capability).
- **Screen capture never saves the image.** One screenshot — OCR'd on-device via Apple's Vision framework for verbatim text (`read_screen`), or handed to a real vision model for actual scene understanding (`ask_about_screen`, `gemma4:31b-cloud` by default — "what app is this", "describe this diagram", not just what the text says) — the file is deleted immediately either way, verified nothing is left behind after every call.
- **Auto-refuses near anything sensitive, with no opt-out**: a password manager (1Password, Bitwarden, Keychain Access, ...) being the frontmost app refuses everything outright; separately, browser observation skips (rather than reports) any individual running browser whose window looks Private/Incognito, checked per-browser via its own accessibility-level window title (verified live: this title carries a "Private Browsing" marker Safari's *own* AppleScript dictionary doesn't expose, and is readable even when that browser isn't frontmost). This is best-effort, not a guarantee — it can't see inside a browser's actual per-tab incognito state (Chromium-based browsers weren't verified to expose an equivalent marker, and likely don't). The real backstop is that nothing runs unless something explicitly asks for one read, right now.

```text
(term) > what does this error dialog say
(term) > what's on my screen right now
(term) > what tab am I on
```

### Gated Background Awareness

`hi/watchdogs/context_shift.py` is a real, narrow exception to "never a background watcher" above — and deliberately kept separate from `read_screen`/`ask_about_screen`, which are completely unmodified by it. Running `hi --suggest-daemon` also polls the frontmost app's *name* (never content) every 45s purely to notice state changes — an app switch, or the same app staying frontmost a long time — and feeds that into the same confidence-gated, per-day-deduped `Suggestion` pipeline every other background signal here already uses (idle repos, deadlines, LeetCode, applications), not a parallel notification path. E.g. staying on one app for 20+ minutes straight surfaces as one more gated nudge, once a day, same as everything else.

`hi/perception/diff_watch.py` goes a step further — hashing a screenshot every ~2min purely to detect *changed vs. didn't* (the pixels themselves are never OCR'd, never inspected, never stored — only a hash, deleted immediately) — and is a genuinely different privacy posture than everything above, so it's **off by default**, opt in explicitly with `DIFF_WATCH_ENABLED=true` in `~/.hi/.env`. Once enabled, it still runs every single check through the same sensitive-context refusal every other perception tool uses first — a password manager frontmost or a private/incognito window skips that cycle's screenshot entirely. When the screen hashes unchanged for 10+ minutes, that surfaces as one more gated `Suggestion` too ("still stuck, or just reading?").

## Architecture

<details>
<summary>File map</summary>

```text
hi/cli.py                  argparse + tmux launcher, dispatches to a persona or router
hi/personas.py              registry: persona name -> agent, on-turn hook, build_agent
hi/repl.py                   generic input loop + auto-routing loop, shared prompt_toolkit setup;
                                 also checks hi/fast_commands.py before classification, and starts
                                 the haiku-tier keep-alive ping (hi/model_warmup.py)
hi/fast_commands.py            latency fix: zero-network-call exact/narrow-regex matches for
                                 common requests (greetings, "show my tasks", mute/volume/wifi/
                                 quit-app, "add task...") that call the real underlying tool
                                 directly, skipping both classification and agent generation
hi/router.py                  classifies each router-mode turn into (persona, tier)
hi/models.py                   haiku/sonnet/opus tier -> ChatOllama, pulls on demand;
                                 get_tier_model_fast() is a separate reasoning-off cache for
                                 latency-sensitive judgment calls (classification, safety checks)
hi/chat_model.py                per-model reasoning=True probe/cache, shared by
                                 models.py and every persona's own default model
hi/briefing.py                  pre-session tasks/notes/projects -> one suggested action
hi/streaming.py                 streams any agent's response token-by-token,
                                 cancellable mid-stream via Ctrl-J
hi/cancellation.py               shared Ctrl-J interrupt primitive — one
                                 mechanism for shell-wait and generation-streaming alike
hi/tmux_util.py              shared tmux new-session/new-window helper
hi/config.py                 reads ~/.hi/.env: VAULT_PATH + per-persona + tier models
hi/vault.py                   shared Markdown memory tools, backed by the vault
hi/frontmatter.py              shared YAML-subset frontmatter parse/dump, used by
                                 vault.py and capture/schema.py alike
hi/capture/schema.py            Task/Event dataclasses <-> frontmatter mapping
hi/capture/store.py             one Markdown file per task/event under
                                 <VAULT_PATH>/hi/tasks/, + one-time legacy
                                 todo.md migration
hi/capture/ambient.py            classifies raw text into a Task or Event
                                 (haiku tier) and saves it via store.py
hi/capture/inbox.py              untriaged raw captures from the global hotkey
hi/capture/triage.py             classifies inbox items into real tasks/events,
                                 run once at the start of every `hi` session
hi/capture/hotkey.py             standalone global-hotkey daemon (`hi --capture-daemon`)
hi/memory_graph.py            shared grounding graph: select notes -> load -> agent
                                 (note-selection call uses HumanMessage, not SystemMessage —
                                 the latter got an empty done_reason='load' response from the
                                 cloud model every single time, silently making relevant_notes/
                                 relevant_logs always empty; hi/agents/docs/vault_rag.py had the
                                 identical bug, fixed the same way — both live-verified after)
hi/tree_cache.py               `tree -L 4` snapshot of the vault, for grounding
hi/model_warmup.py             background warm-up + retry around Ollama Cloud's
                                 occasional empty done_reason='load' response;
                                 start_keepalive() periodically pings the always-in-use
                                 haiku model so it doesn't go cold between user turns
hi/voice.py                     Ctrl-V mic capture + faster-whisper transcription
hi/tts.py                       local TTS via macOS `say`, sentence-chunked as a
                                 streamed response arrives, with barge-in support
hi/wake.py                      standalone wake-word daemon (`hi --wake-daemon`):
                                 openWakeWord "Hey Jarvis" -> voice.py transcription ->
                                 router.py classify() -> streaming.py + tts.py
hi/mcp_tools.py                 MCP client layer: configured servers -> sync-callable tools
                                 (reads hi.config's values fresh per call, not snapshotted at
                                 import, so mcp_install.py's writes take effect without a restart)
hi/env_file.py                  shared ~/.hi/.env writer (write_env_var) — used by
                                 mcp_install.py and hi/ipc/server.py's POST /config alike
hi/mcp_install.py              conversational MCP server setup (butler): browse the known
                                 catalog (playwright/github/obsidian), configure one by writing
                                 its credential into ~/.hi/.env instead of hand-editing it
hi/widget_store.py              MCP-UI widget recall (docs): persists every widget
                                 agui_adapter.py detects, recall_widget() re-serves one in the
                                 same shape so it re-renders via the existing CUSTOM passthrough
hi/watchdogs/idle_repos.py       flags known projects idle N+ days with open tasks,
                                 surfaced in the daily briefing
hi/watchdogs/dev_servers.py      on-demand dev-server health check (`term` tool)
hi/watchdogs/context_shift.py    polls frontmost-app state every 45s (name only,
                                 never content) -> gated Suggestion via suggest/engine.py
hi/tracking/deadlines.py         vault-wide due:/when: aggregation (`term` tool)
hi/tracking/leetcode.py           daily problem picker + attempt log + streak/topic stats
hi/tracking/applications.py       job/internship application tracker + follow-up nudges
hi/tracking/team_ops.py           task ownership + team status drafts + deadline pings
hi/tracking/pipeline.py           generic named-pipeline tracker (custom stages, any
                                 recruitment/event-shaped tracking)
hi/context/weekday.py             optional per-weekday vault note, read by the arbiter
hi/synthesis/arbiter.py           "what should I work on" — one deterministic
                                 recommendation + rationale, never a ranked list;
                                 what_next_smart() opt-in narrative variant;
                                 exclude_ids support for multi-turn negotiation
hi/synthesis/retro.py             weekly retro note generation (tasks/git/deadlines/
                                 LeetCode), auto-runs on Sunday; generate_retro_smart()
                                 opt-in narrative reflection appended on top
hi/synthesis/reflection.py        weekly pass over conversation logs proposing durable
                                 preferences, rides along with the Sunday retro trigger
hi/synthesis/longcontext.py       synthesize_vault(): reads the ENTIRE vault (not a
                                 relevance-selected subset) for "summarize/find
                                 patterns across everything" questions
hi/synthesis/negotiation.py       multi-turn "no, something else" pushback detection
                                 for the arbiter — session-scoped, not a new daemon
hi/orchestrator/complexity.py      one haiku-tier call extending classify() with a
                                 plan/no-plan signal — supersedes the old planner.py
                                 heuristic (retired) rather than running both
hi/orchestrator/planner.py         opus-tier call decomposing a complex turn into a
                                 real task DAG (ids, personas/tiers, tool_scope,
                                 depends_on) — JSON, with cycle detection/breaking
hi/orchestrator/subagent.py        builds one scoped, stateless agent per DAG task —
                                 least-privilege tool subset, not a persona's full list;
                                 also holds Phase 20's ARCHETYPES (Researcher/Coder/
                                 Reviewer/Fixer) — a role-framing overlay on any
                                 persona's own prompt, orthogonal to tool access
hi/orchestrator/graph.py           the DAG executor: a real LangGraph StateGraph (one
                                 node per task, edges per depends_on) so independent
                                 tasks run concurrently under .ainvoke(), bounded by
                                 an asyncio.Semaphore; threads each task's real
                                 upstream results into its own prompt, not just order;
                                 also creates/tears down a per-run scratch directory
                                 (~/.hi/scratch/<run_id>/, Phase 20) and pushes
                                 DAGEvent milestones to an optional queue two
                                 different consumers drain (Phase 18's agui_adapter.py,
                                 Phase 19's repl.py status line) — see latest_run_trace()
hi/orchestrator/budget.py          Phase 20's user-settable quick/thorough budget
                                 (REPL commands: budget / budget quick / budget
                                 thorough) — caps planner.py's task count and
                                 suggests a default tier; a soft steer, not a hard rule
hi/orchestrator/reviewer.py        Phase 20's Reviewer-verifies-Coder check: one
                                 haiku-tier call flags a destructive shell command's
                                 own concerning details before term.py's confirm gate
                                 ever shows it to a human/pending-approval queue
hi/orchestrator/blackboard.py      LangGraph's own AsyncSqliteSaver checkpointer —
                                 an orchestrated run's state survives a crash mid-DAG
hi/orchestrator/aggregator.py      synthesizes one final answer from a completed
                                 DAG's per-task results
hi/orchestrator/pending_actions.py  in-process queue for destructive actions an
                                 orchestrated subagent needs human approval for —
                                 async-safe (threading.Event), never input();
                                 resolution_of() tracks the approve/deny outcome
                                 separately from _pending's own pop timing, so a
                                 concurrent poller (agui_adapter.py) can't race it
hi/orchestrator/pending_http.py    shared /pending route logic used by both
                                 hi/ipc/server.py and pending_server.py below
hi/orchestrator/pending_server.py  dedicated HTTP server (port 8766) for the
                                 pending queue, started with the terminal REPL —
                                 one of two processes an orchestrated run can now
                                 occur in (hi/ipc/server.py's /query is the other,
                                 since Phase 18)
hi/agui_adapter.py                 Phase 18: translates a persona turn or an
                                 orchestrated DAG run into AG-UI's typed SSE event
                                 stream (ag-ui-protocol SDK) for hi/ipc/server.py's
                                 /query — real RUN_*/TEXT_MESSAGE_*/TOOL_CALL_*/
                                 SUBAGENT_* events, not a bespoke wire format;
                                 Phase 20: also emits CUSTOM pending_action/
                                 pending_action_resolved events for the voice
                                 companion's inline approve/deny cards, and saves
                                 every detected MCP-UI widget via widget_store.py
hi/suggest/engine.py              continuous background suggestion loop with
                                 confidence gating + per-day dedup (`hi --suggest-daemon`);
                                 optional SMART_SUGGESTIONS_ENABLED model-judgment pass
hi/action_tiers.py                shared destructive-action confirm gate, reused
                                 across personas (not just term's shell commands)
hi/perception/privacy.py          shared best-effort sensitive-context refusal for
                                 browser/screen perception (no separate enable step)
hi/perception/browser.py          on-demand current-tab (title/URL only) read via AppleScript
hi/perception/screen.py           on-demand screenshot -> on-device Vision OCR -> text,
                                 image discarded immediately, never saved
hi/perception/vision.py           on-demand screenshot -> real vision model (gemma4:31b-cloud)
                                 for scene understanding, not just OCR text; same discipline
hi/perception/diff_watch.py       opt-in (DIFF_WATCH_ENABLED) screenshot-hash change
                                 detector, ~2min interval -> gated Suggestion; never OCR'd,
                                 never stored, gated by privacy.py first, same as every
                                 other perception tool
hi/note_preview.py                shared content-preview generator for vault grounding
                                 (used by both memory_graph.py and vault_rag.py)
hi/browser.py                     open_url_in_browser — a real tab in the user's actual
                                 default browser, not Playwright's automation instance

hi/agents/butler/  (butler.py + todo.py + mac_control.py)          the `butler` persona
hi/agents/docs/    (docs.py + vault_rag.py)                         the `docs` persona
hi/agents/web/     (web.py)                                          the `web` persona
hi/agents/term/    (term.py + shell_pane.py + danger.py +             the `term` persona:
                    dev_flow_tool.py + people.py + resume.py +        shell + memory + people +
                    files.py + save_project.py +                     dev flows + pane splitting +
                    tmux_control.py)                                  resume-context + real
                                                                       project file access/edits +
                                                                       real coding-agent loop + MCP
```

Every persona module exposes both a `model`/`agent` pair built at import time (used by `--flag` launches) and a `build_agent(model)` factory (used by the router to build the same persona bound to a different, tier-selected model) — the direct-flag path is unaffected by the router's dynamic model selection.

</details>

## By the Numbers

| | |
|---|---|
| Personas | 4 dedicated + 1 auto-router |
| Built-in tools across all personas | 74 |
| + Playwright MCP tools (`term`, on by default) | 24 more |
| Python source | 8,168 lines across 89 files |
| Model tiers | 3 (haiku / sonnet / opus) |
| Direct dependencies | 12 |
| Built | July – August 2026 |

*(counted directly from the source tree and tool registries, not estimated)*

## Voice Companion (native macOS app)

A separate native shell in [voice_companion/](voice_companion/) — a docked, hover-activated `NSPanel` that talks voice in, gets a real answer from the exact same router-mode backend this README describes (persona/tier classification, per-persona memory, every tool), and speaks back a short summary rather than reading a full answer verbatim. Swift/AppKit/SwiftUI, not Python; a real, compiling, launchable first pass — see [voice_companion/README.md](voice_companion/README.md) for what's live-verified versus what still needs an interactive first run (permission prompts a human has to click through) to confirm end to end.

## Further Documentation

- [docs/assistants.md](docs/assistants.md) — terminal interface specification
- [CLAUDE.md](CLAUDE.md) — memory system implementation notes
- [docs/TODO.md](docs/TODO.md) — implementation progress
- [voice_companion/README.md](voice_companion/README.md) — native macOS voice companion app
