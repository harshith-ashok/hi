# clauding.md — Make tinyui work like the Claude desktop app

An implementation plan for Claude Code. Read `CLAUDE.md` first: its principles (vault is the only storage, nothing
happens at import, read `config.X` live, every outside dependency can fail, tool calls are never retried) apply to
every task here.

Revised 2026-11-22 after a read of the code. Paths and names below were checked against the tree at commit `57b0f9c`.

## How to work through this file

- Do the phases in order; inside a phase, do the tasks in order. Phase 0 is a prerequisite for most of the rest.
- One task per commit, on a feature branch. Tick the task's checkbox in this file in the same commit.
- Before each commit: `uv run pytest` and `cd tinyui && npx vue-tsc --noEmit -p tsconfig.app.json`. Add a test next to
  every backend behaviour you change (`tests/unit/`, `tmp_vault` fixture, no network, no real vault).
- Each task ends with **Done when**. If a step turns out to be wrong for the code you find, stop and update this file
  rather than forcing the step.
- Every task has a GitHub issue, in task order: 0.1 is #7 and 6.1 is #32 (0.1–0.4 = #7–#10, 1.1–1.5 = #11–#15,
  2.1–2.3 = #16–#18, 3.1–3.4 = #19–#22, 4.1–4.6 = #23–#28, 5.1–5.3 = #29–#31, 6.1 = #32). Put `Closes #N` in the
  task's commit.
- Do not add a database, an index or embeddings. Do not add a dependency without saying why in the commit message.

## What already exists (do not rebuild)

| Feature                                                                                             | Where                                                                                 |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Chat list: search by title **and content** with snippets, date groups, pin, rename, archive, delete | `AppSidebar.vue`, `useSessions.ts`, `GET /sessions?q=` → `transcript.search_sessions` |
| Streaming, thinking blocks, tool rows, run timeline, stop                                           | `useChat.ts`, `ThinkingBlock.vue`, `ToolCall.vue`, `RunTimeline.vue`                  |
| Copy and "ask again" on the last reply                                                              | `TurnView.vue`                                                                        |
| Model size picker (Auto / Fast / Balanced / Deep)                                                   | `Composer.vue`, `/query` `tier`                                                       |
| Attachments, drag and drop, paste                                                                   | `attachments.ts`, `hi/attachments.py`                                                 |
| Code blocks, Mermaid, 3D scenes                                                                     | `MarkdownContent.vue`, `lib/markdown.ts`                                              |
| HTML preview in a side pane (sandboxed iframe)                                                      | `PreviewPane.vue`, `composables/usePreview.ts`                                        |
| `/skill-name` with autocomplete; built-in names reserved                                            | `hi/memory/skills.py` (`BUILTIN_COMMANDS`, `expand_slash`), `GET /skills`             |
| Tab-to-accept suggestions                                                                           | `Composer.vue`, `POST /suggest`, `hi/server/suggest.py`                               |
| Memory page with forget                                                                             | `MemoryView.vue`, `GET /memory`, `POST /memory/forget`                                |
| Tool approvals                                                                                      | `ApprovalBar.vue`, `GET /pending`                                                     |
| Quick prompt outside the main window                                                                | the menu bar island (`origin: "island"`, `hi/automation/profiles.py`)                 |
| Per-origin writing style                                                                            | `Profile.style` in `hi/automation/profiles.py`, appended in `hi/server/turn.py`       |

## How a turn works today (the facts the plan builds on)

- `POST /query` → `turn.stream_query_as_agui` (`hi/server/turn.py`). A new LangGraph `thread_id` is made per turn; the
  conversation is **not** in a checkpointer. History comes from `transcript.history(session=...)`.
- `transcript.history` (`hi/memory/transcript.py`) returns the last `HISTORY_TURNS = 8` exchanges, each question
  clipped to `ASK_CHARS = 1500` and each answer to `ANSWER_CHARS = 2000`.
- Transcript entries are JSON lines in day files, `{time, persona, tier, plan, seconds, ask, tools, answer, error,
origin, session, visual}`. **There is no turn id.**
- After a turn, `records.record_turn` (`hi/memory/records.py`) fans out to the sinks `_transcript`, `_conversation`,
  `_journal`, `_extraction`, `_session`.
- `build_chat_model` (`hi/llm/providers.py`) constructs `ChatOllama` with **no `num_ctx`**, so Ollama's server default
  context length applies.

Two consequences matter for a Claude-like app:

1. A long chat silently loses context: fixed turn count, clipped answers, and an unknown (possibly small) model
   context window that Ollama truncates without telling anyone.
2. Iterating on an artifact cannot work: a 10 KB HTML page is clipped to 2000 characters in the history, so "make the
   button blue" has no page to edit.

Phase 0 fixes both before anything is built on top.

---

## Phase 0 — Context foundations

### - [x] 0.1 Set the model context window explicitly

- Add `CONTEXT_TOKENS` to `hi/config.py` (default `16384`, which is also the ceiling for the tailscale box; overridable in the settings like the other model settings).
  Pass `num_ctx=config.CONTEXT_TOKENS` from `build_chat_model`, unless the caller passes its own.
- Show the value on the Status view next to the models.
- Note in `docs/architecture.md` that a larger window costs memory on the Ollama host (local or tailscale).
- **Test:** `build_chat_model` passes `num_ctx`; a caller's explicit value wins.
- **Done when:** every chat model is built with a known window, visible in the UI.

### - [x] 0.2 Give every turn an id and a parent

- In `transcript.record_turn`, add `id` (`uuid4().hex[:12]`) and `parent` (the id of the session's current head, or
  `""`). Return the new id; thread it back through `records.TurnRecord` so `turn.py` can emit it.
- Add `head` (turn id) to the session frontmatter in `hi/memory/sessions.py`; `_session` sink sets it.
- Entries written before this change have no id: when reading, give them a stable synthetic id
  (`f"{time}-{index}"`) and treat them as a straight chain (each one's parent is the previous entry of the session).
- `transcript.session_path(session) -> list[dict]`: walk from `head` back through `parent` and return the turns
  oldest first. `session_turns` and `history` use this path instead of "every entry with this session".
- `turn.py` emits `CustomEvent(name="turn", value={"id": ..., "parent": ...})` after the record is written, and
  `GET /sessions/{id}` returns `id`/`parent` per turn. Add both to `StoredTurn` in `useChat.ts`.
- **Tests:** ids and parents are written; legacy entries read as a chain; `session_path` follows `head`.
- **Done when:** behaviour is unchanged for the user, and every turn in a session has an id the UI knows.

### - [x] 0.3 Budget history by tokens, not by turn count

- Replace the fixed count with a budget: `history_budget = CONTEXT_TOKENS - RESERVED_FOR_ANSWER (4096) -
estimate(system prompt + this message + attached context)`. Use a plain estimate (`len(text) // 3`, a little
  generous for code); do not add a tokenizer dependency.
- Fill from the newest turn backwards along `session_path`. Clip only a turn that alone exceeds a quarter of the
  budget. Keep `ASK_CHARS`/`ANSWER_CHARS` only as that per-turn ceiling.
- Return how many turns were left out. `turn.py` emits `CustomEvent(name="context_window", value={"used": n, "limit": m,
"dropped_turns": k})`.
- **Tests:** a short chat is sent whole; a long one drops the oldest turns first; one huge answer is clipped, not
  dropped.
- **Done when:** a long chat keeps as much as fits, and the UI is told what was left out.

### - [x] 0.4 Show context use, and summarise what fell out

- Composer: a small ring next to the model picker showing `used / limit`, with a tooltip ("12 earlier messages are
  not in context"). Hidden while under 50%.
- When turns are dropped, keep a running summary of them in the session file body (`<vault>/hi/sessions/<id>.md`,
  below the frontmatter) and put it at the top of the history as "Summary of earlier messages". Write the summary in
  a background job (`hi/core/jobs`) with the fast tier after the turn ends, only when the set of dropped turns grew.
  If the summary call fails, record it in `hi/core/health.py` and carry on without it.
- **Tests:** the summary is written to the session file and read back into history; a failed summary call leaves the
  turn working.
- **Done when:** a 50-message chat still knows what was decided in message 3.

---

## Phase 1 — The chat loop

### - [x] 1.1 Keyboard shortcuts

- `tinyui/src/composables/useShortcuts.ts`: one `keydown` listener on `window`, one table of `{keys, label, run}`.
  Use `metaKey` on macOS, `ctrlKey` elsewhere.
- Shortcuts: `Mod+K` focus chat search, `Mod+Shift+O` new chat, `Mod+B` toggle sidebar, `Mod+,` settings,
  `Mod+Shift+C` copy last reply, `Esc` stop (exists), `Mod+/` open a sheet listing the shortcuts and the `/` commands.
- Do not fire while an IME composition is active or when focus is in an input other than the composer (except `Esc`
  and `Mod+K`).
- **Done when:** every shortcut works and the help sheet lists them all.

### - [x] 1.2 Edit a message and regenerate any reply (with versions)

Built on 0.2. Nothing is deleted: a new attempt is a sibling in the turn tree.

- `/query` accepts `parent` (a turn id). When given, the new turn's parent is that id instead of the session head,
  and history is `session_path` up to that parent. The new turn becomes the head.
  - **Edit** turn T = send the edited text with `parent = T.parent`.
  - **Regenerate** turn T = send `T.ask` with `parent = T.parent`.
- `GET /sessions/{id}` returns the active path plus, for each turn, `versions: {index, count, ids}` (siblings sharing
  its parent). `PATCH /sessions/{id}` accepts `head` to switch versions: set the head to the newest leaf under the
  chosen sibling.
- `TurnView.vue`: a pencil on user messages (inline edit, Enter resends, Esc cancels), "ask again" on every reply, and
  a `‹ 2/3 ›` switcher when `count > 1`.
- The conversation log and journal stay append-only (they are a diary, not the context).
- **Tests:** edit creates a sibling; history for the new turn excludes the old branch; switching head changes
  `session_path`; deleting a session still removes every branch.
- **Done when:** you can edit message 2 of 5, get a new answer, and flip back to the original conversation.

### - [x] 1.3 Queue a message while a reply is streaming

- In `ChatView.vue`, Enter while busy stores the message as "queued" (shown greyed above the composer, with an ×) and
  sends it when the reply ends. One queued message at most; a second Enter replaces it.
- **Done when:** typing ahead no longer produces a "still replying" toast.

### - [x] 1.4 Math rendering

- Add KaTeX (`katex` package) to `lib/markdown.ts`: `$…$` inline and `$$…$$` display, rendered before DOMPurify.
  Skip `$` inside code. Render errors show the source, not an exception.
- **Done when:** `$e^{i\pi}+1=0$` renders, and a price like `$5 and $10` does not turn into math (require no space
  after the opening `$` and before the closing one).

### - [ ] 1.5 Reading layout (applied; waiting for a visual check in light and dark at laptop width and 390px)

- Reply column at most 46rem, body text 15px, line height 1.65. User messages in a soft rounded panel aligned right;
  replies plain, no container. Keep the sticky "Latest" button.
- **Done when:** checked by eye in light and dark at a laptop width and at 390px.

---

## Phase 2 — Artifacts

The existing `PreviewPane` becomes a proper artifact panel. Artifacts are files in the vault, versioned, and the model
always sees the latest version in full.

### - [x] 2.1 Store artifacts in the vault

- New `hi/memory/artifacts.py` (memory layer: imports only `core`, `config`, `llm`):
  - `extract(answer) -> list[Artifact]`: fenced blocks with an `artifact` marker on the fence line, e.g.
    ` ```html artifact title="Budget" `. Kinds: `html`, `svg`, `markdown`, `mermaid`, `code` (any other language).
  - `save(session, turn_id, artifact)` writes `<vault>/hi/artifacts/<session>/<slug>/v<N>.<ext>` and
    `<slug>/index.json` (`{title, kind, versions: [{n, turn, time}]}`). The slug is derived from the title; a block
    with the same title in the same session is a new version.
  - `latest(session) -> list[Artifact]` for context.
- Wire it as a records sink (`_artifacts`) after `_transcript`, so the turn id exists.
- `turn.py` emits `CustomEvent(name="artifact", value={slug, title, kind, version})` for each one saved.
- Routes in `hi/server/routes/artifacts.py`: `GET /artifacts/{session}` (index), `GET
/artifacts/{session}/{slug}/{n}` returning **JSON** `{content, kind}`. Never serve artifact HTML as a page on the
  app's origin (same reason as `files.py`); the panel renders it with `srcdoc` in the sandboxed iframe.
- Validate `session` with `sessions.valid_id` and `slug` with `[a-z0-9-]+`.
- **Tests:** extraction (marker required, title optional → "Untitled"), versioning by title, path safety.

### - [x] 2.2 Put the latest artifacts into context

- In `turn.py`, when the session has artifacts, add "Current artifacts" to the context: each latest version in full,
  newest first, within the 0.3 budget (an artifact that does not fit is listed by title with a note to ask for it).
- In the history, replace an artifact block inside an older answer with `[artifact "Budget" v2]` so the same page is
  not sent twice.
- Add to `hi/agents/term/term_prompt.md`: when to make an artifact (a self-contained page, document, diagram or file
  the user will keep or iterate on; not for short snippets), the fence syntax, and "to change an artifact, write the
  whole new version with the same title".
- **Tests:** context contains the latest version only; old answers get the placeholder.
- **Done when:** "make the button blue" on a 10 KB page produces a correct v2.

### - [x] 2.3 The artifact panel

- Rename `usePreview` → `useArtifact` and `PreviewPane.vue` → `ArtifactPanel.vue`. State: `{session, slug, version}`;
  content is fetched from the route.
- Renderers: `html` and `svg` in the sandboxed iframe (`sandbox="allow-scripts allow-forms allow-modals allow-popups"`,
  no `allow-same-origin`); `markdown` with `MarkdownContent`; `mermaid` with `MermaidDiagram`; `code` with `CodeBlock`.
- Header: title, version dropdown, Code/Preview toggle (for html/svg), copy, download (a Blob made in the client),
  close. Keep the existing drag-to-resize and the narrow-screen full-screen layout.
- In the reply, an artifact appears as a compact card (title, kind, version) instead of the raw block; clicking it
  opens the panel. Untagged ` ```html ` blocks keep the existing Preview button.
- Setting "Open artifacts automatically" (default on): the panel opens when an `artifact` event arrives.
- **Done when:** an HTML artifact streams as a card, opens on completion, and v1/v2 can be compared.

---

## Phase 3 — Projects

### - [x] 3.1 Projects as vault folders

- `hi/memory/projects.py`: a project is `<vault>/hi/projects/<slug>/PROJECT.md` (frontmatter `name`, `description`;
  body = instructions) plus any files in that folder.
- A session belongs to at most one project: `project: <slug>` in the session frontmatter (`sessions.update` gains a
  `project` argument).
- Routes `hi/server/routes/projects.py`: `GET/POST /projects`, `GET/PATCH/DELETE /projects/{slug}`,
  `POST /projects/{slug}/files` (reuse the upload handling in `attachments.py`). Deleting a project unassigns its
  sessions; it does not delete them.
- **Tests:** create, rename, assign a session, delete keeps sessions.

### - [x] 3.2 Project context in a turn

- In `turn.py`, when the session has a project, add its instructions and a list of its files (names and sizes, not
  contents) to the context. The agent reads a file with the existing note tools; make sure those tools can read under
  `hi/projects/` (check `hi/agents/term/vault_files.py`).
- **Done when:** a chat in a project follows the project's instructions and can open its files on request.

### - [x] 3.3 Projects in the UI

- Sidebar section "Projects" above the chat list; a project page lists its chats, its instructions (editable) and its
  files (upload, remove). "New chat" from a project page creates the session inside it. Add `'projects'` to
  `View` in `lib/views.ts`.
- **Done when:** a project can be created, given instructions and files, and chatted in, all from tinyui.

### - [x] 3.4 Personal preferences editor

- `knowledge/preferences.md` already goes into the term prompt (`term.py`). Add a text area for it in Settings, with
  `GET/PUT /preferences`.
- **Done when:** editing preferences changes the next reply without a restart.

---

## Phase 4 — Composer and commands

### - [x] 4.1 Built-in `/` commands

- Implement the reserved names client-side: `/new`, `/clear` (new chat), `/help` (shortcut sheet), `/skills` (list),
  `/model <fast|balanced|deep|auto>`, `/tier` (alias), `/config` (Settings). Remove `persona` from
  `BUILTIN_COMMANDS` (decision 2).
- One autocomplete list: commands first, labelled "Command", then skills, labelled "Skill".
- A built-in command never reaches `/query`.
- **Done when:** every listed command works, and `/pdf …` still runs the skill.

### - [x] 4.2 Skills that appear without a reload

- Refetch `GET /skills` each time the composer text becomes `/` (debounced), instead of once on mount.

### - [ ] 4.3 `create_skill` tool

- In `hi/memory/skills.py`: `create_skill(name, description, instructions)`, writing
  `<vault>/skills/<name>/SKILL.md`. Name must match `[a-z0-9-]{2,40}`, must not be a built-in command and must not
  exist (no overwrite; a separate `update_skill` replaces the body and keeps the frontmatter).
- Register it for term in `hi/toolkit.py`. It is a write tool, so it goes through approvals like the other writes.
- Note in the skill-creator docs (not in code): its eval scripts assume Claude Code and subagents and are not supported.
- **Tests:** writes the file, rejects bad and built-in names, refuses to overwrite.

### - [ ] 4.4 `+` menu in the composer

- Replace the paperclip with a `+` menu: Upload files (existing), Add from vault (a note picker over `GET /memory` or
  the vault file list; adds the note as an attachment), Use a skill (inserts `/`), Use a project (assigns the chat).

### - [ ] 4.5 Writing styles

- Add `STYLES` to `hi/automation/profiles.py`: `normal` (empty), `concise`, `explanatory`, `formal`, each a short
  instruction block. User styles: `<vault>/hi/styles/*.md` (frontmatter `name`; body = instruction).
- `/query` accepts `style`; `turn.py` appends it after `prof.style`. `GET /styles` lists them.
- Selector next to the model picker; remembered per browser.
- **Tests:** a built-in style and a vault style both reach the agent's input; an unknown style is ignored.

### - [ ] 4.6 Thinking toggle

- First read how reasoning is chosen (`hi/llm/reasoning.py`, `registry._resolve`, `Profile.reasoning`, the agent
  builders). Then add a `think: bool | null` option to `/query` (null = current behaviour) and a "Think" toggle in the
  composer. On a model without reasoning support the toggle is disabled with a tooltip; the reasoning probe already
  knows which models support it.
- **Done when:** Think off gives no thinking block on a reasoning model, and the setting survives a reload.

---

## Phase 5 — Privacy, export, notifications

### - [ ] 5.1 Incognito chats

- Session flag `incognito: true`. `records.py` skips `_conversation`, `_journal` and `_extraction` for such turns
  (the transcript is still written, because history needs it).
- Incognito sessions are hidden from the sidebar and deleted (session file, transcript entries, artifacts) when the
  user starts or opens another chat, and by a startup sweep in `hi/startup.py` for any older than one day.
- A ghost icon in the chat header starts one; the header says "Incognito: not saved or remembered".
- **Tests:** no memory extraction, no conversation log, sweep deletes everything for the session.

### - [ ] 5.2 Export a chat

- `GET /sessions/{id}/export` returns Markdown of the active path (questions, answers, artifact links). A header menu
  item downloads it.

### - [ ] 5.3 Notifications

- Browser Notification API: when a reply finishes or an approval is waiting while the tab is hidden. Ask permission
  on first use, from a click. Setting to turn it off.

---

## Phase 6 — Look and feel (last)

- A typography and colour pass in `tinyui/src/style.css` tokens: a serif for headings and the empty-state greeting, a
  sans for body, warm neutrals, one accent colour, matching dark mode.
- Empty state: a time-of-day greeting ("Good evening") with the user's first name from preferences, the composer
  centred, then the suggestion cards.
- **Do not copy Anthropic's branding**: no Claude logo or name, no licensed Anthropic fonts, no copied colour values.
  The goal is the same calm reading experience, not a lookalike.

---

## Dropped from the previous version, and why

| Item                                              | Why                                                                                                                                                                                                        |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Search chats by content                           | Already done (`transcript.search_sessions`, snippets in the sidebar).                                                                                                                                      |
| "Manage memory" page                              | Already done (`MemoryView.vue` with forget). Only incognito was missing (5.1).                                                                                                                             |
| Quick entry window                                | The menu bar island already does this.                                                                                                                                                                     |
| Native desktop shell (Tauri/Electron), dock badge | A separate product decision with build cost, and CLAUDE.md names tinyui as the one interface. Needs an ADR in `docs/adr/` first; not part of this plan. Browser notifications (5.3) cover the useful part. |
| Truncate-and-resend for edits                     | Replaced by the turn tree (0.2, 1.2): nothing is deleted, and versions come for free.                                                                                                                      |
| Unmarked HTML blocks as artifacts                 | An explicit `artifact` marker keeps code examples in answers from turning into panels.                                                                                                                     |
| Suggestion delay setting                          | Not worth a setting yet.                                                                                                                                                                                   |

## Not in scope

Accounts, sync, billing, sharing links, team features, a branching tree view, remote connector marketplace (MCP
servers are already configured in Settings).

## Decisions (answered by the owner, 2026-11-22)

1. `CONTEXT_TOKENS` stays at 16384. The tailscale box cannot take a larger window, so do not raise the default.
2. `/persona` is dropped: remove it from `BUILTIN_COMMANDS` and do not implement it.
3. A chat belongs to at most one project, and a project holds several chats.
