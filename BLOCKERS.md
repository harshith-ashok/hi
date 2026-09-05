# Blockers to "powerhouse" status

This is a punch list, not a feature wishlist: every item below was found by
reading the actual current code, not by guessing at what might be wrong.
Each one is a real, load-bearing gap between what `hi` is today (a decent
shell/macOS-control assistant with a lot of narrow, well-tested add-on
tools) and what it needs to be to function as a genuinely capable agentic
assistant across real project work: reliable filesystem access, reliable
search, and vault context that actually surfaces what's relevant instead
of what happens to share a word with the note's filename.

The three complaints that prompted this list — can't find files, can't
read/understand a project's README, "save this project to the vault"
almost never works — all trace back to the same handful of root causes
below, not three unrelated bugs. Fixing #1-#3 (filesystem access) directly
fixes the README/find-files complaints; #3 also directly enables the
project-save complaint, which currently has **no dedicated tool at all**,
not a broken one.

---

## 1. `term` has no way to read a file outside the vault — at all

**This is the single biggest blocker.** Every file-reading tool `term`
has is hard-scoped to `<VAULT_PATH>/hi/knowledge/`:

- `hi/vault.py`'s `create_note`/`append_note`/`read_note`/`list_notes` all
  route through `_resolve_path(KNOWLEDGE_DIR, path)`, which raises
  `ValueError: Invalid path` for anything outside that one directory.
- There is no `read_file(path)`, no `list_directory(path)`, nothing that
  touches an arbitrary location on disk — a project's `README.md`,
  `package.json`, `pyproject.toml`, source files, none of it.

The only indirect path is `run_shell_command` (e.g. asking the model to
run `cat README.md`), which has three separate problems:

- **It requires a live tmux session with a sibling pane.**
  `hi/agents/term/shell_pane.py`'s `_own_pane_id()` raises outright
  (`"term needs to run inside a tmux pane with a sibling pane to control"`)
  if `TMUX_PANE` isn't set. The native macOS voice companion
  (`voice_companion/`) calls `term` through `hi/ipc/server.py`, which has
  no tmux context at all — **meaning `run_shell_command` is 100%
  unusable from the voice app**, and reading a README through it is not
  just unreliable there, it's impossible.
- It's designed to show the user a command running in their own shell,
  not to silently pull file content into the model's context — it echoes
  start/end markers, waits on a real terminal round-trip, and is a much
  heavier mechanism than "read this file" needs.
- It depends entirely on the model correctly guessing the right shell
  incantation (right relative path, right flags) with zero structure or
  guardrails — no size limit, no binary-file check, nothing.

**Fix:** a `read_project_file(path)` tool (and a `list_project_files(path)`
directory-listing counterpart) that reads directly off the filesystem via
plain `pathlib`, the same way `hi/agents/term/resume.py`'s
`resume_context` already reads git log/status via direct `subprocess`
calls — **not through `run_shell_command`/tmux at all**. That precedent
already proves this isn't blocked by any real technical constraint;
nothing like it was ever built for general file reading, that's all.
Should default to resolving relative to the current project directory
(`HI_LAUNCH_CWD`, already threaded through in `term.py`'s `build_agent`)
so "read the README" doesn't need an absolute path spelled out.

## 2. No real file/content search

There is no `find`/`grep`-equivalent tool. "Find the file that handles
X" or "which files mention Y" both fall back to the model constructing a
shell command through `run_shell_command` — same tmux dependency as #1,
same complete unavailability from the voice companion, same reliance on
the model happening to type the right incantation instead of calling a
tool built for the job.

**Fix:** a `search_files(query, path, mode="name"|"content")` tool —
name-glob search and a plain content grep, respecting `.gitignore` where
present, with sane defaults (skip `node_modules`/`.git`/binary files
without being asked). Structured results (path + line + snippet for
content matches), not a wall of raw `grep` output the model has to
re-parse.

## 3. "Save this project to the vault" has no dedicated tool — it never worked because nothing was built for it

`hi/agents/term/dev_flow_tool.py`'s `add_dev_flow` is the only
project-related "save" tool that exists, and it saves exactly
`{directory, tmux layout, apps}` to `dev_flows.json` — a **launcher
shortcut**, not a knowledge-capture mechanism. It never reads the
project's own content at all.

Today, "save this project to the vault" requires the model to
improvise a whole chain by itself: read the README and manifest file via
fragile shell commands (blocked entirely on the voice companion, per #1),
synthesize a summary, then call `create_note` with a guessed path under
`hi/knowledge/projects/`. There's no scaffolding for any of that — it's
asking the model to reliably orchestrate a multi-step task with the wrong
tools and no structure, so of course it "almost never works."

**Fix:** a `save_project_to_vault(directory)` tool that:

- Reads the project's README, manifest (`package.json`/`pyproject.toml`/
  `Cargo.toml`/etc. — whichever exists), and a shallow directory listing
  directly (once #1 exists, this can literally call the same underlying
  file-read function rather than duplicating it).
- Writes a real, structured note to `hi/knowledge/projects/<name>.md`
  (the path convention this codebase already uses elsewhere — see
  `hi/agents/term/resume.py`'s project-note lookup) summarizing what the
  project is, its stack, and its structure — not just a raw file dump.
- Ideally also offers to save it as a dev flow in the same turn (reusing
  `add_dev_flow`), since "save this project" plausibly means both
  "remember what it is" and "make it easy to reopen" — worth confirming
  with the user rather than assuming, the first time this is built.

## 4. Vault context retrieval is filename-matching, not real relevance ranking — and it's duplicated, not shared

Both grounding graphs that decide what context to load — `term`'s
`hi/memory_graph.py` and `docs`'s `hi/agents/docs/vault_rag.py` — use the
identical weak mechanism:

1. Dump every note's **path/filename only** (never its content) into one
   prompt, plus a `tree -L 4` structural snapshot.
2. Ask the model in one shot: "which of these paths are relevant?"
3. Parse relevance by checking whether each known path appears as a
   **literal substring** of the model's free-text reply
   (`[path for path in known_notes if path in reply]` — verbatim in both
   files).

The direct consequences:

- **A note's actual content is invisible to the selection step.** A note
  titled `misc.md` or `notes.md` can never be selected, no matter how
  relevant its content is — nothing about what's _in_ the note is ever
  looked at before deciding whether to load it.
- **No ranking, just a binary in/out** from one classification pass —
  no way to represent "these three are clearly relevant, these two might
  be."
- **Doesn't scale.** Every single note's path gets dumped into one prompt
  on every turn, regardless of vault size — a vault with real project
  breadth (people, projects, ideas, retros, tasks, applications — all of
  which this codebase already writes into `hi/knowledge/`/`hi/tasks/`)
  will either blow past what one classification call can reason about
  well, or just get ignored past the first screenful.

This is the direct, root-level cause of "context access is extremely
bad" — the mechanism was never built to do more than "does the filename
share a word with the question," and both personas that ground answers in
the vault share that exact same ceiling.

**Fix, roughly in order of effort:** (a) **done** — feed a short content
preview (first heading + first paragraph, or frontmatter) alongside each
path in the selection prompt, not just the bare filename. `hi/note_preview.py`,
shared by both grounding graphs — live-verified against a real case
where it mattered: "what are my interests?" answered correctly from
`hi/knowledge/people/Harshith_Ashok.md`, a filename with zero word
overlap with the question, which title-only selection could never have
surfaced. (b) **not yet built** — a real local keyword/BM25-style scoring
pass over note content before the LLM selection step; a plain scoring
algorithm, not a model, so unaffected by the local-model directive below.
(c) **un-blocked after explicit clarification**: this originally named
`nomic-embed-text` and `bge-m3` as "already pulled, no new dependency" —
both are local-only Ollama models, which briefly looked like a conflict
with the "DO NOT USE ANY LOCAL MODELS" directive that closed item 6
below. Clarified directly rather than assumed either way: that directive
is about local **generation/reasoning** models specifically — an
embedding model isn't "a proper AI model" in the sense meant (it's a
pure encoder, no generation happening), so running `nomic-embed-text`
locally is fine. `bge-m3` presumably falls in the same category but
wasn't explicitly named in the clarification — verify before relying on
it rather than assuming the same green light extends automatically. Not
built yet either way — still real work: embed every note, build/maintain
the index as a derived, rebuildable cache next to `tree_cache.md` (not a
second source of truth, keeping this compatible with `CLAUDE.md`'s
"filesystem is the single source of truth" principle), wire it into both
grounding graphs.

## 5. (Secondary, not directly evidenced — worth watching) `term`'s tool list has grown to 34 flat tools

`hi/agents/term/term.py`'s `TOOLS` list now spans shell execution, notes,
people, dev flows, resume-context, dev-server health, deadlines, LeetCode,
applications, the arbiter, retros, suggestions, team ops, pipelines,
browser observation, URL-opening, screen OCR, and screen vision — one
undifferentiated list, no grouping, no tiering. Every one of these was
added deliberately and is individually well-tested (see `TODO.md`), but a
single flat tool list this size is a real, plausible contributor to
unreliable tool selection ("it's dumb in every aspect") independent of
any one tool's own quality — more plausible candidates for the model to
mis-pick between on any given turn. Not confirmed by direct evidence the
way #1-#4 are (would need to actually measure tool-selection accuracy
before/after some restructuring), but worth keeping in view if fixing
#1-#4 doesn't fully resolve the "feels dumb" complaint on its own.

---

## Suggested order

1 and 2 first — they're the actual filesystem-access gap, they're what
the voice companion needs to be useful for anything project-related at
all, and 3 depends on 1 existing anyway. Then 3, which becomes a thin
tool once 1 exists. Then 4, which is the deepest and most valuable but
also the most work — start with the cheap content-preview fix (4a) before
reaching for a local embedding index (4c). 5 is an observation to revisit
after, not a ticket to start on its own.

---

# Suggested feature improvements

Separate from the blockers above: these aren't things that are broken,
they're places where `hi`'s design deliberately chose small/fast/
deterministic over smart, for reasons that made sense as _defaults_ but
don't fully apply to this setup specifically. `hi/config.py` already has
real frontier-scale models configured and idle for most of what `hi`
actually does day to day — `gpt-oss:120b-cloud` as the default for every
persona. **Correction, per explicit clarification — the account this
runs under does not have subscription access to every model that merely
shows up in `ollama list`.** `kimi-k2.7-code:cloud` and
`qwen3-coder:480b-cloud` were both named as "idle and available" in an
earlier version of this section; both actually require a subscription
this account doesn't have (matching what `TODO.md` already documented
live for `deepseek-v4-flash:cloud`: a `403 this model requires a
subscription` at call time despite it appearing in `ollama list`, listed
≠ usable). **The confirmed-usable cloud model set is**: `gemma4:31b-cloud`
(already `VISION_MODEL`), `gpt-oss:120b-cloud` (already the default for
every persona), `gpt-oss:20b-cloud` (already `HAIKU_MODEL`/`WEB_MODEL`),
`nemotron-3-nano:30b-cloud` (already pulled), and the larger NVIDIA
Nemotron 3 tiers, `nemotron-3-super`/`nemotron-3-ultra` (exact `:tag`
suffix not yet confirmed — check `ollama list`/pull before wiring
anything to them). **Worth verifying separately, flagged rather than
assumed**: `hi/config.py`'s current `OPUS_MODEL` default is
`qwen3.5:397b-cloud`, which is _not_ in the confirmed-usable list above —
if it's subscription-gated the same way `kimi`/`qwen3-coder`/
`deepseek-v4-flash` are, the `opus` tier is silently broken right now
(would only surface as a `403` the first time something actually routes
to it). `nemotron-3-ultra` is the natural swap-in once its exact tag is
confirmed, as the largest model in the confirmed-usable set. A
haiku-tier classifier and a hand-rolled scoring formula make sense when
every call costs real latency or money at a scale where that matters;
several of `hi`'s existing "deliberately not an LLM call" decisions were
made under that framing (named explicitly in `TODO.md`, e.g. the arbiter
and weekly retro), and
are worth revisiting now that the actual constraint is "make it as smart
as possible," not "keep it cheap."

## A. Let a capable model replace some of the deliberately-deterministic logic, as an opt-in

`hi/synthesis/arbiter.py` (`what_next`) and `hi/synthesis/retro.py`
(`generate_retro`) are hand-rolled scoring/aggregation, explicitly chosen
over an LLM call — the arbiter's own docstring reasoning is "the point is
to remove a decision, not introduce a second, less-inspectable one in its
place." That's a genuinely good default and shouldn't just be deleted —
but it was written under the assumption that an LLM call is a worse
option, not a better one, which isn't true once the model doing the
reasoning is actually strong enough to give a real, inspectable
justification rather than a shrug. Worth an opt-in "smart" variant of
each: same underlying data (pending tasks, deadlines, idle repos, git
activity, LeetCode streak), but a real model call — using `opus`/
`gpt-oss:120b-cloud` — synthesizing an actual narrative recommendation
instead of a fixed formula, kept alongside the deterministic version
rather than replacing it, since "remove the decision" is still the right
default for most turns.

## B. A real planner for multi-step, multi-persona requests

Today, one persona is picked per turn (`hi/router.py`'s haiku-tier
`classify()`), and everything within that turn is a flat ReAct loop —
there's no decomposition step. `TODO.md` Phase 4 explicitly named and
skipped a "Generic Planner/Executor subgraph" for lack of a concrete
consumer at the time — a capable cloud model is exactly what makes one
concrete now: "set up my environment for kaapi, check whether its
dependencies are outdated, and tell me if the README is stale" is a real,
plausible request that today's one-persona-per-turn router has no way to
decompose into ordered sub-tasks across `term`/`butler`/`docs`. A
lightweight supervisor pass on the `opus` tier — decompose into ordered
steps, hand each to the right persona/tool, synthesize a final answer —
would let `hi` handle genuinely ambitious requests in one turn instead of
requiring the user to manually break them into several.

## C. Real coding-agent capabilities for `term`, once file access exists

The single highest-leverage idea here, and the most direct answer to
"powerhouse" — **corrected**: there's no dedicated coding-specialist
model in the confirmed-usable set (no `kimi-k2.7-code`/`qwen3-coder`
equivalent — see the correction at the top of this section), so this
isn't "an idle specialist model going unused." It's simpler than that:
`term` already defaults to `gpt-oss:120b-cloud`, a genuinely large,
capable general-purpose model, for every request including coding ones —
the gap is entirely tooling, not model capability. Once blockers #1/#2
(real file read/search) exist, `term` could become a genuine coding
collaborator for the user's own projects using the model it already
has — propose and apply real file edits, run tests, iterate on
failures — much closer to how this very session operates than to a
shell-command dispatcher. `hi/action_tiers.py`'s destructive-action
confirmation gate already exists as real safety scaffolding to build this
on top of, not from scratch. If accuracy on real coding tasks turns out
to be the limiting factor rather than tooling once this is built,
`nemotron-3-ultra` (once its exact tag is confirmed) is the next thing to
benchmark against `gpt-oss:120b-cloud` for this specific job — not a
dedicated code model, since none is currently available on this account.

## D. Long-context synthesis as a complement to retrieval, not just embeddings

Blocker #4 named a local embedding index as the durable fix for vault
retrieval at scale. Given real long-context cloud models are already
available, there's a second, complementary strategy retrieval-based
approaches can't match: for genuine synthesis questions ("summarize
everything I know about X across every project," "what have I been
working on this month") — as opposed to "find the one relevant note"
questions — direct long-context stuffing (hand the model a large swath of
vault content at once) can give a better answer than narrowing down to a
handful of "relevant" notes first ever could, precisely because the
question is about the whole, not a part. Worth building both: retrieval
for point lookups, full-context synthesis for the big-picture questions
retrieval structurally under-serves.

## E. Surface the model's actual reasoning, not just its final answer

The same Ollama reasoning models `hi` already uses (`gpt-oss:120b-cloud`,
`qwen3:8b`, etc.) stream a separate `thinking`/reasoning content block
that a sibling project on this same machine (`sage/hi`) discovered
`langchain_ollama` silently drops unless `ChatOllama(reasoning=True)` is
set explicitly — and wired up as a live "thinking" trace once found.
Nothing in this codebase (`hi/streaming.py`, `term_prompt.md`, the voice
companion's Processing view) surfaces this today; every persona's actual
reasoning is invisible, only the final content ever reaches the user.
Seeing _why_ a frontier-scale model reached a conclusion — not just the
conclusion — is exactly the kind of value using one over a small model is
supposed to unlock, and it's currently thrown away unseen on every turn.

## F. Proactive, model-driven reflection over conversation history

`hi/knowledge/preferences.md` is the only durable, curated "what does
`hi` know about the user" artifact today, and nothing updates it
automatically — durable facts only get saved when a persona happens to
notice one mid-conversation (per `term_prompt.md`'s "proactively save
durable facts" instruction) or the user explicitly asks. A periodic
reflection pass — a capable model reviewing recent
`hi/conversations/` logs (already logged for every persona, every turn)
and proposing durable facts/preferences/project-context worth keeping —
run alongside the existing weekly retro, would make grounding compound in
value over time instead of depending on it being caught live in the
moment. This is the same kind of consolidation more advanced assistant
memory systems do, and `hi` already writes every ingredient it would need
for it (conversation logs, task history, retros) — nothing currently
reads them back for this purpose.

## G. Give the suggestion engine actual judgment, not just fixed thresholds

`hi/suggest/engine.py`'s confidence gating is deliberately deterministic
— documented reasoning: reliability for an unattended background loop,
which is still the right call for the loop's baseline behavior. On top of
that baseline, an opt-in pass where the periodic check also asks a
capable model "given everything currently being tracked, is there
anything genuinely worth surfacing right now" — beyond the fixed idle-
repo/deadline-window/streak rules — could catch holistic, cross-cutting
signals a fixed rule set structurally can't represent (e.g. three
separately-tracked things that are actually related and worth tackling
together, or a pattern across several days of retros). Keep the
deterministic rules as the always-on floor; add the model's judgment as
an enrichment on top, not a replacement — an unattended loop should never
depend entirely on a model call succeeding to do anything at all.

---

# Ambient & real-time gaps (toward an actual always-on assistant)

A third, distinct axis from the two sections above — those were about
model _intelligence_ (retrieval quality, planning, coding capability);
this one is about the _interaction model_ itself. Everything in `hi`
today is request/response: you type or press Ctrl-V, it answers, done.
Nothing is always-on, nothing interrupts anything else, and nothing
notices state changing on its own except the deliberately narrow,
already-gated pieces (`hi/suggest/engine.py`'s periodic checks). That's
the actual gap between what exists and "Jarvis." Verified each claim
below against the real code before writing it down, same as the rest of
this document — not restated secondhand.

## 1. Wake-word / always-listening voice loop

**Corrects something stated earlier in this project's own `TODO.md`**:
wake-word was documented as skipped because Porcupine (Picovoice) needs a
paid account this session can't provision. `openWakeWord` is a real,
fully open-source (Apache-2.0), local, ONNX-based wake-word engine —
**no account, no API key, no subscription** — which actually removes
that blocker rather than working around it. Worth reopening that
`TODO.md` item once this is built, rather than leaving "not built, needs
a Picovoice account" standing as the reason when it's no longer true.

Verified this affects both existing voice paths, not just one:

- **Terminal `hi`'s Ctrl-V** (`hi/voice.py`) is push-to-talk-then-_edit_,
  confirmed by reading it: `record_until_silence()` auto-stops on
  silence, `listen_and_transcribe()` returns the text, and `hi/repl.py`'s
  `c-v` binding drops it into the input line for the user to review and
  press Enter — it never auto-submits.
- **The voice companion app**'s dictation (`SpeechRecognizer.swift`)
  works the same way: live-updates the text field, still needs an
  explicit Return to send.

Neither is "always listening for a wake phrase, transcribe, and just
go" — both require a manual trigger and a manual submit today.

**Shape**: `hi/voice/wake.py`, a standalone daemon in the same pattern
this codebase already uses three times over (`hi/suggest/engine.py`'s
`run_suggest_daemon`, `hi/capture/hotkey.py`'s `run_capture_daemon`, and
now this) — started via a new `hi --wake-daemon`, listening _only_ for
the wake phrase via `openwakeword` (not transcribing continuously). On
trigger: reuse `hi/voice.py`'s existing `record_until_silence`/
`transcribe` pipeline unchanged, but pipe the result straight to the
router instead of requiring the manual-edit step.

**TTS for every response, not just the voice companion's spoken
summary** — confirmed there is currently zero TTS anywhere in Python
`hi/` (grepped the whole tree; `AVSpeechSynthesizer` exists only in
`voice_companion/Sources/HiVoice/SpeechOutput.swift`, nothing on the
terminal side at all). Reuse `hi/streaming.py`'s existing token stream,
feeding sentence-chunks to a local TTS engine as they arrive rather than
waiting for the full response. macOS's built-in `say` is the honest
zero-dependency MVP placeholder here — matches exactly why
`AVSpeechSynthesizer` was chosen for the voice companion in the first
place (see `TODO.md`'s Phase 5 notes); `kokoro`/`piper` are real
upgrades to reach for once/if `say`'s quality proves insufficient, not a
starting requirement.

**Barge-in** needs a real shared "is speaking" signal plus an actual
interrupt, not a queue that just plays things one after another — this
is the same primitive as item 3 below, not a separate mechanism to build
twice.

## 2. A real background watcher, gated properly — not "none at all"

The existing `hi/perception/` design deliberately has no background
watcher of any kind — a correct call for _content_ (screen/browser
reading), but it means `hi` currently can't notice anything changing on
its own at all, which is a big part of why it doesn't feel ambient.

The fix doesn't need to touch that content-reading gate: `hi/perception/
privacy.py`'s `frontmost_app_name()`/`frontmost_window_title()` already
exist and already do exactly the AppleScript query this needs — they're
just currently only called reactively, inside `sensitive_context_reason()`,
right before a perception tool would act. A new `hi/watchdogs/
context_shift.py` polling those same two functions every 30-60s, purely
for state-change detection (app switched, gone idle N minutes — never
content, never OCR), is a thin addition built entirely on primitives
already proven correct, not new surface area.

Feed detected state changes into `hi/suggest/engine.py`'s existing
`gather_suggestions()`/`run_once()` — the same confidence-gate and
per-day dedup (`~/.hi/suggest_state.json`) every other signal already
goes through (`hi/watchdogs/idle_repos.py`, deadlines, LeetCode,
applications) — rather than a parallel notification path. E.g. "Xcode's
been frontmost with no app switch for 25 minutes and a deadline note is
2 days out" becomes one more gated `Suggestion`, reusing infrastructure
this project already built and tested, not a new one.

## 3. Unified interrupt/cancellation, not three different (or missing) paths

Verified directly: `hi/repl.py` has exactly two real key bindings
(`c-l` clear, `c-v` voice). Ctrl-J is **not** a key binding at all — it's
a raw-terminal cbreak-mode byte read inside `hi/agents/term/
shell_pane.py`'s `_check_interrupt()`, active only while
`run_in_left_pane` is polling for a shell command to finish. There is no
interrupt path for a mid-generation LLM stream (`hi/streaming.py`'s
`stream_and_print` has no cancellation hook at all) or for TTS playback
(doesn't exist yet — item 1). So today: one real interrupt (shell-wait
only), one missing (generation), one not-yet-applicable (TTS) — three
different mechanisms where conceptually there should be one.

Fix: a single cancellation primitive (an `asyncio.Event`/threading
equivalent) threaded through `repl.py`'s loop, checked by shell-wait,
generation-streaming, and TTS playback alike — replacing Ctrl-J's
shell-specific special case with "the one thing that cancels whatever's
currently happening," triggerable the same way regardless of which of
the three is in flight.

## 4. Continuous scene-change detection, still gated — a genuinely different privacy posture, flagged as such

`hi/perception/screen.py`/`vision.py` are one-shot by design — correct
for privacy, but it means `hi` can never notice "you've been stuck on
the same stack trace for 10 minutes" on its own.

A middle ground: `hi/perception/diff_watch.py`, hashing/diffing
screenshots at a long interval (~2 min) purely to detect _changed vs.
didn't_ — never OCR'd, never stored, never even looked at beyond a hash
comparison, unless a real change is detected. Still runs every check
through `hi/perception/privacy.py`'s existing `sensitive_context_reason()`
gate first, same as every other perception tool.

This is honestly a different privacy posture than "on-demand only, one
screenshot per explicit ask" (the current design, and the one
`voice_companion/README.md` and `TODO.md` both describe as deliberate).
Agreed this needs its own explicit opt-in — a new flag in `~/.hi/.env`,
off by default — rather than silently broadening what "on-demand" means
for the existing tools. `read_screen`/`ask_about_screen` themselves
shouldn't change behavior at all; this is a new, separately-gated
capability sitting next to them, not a modification to them.

## 5. Multi-turn negotiation for the arbiter, not a single unchallengeable answer

`hi/synthesis/arbiter.py`'s `pick_next_hour()` is a pure, stateless
function today — no memory of what it recommended last time. A pushback
reply ("not that, I don't have time today") currently has nowhere to go
except being classified as an unrelated fresh turn.

The fix is genuinely small, as described: session-level state (a
`last_arbiter_rejects: list[str]` of excluded task ids) threaded through
wherever `what_next` gets invoked in a session, re-running
`pick_next_hour()` with that exclusion applied — `pick_next_hour()`'s
scoring loop already just filters/sorts a task list, so excluding
specific ids slots in without touching its actual scoring logic. The one
piece of real new plumbing: `hi/router.py`'s `classify()` treats every
turn independently today, so recognizing "this is a pushback on the
arbiter's last answer" as its own turn shape (rather than a fresh,
unrelated classification) is the part that doesn't exist yet and needs
designing, not just the state list itself.

## 6. Latency — **rejected per explicit directive: "DO NOT USE ANY LOCAL MODELS"**

Confirmed directly in `hi/config.py`: `HAIKU_MODEL` defaults to
`gpt-oss:20b-cloud` — a **cloud** model for the tier that's explicitly
meant to be the fast/cheap one, and the one every single router-mode
turn calls unconditionally (`hi/router.py`'s `classify()` always uses
`get_tier_model("haiku")`, before anything else about the turn happens).
`hi/model_warmup.py`'s retry-past-empty-`done_reason='load'` workaround
exists specifically because of this pattern — a real, already-documented
behavior, not a hypothetical latency concern.

**This section originally proposed pointing `HAIKU_MODEL` at a local
model — live-benchmarked before acting on it, then explicitly overruled;
both the benchmark result and the override are worth keeping on record.**
Three local candidates were timed for real, on this actual machine
(Apple M3 Pro, 18GB), against a classification-shaped prompt matching
what `hi/router.py`'s `classify()` actually sends — specifically because
`hi/config.py` already carries a comment documenting a prior finding
that a local 8B model measured 30-85s per call here, worth re-checking
rather than assuming stale: `gemma3:1b` answered in 0.34s but the reply
was garbled and unusable (echoed the prompt's own placeholder text back
verbatim instead of filling it in); `llama3.2:3b` took 7.01s and got the
tier wrong; `qwen3:8b` took 14.05s. None cleared speed _and_ correctness
together — the original comment's finding held up under a fresh check,
it wasn't stale. **Moot regardless of that result**: mid-benchmark, the
explicit instruction came back — "DO NOT USE ANY LOCAL MODELS." This
closes the item outright, not just deprioritizes it; `HAIKU_MODEL` stays
`gpt-oss:20b-cloud`. Consistent with this whole document's own framing
("I am literally using actual big cloud models") — local was always the
wrong axis to optimize on for this setup, cloud-round-trip latency is
the accepted cost of that choice. If turn latency is worth revisiting
later, it needs a cloud-only angle (e.g. fewer round trips per turn),
not a local-model swap.

---

Two changes matter more than any feature: right now `router.py` picks exactly one persona and one tier per turn — there's no notion of a plan, and nothing spawns anything. And your event stream (once you build the AG-UI server) is currently going to be flat text tokens, which can't express "3 subagents are running" or "here's an inline widget from an MCP app." Both need fixing before orchestration is real, not bolted on.

You already have LangGraph as a dependency and aren't really using its multigraph/checkpointer capabilities — the orchestration layer below is built to actually use what you're already carrying, not add a second framework.

## Architecture changeThe classifier reuses your existing router — same classify call, extended to also return "simple" vs "complex" instead of just persona+tier. Complex turns don't get one persona; they get a plan.

**New module map:**

```
hi/orchestrator/
├── complexity.py     # extends router.py's existing classifier with a plan/no-plan signal
├── planner.py        # decomposes a complex turn into a task DAG — a LangGraph StateGraph, built at runtime
├── graph.py          # executes the DAG: asyncio.gather across independent nodes, bounded by a Semaphore per model tier
├── subagent.py        # spawns a scoped agent — persona + tier + tool allowlist — least privilege per task
├── blackboard.py       # LangGraph checkpointer (SqliteSaver) — shared run state instead of a bespoke store
├── aggregator.py         # merges subagent outputs, synthesizes final response
└── pending_actions.py     # queue of subagent actions awaiting confirmation — see action_tiers below
```

Modified existing modules:

- **`hi/router.py`** — calls `complexity.py` first; complex turns hand off to `orchestrator/graph.py` instead of a single persona call.
- **`hi/action_tiers.py`** — this is the one that actually matters for safety. Right now your confirm gate presumably blocks on a `prompt()` call in the REPL. That doesn't work when a background subagent hits a destructive action with no human watching that exact pane. Route confirm requests into `pending_actions.py`'s queue instead; any connected client (tmux, Swift panel, web) can see and approve/deny pending actions, and the subagent actually blocks on that queue entry, not on stdin.
- **`hi/mcp_tools.py`** — currently returns tool results as text. MCP is growing UI-producing resources (structured widgets, not just strings) — this needs to detect and pass those through as a distinct content type instead of stringifying them.
- **`hi/streaming.py`** — becomes the AG-UI adapter. LangGraph's `.astream_events()` already emits structured per-node/per-tool events; translate those into AG-UI's schema (`RUN_STARTED`, `TEXT_MESSAGE_CONTENT_DELTA`, `TOOL_CALL_START/ARGS/END`, `STATE_DELTA`, `CUSTOM` for MCP-UI payloads, `RUN_FINISHED`) instead of hand-rolling token strings. This is the actual point of adopting AG-UI: any AG-UI-aware client — including third-party ones you didn't write — can render your agent's run without you inventing a wire format.

Concretely, why AG-UI over raw SSE tokens: once you have parallel subagents, "which agent said what" and "here's a tool's rendered widget, not just its text result" need structure the client can distinguish. A flat token stream can't express that; a typed event stream can.MCP-UI resources (a GitHub PR view, a booking widget) flow through as `CUSTOM` events in the AG-UI stream, so a client that understands AG-UI's generative-UI event type can render the actual widget inline instead of just its text fallback. This is the same mechanism this very chat interface uses for MCP Apps — you're not inventing new plumbing, you're adopting an existing pattern.

## Todos

**Phase 1 — orchestration substrate (do this before anything else)**

1. `complexity.py` — extend the router's classifier prompt to return a `plan: bool` alongside persona/tier
2. `planner.py` — LangGraph `StateGraph` builder: given a complex turn, emit a DAG of `{persona, tier, tool_scope, depends_on}` nodes
3. `subagent.py` — factory that builds a scoped agent from one DAG node (reuses `personas.py`'s existing `build_agent(model)` factory, just narrows its tools)
4. `graph.py` — executor: topological sort, `asyncio.gather` on independent nodes, `asyncio.Semaphore` bounding concurrent model calls (start at 3 — local/cloud Ollama will choke past that)
5. `blackboard.py` — wire LangGraph's `SqliteSaver` as the checkpointer so a run's state survives a crash mid-DAG
6. `aggregator.py` — synthesis pass over subagent outputs into one response
7. Write each completed run as a dated note under `<VAULT_PATH>/hi/conversations/runs/` — DAG shape, which subagent did what, tool calls made. This keeps the "filesystem is the source of truth" principle intact for orchestrated runs, not just single-turn ones.

**Phase 2 — action safety under autonomy** 8. `pending_actions.py` — queue + `GET /pending`, `POST /pending/{id}/approve|deny` endpoints 9. Rework `action_tiers.py`'s confirm gate to post into this queue instead of blocking on stdin 10. tmux REPL and the Swift panel both need a "pending approvals" indicator — this can't be silent, or a subagent just hangs forever

**Phase 3 — AG-UI adoption** 11. Add the AG-UI Python SDK dependency (it has first-class LangGraph support — check their reference integration before writing your own event mapper) 12. `hi/agui_adapter.py` — map LangGraph's `astream_events()` output to AG-UI event types 13. Rebuild `hi/server.py`'s `/turn` endpoint on this adapter instead of raw token SSE 14. Extend `hi/mcp_tools.py` to detect MCP-UI resource blocks in tool results, pass through as `CUSTOM` AG-UI events instead of stringifying 15. Swift panel: add a generic widget renderer (sandboxed `WKWebView` is the pragmatic choice, since MCP-UI resources are commonly HTML) for `CUSTOM` events

**Phase 4 — polish** 16. Live DAG status line in the tmux pane while subagents run in parallel — even a plain `[drafting] [checking build] [reading vault]` beats a silent wait 17. A `trace` command — `(term) > show me how you did that` replays the last run's log note from step 7

## More features

1. **Named subagent archetypes** — instead of always spawning generic personas, define a few fixed roles (`Researcher`, `Coder`, `Reviewer`, `Fixer`) with distinct system prompts and tool allowlists the planner picks from. Composable, not ad hoc per task.
2. **Reviewer-verifies-Coder for destructive plans** — before a subagent's shell-command plan hits the `action_tiers` confirm gate, a second cheap-tier subagent checks it. Multi-step autonomous planning raises the cost of a bad plan; catch it before the human even sees the approval prompt.
3. **Auto-retry with tier escalation** — if a subagent's tool call fails, the orchestrator retries once with a different tool or a higher tier before surfacing failure. Right now a failure is just a failure.
4. **Quick/thorough budget flag** — user-settable, changes how many subagents the planner is allowed to spawn and which tiers it reaches for. "Quick" caps at haiku-tier, no parallel branches; "thorough" allows full DAG breadth.
5. **Scoped scratch space per run** — subagents write intermediate notes to a per-run temp directory, not `hi/knowledge/` directly. The aggregator promotes only what's worth keeping. Otherwise failed/parallel branches clutter the vault.
6. **Approvals as generative UI, not text** — since AG-UI supports custom render events, make the approve/deny prompt from step 9 an actual inline button via `CUSTOM`, not a yes/no text exchange.
7. **Conversational MCP server install** — `butler`/`term` can browse and add a new MCP server by name, writing the config entry into `~/.hi/.env` for you, instead of manual editing.
8. **MCP-UI widget recall** — when an MCP app returns a rendered widget (a PR diff view, a booking screen), save a reference to it in the vault so `docs` can say "show me that again" without re-fetching.

Start with Phase 1, items 1–4 — nothing else here works without a DAG executor that actually bounds concurrency against your local model pool.
