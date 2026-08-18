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

---

## Phase 9 – `term` Agent + Ctrl-V Speech-to-Text

- [x] New `term` persona (`hi/agents/term/`): turns natural language into
      real shell commands and runs them *visibly* in the user's left tmux
      pane via `send-keys`/`capture-pane` (`shell_pane.py`), rather than
      invisibly in its own process — the only persona that talks to a
      sibling pane
- [x] Output capture uses a start+end marker pair and extracts by text
      position, not line-count diffing — a long command wraps across
      pane-width lines, which shifts line indices unpredictably; markers
      found by string position are immune to that
- [x] `term` is the only persona with real multi-turn session memory (a
      small `_StatefulAgent` wrapper local to `term.py`) so it can answer
      a follow-up like "the first file" from a previous command's output,
      or run a new, more targeted command informed by that context —
      every other persona is still stateless per turn by design
- [x] `hi/agents/term/danger.py`: heuristic-flagged destructive commands
      (`rm`, `mv`, `sudo`, `chmod`, force-push, `kill`, redirection, ...)
      pause for a y/n confirmation before running; read-only commands run
      immediately
- [x] `hi/repl.py` rewritten on `prompt_toolkit` (replacing the
      readline-based Ctrl-L hack from Phase 8) so key bindings can run
      real Python callbacks, not just readline's fixed named functions —
      needed for Ctrl-V, and unifies Ctrl-L across GNU readline/libedit
      for free
- [x] `hi/voice.py`: Ctrl-V records from the mic until the user falls
      silent (RMS-threshold based, capped at 20s), transcribes with a
      lazily-loaded `faster-whisper` model (`WHISPER_MODEL` in
      `~/.hi/.env`, default `base.en`), and auto-submits the transcript —
      verified against a real synthetic speech sample (macOS `say` ->
      `afconvert` -> transcribe), exact match

---

## Phase 10 – Per-Person Notes ("who do I know")

- [x] `hi/agents/code/people.py`: `add_person_info`/`get_person_info`/
      `delete_person`/`list_people` tools backed by one note per person at
      `<VAULT_PATH>/hi/knowledge/people/*.md` — fuzzy name matching
      (case/spacing-insensitive, unambiguous partial match) so "dean"
      finds `Dean_Haidt.md`
- [x] Consolidated the pre-existing `hi/knowledge/personas/harshith.md`
      (from the Phase 1 migration) into this same `people/` directory
      alongside the real `Dean_Haidt.md` note that had already been
      created through actual use, rather than leaving two similar
      locations to check
- [x] `docs`'s vault-wide search needed no code changes to start reading
      person notes (nothing in `hi/knowledge/` is excluded from its
      scope) — but its note-selection prompt only judged relevance from
      literal keyword overlap with filenames, which missed a folder-level
      question like "who do I know" entirely; added guidance that a
      folder name is itself a relevance signal for aggregate questions,
      verified fixed without regressing the existing Docker-note-citation
      and no-match-found cases
- [x] Suppressed langchain_ollama's `done_reason='load'` warning (harmless
      once retried, but printed ahead of every reply since nothing in this
      project configures its own logging) and added `keep_alive="30m"` to
      every persona's model, to cut down how often Ollama Cloud unloads a
      model between turns in the first place

---

## Phase 11 – Redesign: Auto-Router, Streaming, Tiered Models, Butler Expansion

- [x] Real token-by-token streaming for every persona (`hi/streaming.py`).
      Required replacing `code`/`docs`'s hand-written `run_agent(state,
      config)` node — which called `note_agent.invoke(...)` and only ever
      surfaced whole-message chunks, verified directly — with embedding
      `note_agent` as a literal subgraph node
      (`graph_builder.add_node("agent", note_agent)`) and streaming with
      `stream_mode=["messages","values"], subgraphs=True`, which restores
      true token-level granularity from the inner agent
- [x] New `hi` (no flag) auto-routing mode (`hi/router.py` +
      `run_router_repl()` in `hi/repl.py`): each turn is classified into a
      (persona, tier) pair and routed automatically; the prompt starts as
      `(hi) >` and updates to show whichever persona just handled the
      turn. `--code`/`--butler`/etc. still work unchanged as an explicit
      override (`hi/cli.py`)
- [x] Claude-tier-style model selection (`hi/models.py`,
      `HAIKU_MODEL`/`SONNET_MODEL`/`OPUS_MODEL` in `~/.hi/.env`) — cloud
      models only: measured a local 8B model at 30-85s per call on this
      machine (no GPU acceleration) versus ~2-16s for the cloud haiku
      default, and the haiku tier runs on every single router turn.
      `ensure_pulled()` runs `ollama pull` with live progress if a
      configured tier model isn't already available. Found and fixed a
      real quirk along the way: `gpt-oss:20b-cloud` (the haiku default)
      returns empty content for a system-message-only prompt but works
      fine with a human-message — different from `gpt-oss:120b-cloud`
      elsewhere in this codebase, and not the transient issue
      `invoke_with_retry` otherwise handles
- [x] Each persona module refactored to expose `build_agent(model)`
      alongside its existing fixed default instance, so the router can
      build a persona bound to a tier-selected model without touching the
      stable warm-up/keep-alive behavior of the direct-flag path
- [x] Also fixed in passing: `WEB_MODEL` was set to a model name (`'web'`)
      that doesn't exist in this Ollama installation — `hi --web` was
      fully broken before this session, unrelated to streaming; changed
      to `gpt-oss:20b-cloud`
- [x] Known, expected limitation of per-turn independent classification
      (as specified): a short follow-up with no persona-specific keywords
      (e.g. "how many did you find" right after a `term` turn) can route
      to the wrong persona, since the router has no awareness of routing
      history. `term`'s own session memory is unaffected when this
      happens — verified live, it correctly recalled context once routed
      back to it later in the same session
- [x] `hi/agents/butler/mac_control.py`: volume (set/mute/unmute), Wi-Fi
      toggle, Do Not Disturb (best-effort — modern macOS has no stable
      CLI toggle since Monterey+, so this runs a user-created
      Shortcuts.app automation and says so plainly if it's missing),
      screenshot, clipboard read/write, list/quit running apps — all
      verified directly (clipboard round-trip, volume set-and-restore,
      error paths), screenshot blocked in this sandbox by macOS Screen
      Recording permission (expected, not a code issue)
- [x] Ctrl-V no longer auto-submits after transcribing — the text lands
      in the input buffer for the user to review/edit, Enter is manual

---

## Phase 12 – Removed `code`, Merged Into `term`

- [x] `code` persona (`hi/agents/code/`) removed entirely — its
      responsibilities (persistent Markdown memory, per-person notes,
      dev-flow launcher) folded into `term`, so there's one
      general-purpose persona instead of two with overlapping scope
- [x] `dev_flow_tool.py` and `people.py` moved from `hi/agents/code/` to
      `hi/agents/term/` unchanged (no code-specific dependencies)
- [x] `term/term.py` rebuilt: `note_agent` now carries the full tool set
      (shell + notes + people + dev-flow), wrapped in
      `build_memory_graph` (the same grounding `code` had — auto-selects
      relevant `hi/knowledge/` notes and `hi/conversations/` logs before
      every turn) and *then* in `_StatefulAgent` (cross-turn session
      memory) — verified live that all three layers compose correctly
      together: a shell command, a grounded "who do I know" answer, and a
      context-recalled follow-up all worked correctly in one session
- [x] `term_prompt.md` rewritten to merge both personas' guidance (shell
      execution + confirmation gating, memory/notes, people tracking,
      dev-flow launching)
- [x] `hi/personas.py` / `hi/router.py`: removed `code` from `PERSONAS`
      and `PERSONA_DESCRIPTIONS`, expanded term's router description to
      cover its new scope, changed the router's default fallback persona
      from `code` to `term`
- [x] `CODE_MODEL` removed from `hi/config.py` and `~/.hi/.env` (dead
      config); `TERM_MODEL` made explicit in `~/.hi/.env`
- [x] README / `docs/assistants.md` updated throughout — every `--code`/
      `(code) >` reference replaced with `--term`/`(term) >`, with a note
      explaining the merge where it's first mentioned

---

## Phase 13 – Multi-Step Robustness, CWD Awareness, Agent-Creatable Dev
Flows, Clarifying Questions, Daily Briefing

- [x] Confirmed live that LangChain's `create_agent` ReAct loop already
      chains multiple tool calls per turn — no new mechanism was needed
      for "commit with a message and push" style multi-part requests.
      What actually broke that test was a real, separate bug (next item)
- [x] `hi/agents/term/shell_pane.py`: fixed two "command doesn't behave
      like a simple synchronous foreground process" bugs sharing one root
      cause — (1) a command that opens a pager (`git diff`/`log`) blocks
      forever since nothing can send it a keystroke to exit; fixed with a
      one-off `PAGER=cat GIT_PAGER=cat` env prefix. Verified live: this
      had stalled a real turn for 2+ minutes before the fix, down to
      0.24s after. (2) heredocs/multi-line commands break when typed as
      one compound `;`-joined line (everything after `<<EOF` on that
      "line" gets swallowed into the heredoc body) — fixed by writing
      multi-line commands to a temp script and running that instead,
      verified against the TODO's own garbled-heredoc example
- [x] `HI_LAUNCH_CWD` env var (`hi/cli.py`, threaded the same way
      `HI_PERSONA_PANE` already is) gives `term` awareness of the
      directory `hi` was launched from, folded into its system prompt —
      shell commands already ran there for free (the left pane's real
      shell inherits cwd naturally), this is about the model's own
      reasoning awareness
- [x] `hi/memory_graph.py`: `hi/knowledge/preferences.md` (already
      existed with real content) is now always loaded into context, not
      just when the relevance-selection step happens to match it —
      verified live it's present even for a fully unrelated question
- [x] `hi/agents/term/dev_flow_tool.py`: new `add_dev_flow` tool saves
      `HI_LAUNCH_CWD` as a new `~/.hi/dev_flows.json` entry — reverses the
      explicit "you cannot create, edit, or add one" restriction written
      into the prompt during Phase 3, now that it was explicitly asked
      for. `dev_flows.json` stays hand-editable either way
- [x] `term_prompt.md`: added guidance to ask a short clarifying question
      for genuinely ambiguous requests instead of guessing, relying on
      `_StatefulAgent`'s existing cross-turn memory to resolve the answer
      next turn — verified live with "delete the old branches" (asked
      which repo/criteria rather than guessing) and confirmed the
      follow-up turn correctly recalled the original request
- [x] `hi/briefing.py` (new): gathers pending tasks
      (`hi.agents.butler.todo.pending_tasks_greeting`, already existed),
      most-recently-edited vault note, and most-recently-opened project
      via plain filesystem mtime lookups (no LLM needed for gathering),
      then one haiku-tier call synthesizes a one-line actionable
      suggestion — shown once at the start of auto-routing mode
      specifically (`run_router_repl`, not every `--flag` launch, since
      "before starting the session" describes the general entry point).
      Found during implementation that `~/Dev` is actually a *different*
      Obsidian vault on this machine (its own `.obsidian`/`.stfolder`
      markers) — real project directories live in `~/Dev/Projects/`,
      confirmed directly before using that path instead of the literal
      one named in the TODO item
- [x] `hi/repl.py`: a bare affirmative (`y`/`yes`/etc.) as the first
      router-mode input submits the briefing's stored suggested action
      through the normal classify → route → stream pipeline instead of
      trying to route the literal word "yes" — verified end-to-end with
      scripted input through the real pipeline (not mocked past the
      classify step)

---

## Phase 14 – Ctrl-J Wait-Interrupt + tmux add_pane

- [x] Verified directly (not assumed) that Ctrl-J (raw byte `\x0a`,
      linefeed) is genuinely distinguishable from Enter (`\r`, carriage
      return) at the terminal level, via `prompt_toolkit`'s pipe-input
      test harness — a `c-j` binding fires on the raw byte without being
      swallowed by the default accept-line behavior
- [x] Realized a `prompt_toolkit` `KeyBindings` entry (the Ctrl-L/Ctrl-V
      mechanism, `hi/repl.py`) categorically cannot handle this: the
      "stuck" moment is inside `run_in_left_pane`'s synchronous polling
      loop, entirely outside `prompt_toolkit`'s event loop, which isn't
      reading input at all during that window
- [x] `hi/agents/term/shell_pane.py`: `_check_interrupt` replaces the
      polling loop's `time.sleep(0.2)` — puts the terminal in cbreak mode
      just for a non-blocking `select.select(...)` check, restored
      immediately via `finally` every iteration, falling back to a plain
      sleep when `sys.stdin.isatty()` is false. No background thread
      needed (the original instinct) — the loop already had a sleep to
      replace. Verified live: the non-tty fallback behaves identically to
      a plain sleep (this sandbox has no real TTY), and no regression in
      the normal-completion or genuine-timeout paths
- [x] Real Ctrl-J-press verification needs an actual terminal with a real
      TTY, which this sandbox doesn't have — noted plainly rather than
      claimed, same caveat as the voice-input work earlier
- [x] `hi/agents/term/tmux_control.py` (new): `add_pane(command, split)`
      splits a new pane in the *current* window (not a new window,
      matching "existing environment" in the TODO item) via
      `hi.tmux_util.run_tmux_raw`, reusing `shell_pane.py`'s window/pane
      resolution (`left_pane_id`, made public — second consumer now).
      Verified live in an isolated tmux session: pane count increases,
      the command actually runs in the new pane — both directly and
      through the real agent via natural language ("split a new pane and
      run: ...")
- [x] `term_prompt.md`: guidance to prefer `add_pane` over
      `run_shell_command` for anything expected to run forever (dev
      servers, log tails), and to treat a Ctrl-J-interrupted result as
      "still running," not a failure

---

## Phase 15 – Last-Modified Fix, Long-Running-Process Fix, MCP Integration

- [x] `hi/briefing.py`: `_last_edited_note()` excluded `hi/` (the
      assistant's own `conversations/`/`knowledge/`/`todo.md`) from its
      scan — `hi/conversations/` gets touched on every turn of every
      persona, so without this it always won "most recently edited" and
      the briefing never actually reflected a note the user wrote.
      Verified live: now correctly returns a real note instead
- [x] `hi/agents/term/danger.py`: new `looks_long_running()` heuristic
      (same shape as the existing `looks_destructive`) — `run_shell_command`
      now auto-redirects matching commands to their own pane instead of
      relying on prompt guidance the model wasn't reliably following.
      Unit-tested against 19 real/non-matching commands, all correct
- [x] Found and fixed a second real bug while verifying the redirect live:
      `add_pane`'s split pane had no keep-alive fallback, so a command
      that fails fast (verified: `npm run dev` outside a JS project)
      closed its own pane before its error was visible — same bug
      category already fixed once for `dev_flow_tool.py`'s `_keep_alive`
      earlier this session, so that helper was promoted to a shared
      `hi.tmux_util.keep_alive` and reused here instead of duplicated
- [x] Researched rather than assumed which MCP servers actually exist and
      what they need before building anything: `langchain-mcp-adapters`
      is the standard LangChain/LangGraph MCP client; official servers
      exist for GitHub (`github/github-mcp-server`, local via Docker + a
      personal access token) and Playwright (`microsoft/playwright-mcp`,
      via `npx`, no credentials); Obsidian needs the community "Local
      REST API" plugin installed *inside* Obsidian (confirmed not
      currently installed in this vault) plus its API key; no official
      Amazon price-tracking server exists, only paid third-party scrapers
      — asked the user directly which to use rather than guess, and they
      chose to skip it for now; evaluated existing macOS-control MCP
      servers and found none better than butler's existing, tested
      osascript tools, so didn't replace them
- [x] Verified directly (not assumed) that MCP tools are async-only —
      calling `.invoke()` on one raises `NotImplementedError` — before
      building anything on top of that assumption. `hi/mcp_tools.py`
      (new) bridges each tool with one `asyncio.run()` call per
      invocation rather than converting the whole (otherwise entirely
      synchronous) agent execution path to async
- [x] Servers are included in the client config conditionally — Playwright
      always (just checks `npx` is on `PATH`), GitHub/Obsidian only when
      their credential is set in `~/.hi/.env` (both added as commented-out
      placeholders with setup instructions) — gracefully absent rather
      than crashing when not configured. A server that fails to connect
      is caught, logged, and skipped without taking any other server or
      the persona down with it
- [x] Wired into `term`'s tool list (cached — only the first `build_agent`
      call in a process actually connects). Verified end-to-end through
      the real agent via natural language: "go to https://example.com and
      tell me the exact page title" correctly navigated a real browser and
      returned the real title, not a guess — installing a usable Chromium
      for the Playwright MCP server along the way required a genuine
      system-level install (`npx playwright install chrome` downloaded
      real Google Chrome to `/Applications`, not just a Playwright-managed
      cache), flagged clearly rather than treated as a routine dependency
      install
- [x] Full regression check with the ~24 new Playwright tools added to
      term's tool list: shell commands, vault grounding + people notes,
      and the long-running-process redirect all still verified working
      together in the same session

---

## Phase 16 – Real GitHub/Obsidian Credentials, `uv tool` Resync, Obsidian Cert Fix

- [x] `uv tool upgrade hi` again — the installed `hi` command's separate
      venv didn't have `langchain-mcp-adapters` after `uv add`, same class
      of issue as every previous dependency addition this session
- [x] User provided real credentials in `~/.hi/.env` — confirmed GitHub
      and Obsidian both now appear in `_server_configs()`
- [x] GitHub MCP still fails — Docker (Rancher Desktop) isn't currently
      running. Confirmed the failure is graceful (logged warning, other
      servers unaffected, no crash) rather than trying to start a GUI VM
      app on the user's behalf, which felt like a bigger, more invasive
      action than appropriate to take autonomously
- [x] Obsidian MCP failed with `CERTIFICATE_VERIFY_FAILED: self-signed
      certificate` — diagnosed with the full exception (not the generic
      caught-and-logged summary) rather than guessing, confirmed via
      direct `curl -k` that the Local REST API plugin itself was actually
      reachable (Obsidian was running) before concluding it was a cert
      issue specifically. Fixed with a custom `httpx_client_factory`
      (`verify=False`) scoped to just the Obsidian connection — a
      reasonable trade-off since it's loopback-only (127.0.0.1), never
      leaves the machine
- [x] Verified fully end-to-end after the fix: 16 real Obsidian tools
      load, a direct `vault_list` call returned the actual real vault
      folder structure, and the full `term` agent correctly listed the
      same real folders via natural language ("list the top-level folders
      in my vault") — Obsidian MCP is no longer best-effort/unverified,
      it's confirmed working
