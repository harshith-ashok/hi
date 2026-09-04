# hi Voice — native macOS voice companion

A separate native shell, not another persona (TODO.md Phase 5) — a
Spotlight-style companion that talks to the same `hi` backend over local
IPC, so it inherits the exact router-mode logic (persona/tier
classification, per-persona memory, every tool every persona has) that
`hi/repl.py`'s `run_router_repl()` already drives, instead of duplicating
any of it.

**Redesigned per explicit request** from an edge-docked, hover-triggered
sliver (the original TODO.md Phase 5 spec) into a centered, Spotlight-like
panel you summon with a hotkey and can type *or* dictate into — see
"The Spotlight redesign" below for what changed and why.

## What's built

- **Backend IPC layer** (`hi/ipc/`, Python side): `hi --voice-daemon`
  runs a loopback-only HTTP server (`127.0.0.1:8765`) that classifies a
  query the same way router mode does, streams the response back as
  newline-delimited JSON, and produces a short spoken-summary alongside
  the full text (`hi/ipc/spoken_summary.py` — hard-strips code
  blocks/tables before ever considering something speakable, then either
  returns a short answer as-is or condenses a longer one with one small
  model call). **Fully tested live** — `curl` against a running daemon
  produced real streamed responses and correct spoken summaries,
  including a response containing a code block (verified the code was
  excluded from what got spoken).
- **Native app shell** (`Sources/HiVoice/`, Swift/AppKit/SwiftUI): a
  centered, borderless, non-activating `KeyablePanel` (a custom `NSPanel`
  subclass — see "The Spotlight redesign"), hidden until summoned.
  Compiles and links cleanly (`swift build`); packaged as a real `.app`
  bundle via `Scripts/build_app.sh` (SPM alone doesn't produce one, and a
  bundle with a proper `Info.plist` turned out to be *required*, not
  optional — see "What actually got tested," below).
- **State machine** (`AppState.swift`): `hidden -> input (type and/or
  dictate) -> processing -> done` (or `error`), replacing the original
  `collapsed -> listening -> processing -> done` sequence — see "The
  Spotlight redesign."
- **Streaming local STT** (`SpeechRecognizer.swift`): Apple's on-device
  `Speech` framework (`SFSpeechRecognizer`, `requiresOnDeviceRecognition`
  when supported), not whisper.cpp — TODO.md's own "Open decisions"
  section named both as options; Speech was chosen for zero extra
  dependencies/bundled models, consistent with this project's existing
  "native Apple framework over a new bundled dependency" pattern
  (Vision-framework OCR in `hi/perception/screen.py`, `AVSpeechSynthesizer`
  for TTS below). Dictation now live-updates the same text field typing
  would, rather than owning a dedicated "Listening" panel state.
- **Selective TTS** (`SpeechOutput.swift`): speaks only the backend's
  spoken-summary via `AVSpeechSynthesizer` (the zero-dependency default
  TODO.md itself names), with barge-in (starting dictation always
  interrupts an in-progress utterance).
- **Visual language**: `NSVisualEffectView` (`.hudWindow` material) for
  translucent vibrancy, system SF Pro fonts, an 8px corner radius
  (Catalina's ~6-9px range), thin hairline dividers instead of card
  shadows, a plain `.easeInOut` resize/fade animation (no spring/bounce).
  Light/dark handled by SwiftUI's semantic colors automatically rather
  than two hand-tuned palettes. Carried over unchanged through the
  Spotlight redesign — only the panel's shape and position changed, not
  its material/motion language.
- **Menu bar status icon** (`StatusItemController.swift`, added per
  explicit request): an `NSStatusItem` reflecting live state — idle
  (waveform), listening (blue mic), input-ready (cursor), working
  (ellipsis), done (green check), error/backend-unreachable (red
  triangle), driven by the same `AppState.$phase`/
  `BackendHealthMonitor.$isReachable` publishers the panel itself
  observes, so the two never disagree. Its menu carries the app's only
  Quit action (no Dock icon, so there was genuinely no other way to stop
  it before this existed) and a "Show hi Voice" item — a fallback trigger
  that works even before Accessibility permission is granted, since the
  global hotkey needs that permission and the menu click doesn't.
  **Live-verified on a real screen, including a real, non-obvious bug
  caught and fixed in the process**: the icon was initially invisible
  despite every internal signal (a valid, non-nil `NSStatusBarButton`, a
  correctly-rendered `NSImage`, `isVisible == true`) looking correct —
  narrowed down by reading the status item's own window frame directly,
  which came back `height: 0` immediately after creation, then a real,
  non-zero frame a second later once AppKit's own layout pass caught up.
  Not a code defect, in the end — a frame-timing artifact this session
  couldn't see past without asking you to look at the actual screen,
  which you did; confirmed working.

## The Spotlight redesign

The original design (edge-docked sliver, hover-to-expand, voice-only) was
replaced, per explicit request, with a Spotlight-style interaction:

- **Centered panel, not edge-docked.** `PanelController.swift` positions
  a 560px-wide panel horizontally centered, about a third of the way down
  the main screen — the same rough position Spotlight itself uses, not
  flush against a screen edge.
- **A hotkey, not hover.** Option+Space (chosen to avoid colliding with
  real Spotlight's Cmd+Space) toggles the panel open/closed from
  anywhere, via the same kind of global `NSEvent` monitor the original
  hover trigger used — still needs Accessibility trust for the same
  reason. A local key monitor separately handles Escape-to-dismiss and
  the same hotkey while the panel itself is key. The menu bar's "Show hi
  Voice" item is a hotkey-independent fallback (see above).
- **Type or dictate into the same field**, not voice-only. One `TextField`
  is always present and focused when the panel opens; a mic button beside
  it toggles dictation, which live-updates that same field (appending
  after whatever was already typed, not overwriting it) rather than
  showing a separate "Listening" transcript view. Press Return to submit
  either way.
- **A real, one-off `NSPanel` subclass was required for typing to work at
  all.** A borderless `NSPanel` does not become key (accept keyboard
  focus) by default — verified by reading Apple's own documented
  behavior before relying on it, not discovered by a runtime failure this
  session couldn't diagnose. `KeyablePanel.swift` overrides
  `canBecomeKey`, the standard trick every Spotlight-alternative
  (Alfred/Raycast/etc.) needs for exactly this reason — `.nonactivatingPanel`
  in the style mask still means opening the panel never steals focus from
  or changes the menu bar of whatever app was frontmost; `KeyablePanel`
  is what lets it *additionally* accept keystrokes once explicitly asked.
- **No more timed auto-collapse.** The original design auto-collapsed 8s
  after an answer, matching a HUD-notification feel. A Spotlight-style
  tool stays open until you act on it — dismissed via Escape, the hotkey
  again, clicking away, or an explicit "Dismiss" affordance in the
  results view; "New question" resets to a fresh input without closing
  the panel.

## Two more real bugs, found by you actually using the redesign

- **"Open youtube in safari" only opened the bare app.** Root cause was
  in the shared Python backend, not the Swift app: neither `butler`
  (which owns `open_app`, launch-only, no navigation) nor `term` had any
  tool that could actually open a URL — `hi/tracking/leetcode.py`'s
  browser-opening logic existed but was private to that one file. Fixed
  by extracting it into a new shared `hi/browser.py` (`open_url()` the
  plain function, `open_url_in_browser` the agent tool) and registering
  it on **both** `butler` and `term`, since router classification could
  plausibly send an "open X" request to either. Verified end to end: a
  real `classify()` call for the exact failing phrase, then invoking the
  real `butler` agent directly and confirming it called
  `open_url_in_browser` with the correct resolved URL
  (`https://youtube.com`) and a real tab landed in Safari (checked via
  Safari's own tab list, then closed).
- **The panel visibly jumped down and snapped back on every keystroke.**
  Root cause: `PanelController`'s `AppState.$phase` subscription had no
  deduplication, so it re-ran the animated window-frame reposition on
  *every* keystroke — `.input(text: "a", ...)` and `.input(text: "ab",
  ...)` are different `Equatable` values, so each keystroke published a
  "new" phase and re-triggered a `setFrame` animation to the same target
  frame, visibly interrupting itself before settling. Fixed by
  deduplicating on phase *kind* (hidden/input/expanded) rather than full
  phase equality — repositioning now only fires on a genuine state
  transition, never on a keystroke or a mic-toggle within `.input`. The
  original edge-docked design actually had exactly this deduplication
  (filtering by `isCollapsed`) for the same reason; it was dropped by
  accident during the Spotlight rewrite rather than deliberately, and
  this is that guard restored in the new shape.

## Pending-approval indicator (TODO.md Phase 17)

`PendingActionsMonitor.swift` polls `hi --voice-daemon`'s `GET /pending`
every 5s; `StatusItemController.swift` shows a distinct amber "N
awaiting approval" menu bar icon and, per pending action, a submenu with
Approve/Deny — wired to two new `BackendClient.swift` methods
(`fetchPendingActions()`, `resolvePendingAction(id:approve:)`), mirroring
`BackendHealthMonitor.swift`'s own existing polling pattern rather than
inventing a second one.

**Honest limitation, not a bug**: this always shows zero pending
actions today. A pending action can only ever exist if an orchestrated
subagent (`hi/orchestrator/graph.py`) hits a destructive action — and
`run_orchestrated()` only runs inside the terminal REPL's own process,
never this app's backend (`hi/ipc/server.py`'s `/query` was never wired
to it). The Python side's real, currently-reachable indicator is
`hi/orchestrator/pending_server.py`, a *separate* dedicated server on
port 8766 started with the terminal REPL — see that module's docstring
and `TODO.md`'s Phase 17 write-up for the full reasoning. This Swift-side
plumbing is built and compiles clean against the real, already-working
HTTP contract (`GET`/`POST /pending/...`, identical route logic shared
with the port-8766 server via `hi/orchestrator/pending_http.py`)
regardless, ready for whenever a future phase wires orchestration into
this app's own backend process too — not speculative scaffolding, just
correctly scoped ahead of that connection existing.

## The ui.html redesign

A further redesign, per explicit request: implement `hi/ui.html` (a
static browser mockup exploring a Catalina-terminal aesthetic — persona
tabs, a compact briefing strip, a sequential turn log, a `(persona) >`
prompt bar) as the real native panel, replacing the Spotlight redesign's
one-shot "input → processing → done screen → New Question" cycle with
an always-visible, continuously-growing conversation — asking, getting
an answer appended to the log, asking again, the way a real terminal
session works, matching `hi/repl.py`'s own REPL feel far more closely
than a modal done/error screen did.

- **State model rearchitected, not patched.** The old `CompanionPhase`
  enum (`hidden`/`input`/`processing`/`done`/`error`) encoded the
  one-shot cycle directly and couldn't represent "busy AND has prior
  turns AND currently dictating" all being true at once — a real state
  a REPL-style panel needs. `AppState.swift` now exposes flatter,
  independently-`@Published` properties (`isVisible`, `persona`,
  `isBusy`, `isListening`, `turns: [Turn]`, `briefing`) instead of one
  discriminated union. An error is now just another `Turn` (a
  `.systemError` role, rust-colored) appended to the log, not a
  separate screen that replaces conversation history — nothing should
  ever destroy turn history, matching ui.html's own log-centric design.
- **Two real backend changes**, not just a Swift-side reskin — the
  mockup's tabs and briefing strip needed real data/behavior behind
  them, so `hi/ipc/server.py` gained:
  - An optional `"persona"` field on `POST /query` — forces a specific
    persona (skipping `classify()` entirely, `sonnet` tier), the same
    "force a persona" behavior `hi --term`/`--butler`/etc. already give
    the terminal, now reachable from the panel's tab row too.
  - A new `GET /briefing`, wrapping the *existing* `hi/briefing.py`
    (already used once at `hi/repl.py`'s session start) — required
    splitting `build_briefing()`'s return from one pre-joined display
    string into `(context, suggestion, action)` so the compact
    one-line strip can show just the suggestion, not a multi-line
    context dump (`hi/repl.py`'s own terminal call site updated to
    rejoin them, unchanged in effect there).
  - **Live-verified against the real running daemon**, not just
    written: `curl GET /briefing` returned real gathered
    context/suggestion/action from this actual machine's real pending
    tasks/deadlines; `curl POST /query` with `"persona": "web"`
    correctly bypassed classification (`{"event": "persona", "name":
    "web", "tier": "sonnet"}`) and streamed real tokens.
- **Visual language ported deliberately, not copied pixel-for-pixel.**
  ui.html's own two web fonts (JetBrains Mono + Inter, loaded as
  `.woff2` — a format Core Text doesn't reliably handle, and this
  project's own established "native framework over a new bundled
  dependency" pattern, per the original Spotlight redesign's font
  choice above) are replaced with SF Mono and the system font — same
  monospace/humanist-sans pairing intent, zero bundling risk, and
  actually *more* native than matching the mockup verbatim would be.
  The color palette (`Theme.swift`) is a direct, literal port of
  ui.html's own CSS custom properties — one fixed dark theme regardless
  of system light/dark mode, matching the mockup's own single-theme
  design and this project's whole terminal-first brand identity, a
  deliberate departure from the Spotlight redesign's semantic-color
  light/dark adaptation. `VisualEffectBlur.swift` (translucent HUD
  vibrancy) is gone — ui.html's panel is solid/opaque, not translucent,
  and carrying forward an unused file once nothing referenced it
  anymore wasn't worth the confusion.
- **Panel sizing made robust to not being visually verifiable.** This
  session has no way to screenshot or interact with a live native
  window (the same standing limitation "What actually got tested"
  already documents below) — so rather than trust hand-estimated pixel
  heights (`PanelController`'s two target heights, compact/expanded)
  to be exactly right, `ContentView`'s root view now explicitly fills
  whatever frame the panel assigns it
  (`.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)`)
  instead of sizing to its own natural content height. That makes any
  gap between the estimate and SwiftUI's real layout get absorbed by
  the flexible turn-log area (a bit more or less breathing room) rather
  than clipping the fixed-height tabs/briefing/prompt-bar rows around
  it — the failure mode that would actually look broken.

**What was verified, and what wasn't, same honest split as below**: the
Swift package compiles clean (`swift build`), packages into a real
`.app` bundle (`Scripts/build_app.sh`, unchanged and still working), and
the packaged app launches and stays running with no crash log — checked
directly against `~/Library/Logs/DiagnosticReports`, both right after
launch and several seconds later. The two backend endpoints it now
depends on were independently verified live via `curl` against the real
running daemon (see above). **Not verified**: the actual on-screen
rendering (do the tabs/briefing/log/prompt bar actually look like
ui.html, are the panel heights actually right, does text wrap/overflow
correctly at 620pt) and any real interaction (typing, tab-clicking,
dictating, the briefing action button) — this session has no way to see
or drive a live native window, the exact same limitation the original
Spotlight redesign hit. The packaged app was left running for a real
first look: `open`'d, confirmed alive via `pgrep`, ready for Option+Space.

## A proper native app, not just a quick-access panel

Per explicit request: "create a proper native app that expands the
functionality and replaces the terminal agent entirely... don't remove
the agent but create a UI for it." The Option+Space floating panel above
stays exactly as it was (still useful for a fast in-and-out question) —
this adds a second, real surface on top of it: a standard, resizable,
titled `NSWindow` (`MainWindowController.swift`/`MainWindowView.swift`)
with a sidebar (New Chat / conversation history / Settings), the way an
actual daily-driver app looks, rather than a Spotlight-style popup. Both
surfaces share the same `AppState`/`BackendClient` instances, so a
conversation continues seamlessly whichever one you're using — reused
`ContentView.swift`'s existing turn-log/widget/pending-action/prompt-bar
pieces (made non-`private` for exactly this) rather than a second,
diverging chat implementation.

- **Real app presence.** `NSApp.setActivationPolicy(.regular)` — a Dock
  icon, Cmd+Tab reachability, a minimal programmatic main menu
  (`AppDelegate.buildMainMenu()`, since this project has no Xib —
  App/Window menus only, the essentials Cmd+Q and standard window
  commands need). Closing the main window hides it, same as the panel's
  own hide/show model; the Dock icon (`applicationShouldHandleReopen`)
  brings it back.
- **Conversation history**, read-only: `hi/ipc/server.py`'s new
  `GET /conversations` / `GET /conversations/{date}` read back the exact
  dated logs `hi/vault.py`'s `log_conversation()` already writes for
  every persona turn on every surface — no new storage, just a sidebar
  reading what already existed (`HistoryView.swift`, rendered via
  SwiftUI's built-in Markdown-`AttributedString` parsing with a raw-text
  fallback if a real log's content trips it up).
- **A real Settings screen** (`SettingsView.swift`) over `~/.hi/.env`
  instead of hand-editing it — `GET`/`POST /config`, model names per
  tier/persona and the vault path. Deliberately excludes the MCP
  credentials (GitHub token, Obsidian key): those stay reachable only
  through `hi/mcp_install.py`'s conversational, confirm-gated tool, never
  echoed back to a plain `GET`. Honestly caveated, not glossed over: a
  save writes to `.env` correctly, but `hi/models.py`'s `TIER_MODELS` and
  `hi/vault.py`'s vault-path constants are both built once at import
  time — a model/vault-path change needs a restart to actually take
  effect, which the endpoint's own response says explicitly.
- **Real bugs caught building this, not after**: `GET /config` first
  crashed with `TypeError: Object of type PosixPath is not JSON
  serializable` (`VAULT_PATH` is a real `Path` on `hi.config`, not a
  string) — fixed by `str()`-ing it for the response. Caught, before it
  could ship, that naively `setattr`-ing a plain string back onto
  `config.VAULT_PATH` after a save would have silently turned it into a
  non-`Path` value for the rest of the process, breaking any later
  `VAULT_PATH / "..."` — fixed by wrapping it back into `Path` on write.
- **Live-verified, not just compiled clean**: every new endpoint via
  real `curl` against the actual running voice daemon —
  `GET /conversations` returned real dated logs from the real vault;
  `GET /conversations/{date}` returned real content for a real date and
  a 404 for a fake one; `GET /config` returned real current settings;
  `POST /config` with a throwaway test value round-tripped correctly
  (file written, in-memory value updated, reflected in the next `GET`),
  then reverted; posting a secret field (`GITHUB_PERSONAL_ACCESS_TOKEN`)
  was correctly rejected with a 400. Swift: `swift build` clean on the
  first attempt; the packaged app relaunched with a real window titled
  "hi" confirmed via `System Events` (not just "the process didn't
  crash"), and `background only` confirmed `false` — genuinely running
  as a regular, Dock-visible app, not the old menu-bar-only accessory.
- **The underlying Python agent is untouched as an entry point**: `hi`'s
  terminal REPL (`hi --term`/`--butler`/`--docs`/`--web`/auto-routing
  mode), tmux integration, and every persona/tool/orchestrator module
  are exactly as they were — this app is a new, additional way to reach
  the same backend, not a replacement for the Python side, matching the
  explicit "don't remove the agent" instruction.

## What's deliberately not built

- **Wake-word activation.** TODO.md names Porcupine as an example engine
  — it's a third-party (Picovoice) SDK needing an account and API key
  this session has no access to and can't provision unilaterally. The
  hotkey and the menu bar's "Show hi Voice" are the only activation paths
  built. Adding wake-word later means dropping a Picovoice-backed
  detector in that calls `AppState.show()`, same as both existing
  triggers do — the rest of the pipeline doesn't need to change.
- **Real silence detection (VAD).** Ending an utterance is still
  explicit-stop only (toggle the mic button off, or just press Return)
  — TODO.md allows either "silence detection or explicit stop." Automatic
  end-of-utterance detection remains separate, non-trivial scope
  intentionally left for later.
- **Full agent-step transparency in the Processing state.** TODO.md's own
  "Open decisions" flags this as unresolved. Still the simplified side:
  one line per persona/tier pick, not a live tool-call log.

## What actually got tested, and what didn't

Real, live verification this session: the Python backend end-to-end via
`curl` (streaming, classification, spoken-summary condensation, code
exclusion) — and, in this same session, two real backend *routing* bugs
you caught by actually using it, root-caused and fixed: (1) "what's on my
screen" was classified to `butler` instead of `term`, because
`hi/router.py`'s persona descriptions mentioned butler's `take_screenshot`
(saves a file) but never mentioned that `term` — not butler — is the
persona with the actual screen-reading/vision tools (`hi/perception/`);
verified fixed via direct `classify()` calls covering both the original
complaint and the boundary case it risked breaking (`"what apps are
running"` correctly stays on butler). (2) once routed to `term`
correctly, the model defaulted to `read_screen` (raw OCR text) instead of
`ask_about_screen` (the actual vision model) for a general "what's on my
screen" question — fixed by tightening `term_prompt.md`'s guidance to
make `ask_about_screen` the default for open-ended screen questions and
`read_screen` the exception (verbatim text only); verified end to end by
actually invoking the real `term` agent and confirming it called
`ask_about_screen` and produced a real, accurate description of the
actual screen contents at the time.

On the Swift side: `swift build` catching and this session fixing three
genuine compile errors across the two redesign passes (a `@MainActor`
isolation issue in a script-style `main.swift`; a name collision between
a local `cornerRadius` constant and SwiftUI's `.cornerRadius()` modifier;
`.onChange(of:initial:_:)`'s two-parameter form requiring macOS 14 while
this package targets macOS 13, fixed by using the one-parameter form
instead); a real runtime crash from the bare SPM binary (`SFSpeechRecognizer`
gets constructed as a stored property at launch, and macOS hard-crashes
any process touching a TCC-gated API with no `Info.plist`
usage-description key — confirmed via the actual crash log) that's what
made the `.app` bundle + `Info.plist` step non-optional; the packaged,
ad-hoc-codesigned `.app` launching cleanly with no panel visible at
startup (confirmed via the real macOS on-screen window list — the panel
window object exists, per `KeyablePanel`'s construction, but is correctly
absent from the on-screen list until shown); and, with your help looking
at the actual screen, the menu bar status icon rendering correctly after
tracking down a frame-timing artifact that made it initially appear
invisible despite every internal AppKit signal saying it should be
visible.

**Not tested, and not testable by this session**: the actual
hotkey-triggered/menu-triggered show interaction, live microphone
capture, real transcription accuracy, typing into the field, the full
voice-or-typed round-trip through the backend, and TTS output. All of
these need either a human physically pressing keys/clicking, or
Accessibility + Microphone + Speech Recognition permission grants that
only happen through an interactive System Settings prompt — this session
has no way to drive either. AppleScript/System Events UI-automation
(used successfully elsewhere in this project, e.g. reading Safari's
current tab) was tried here too and doesn't reach this app's menu bar
item specifically — confirmed this is a real limitation of scripting
`.accessory`-policy background apps (`HiVoice` doesn't appear among
"processes whose background only is false" at all), not a bug in the
status item. **You'll hit permission prompts the first time you dictate
for real** (Accessibility is requested immediately on launch; Microphone/
Speech Recognition lazily, the first time you toggle the mic button) —
grant them, then the on-screen interaction is what still needs a real
run to confirm end to end.

## Running it

Two different workflows, deliberately kept separate — see "Why two
scripts, and why permissions kept re-prompting" below for the actual
reason this split matters, not just convenience.

### Everyday use — build once, install it, forget the scripts exist

```bash
# from the hi/ repo root
cd voice_companion
./Scripts/build_release.sh
```

Builds a release configuration, packages `hi Voice.app`, and reveals it
in Finder at `voice_companion/dist/hi Voice.app`. **Drag it into
`/Applications`**, then launch it from there going forward — Spotlight,
the Dock, or add it to Login Items to start automatically. You'll still
need `hi --voice-daemon` running separately (from the `hi/` repo root:
`uv run hi --voice-daemon`, or add it to Login Items too) — the app and
the backend are independent processes by design, and the app's menu bar
icon shows red if the backend isn't reachable. Re-run
`build_release.sh` only when you've changed the source and want to
update the installed copy (drag the new one over the old one again).

### Active development — rebuild and relaunch on every change

```bash
cd voice_companion
./Scripts/run.sh
```

Starts `hi --voice-daemon` in the background if it isn't already
running, rebuilds (debug configuration) and re-packages the app **every
single time you run it**, and opens the freshly-built copy. Fine for
iterating on the Swift source; **expect Accessibility/Microphone/Speech
Recognition permission prompts to reappear on every launch this way** —
see below for why, and use the release workflow above once you're done
iterating.

Either way, once the app is running: press Option+Space, or click the
menu bar icon and choose "Show hi Voice." Type your question and press
Return, or click the mic button to dictate into the same field first.
Press Escape or click away to close the panel — your conversation stays
in the log until you clear it (the trash icon in the tab row) or quit
the app.

### Why two scripts, and why permissions kept re-prompting

Without a paid Apple Developer ID, the only code signature available is
an **ad-hoc** one (`codesign --sign -`) — and macOS's TCC (the system
that gates Accessibility/Microphone/Speech Recognition) ties an ad-hoc
app's permission grant to the actual compiled binary, not just its
bundle identifier. Rebuild the app — even from unchanged source, since
Swift's build output isn't guaranteed byte-identical run to run — and
TCC sees "different code" and asks again. `run.sh` (via `build_app.sh`)
rebuilds and re-signs on every single invocation, which is exactly why
using it as your everyday launcher meant a fresh prompt every time.

There's no way to fully remove that constraint for local ad-hoc builds
— it's inherent to not having a real signing certificate. What actually
fixes it: **build once** (`build_release.sh`), **install the result
somewhere stable** (`/Applications`), and **never rebuild it again**
unless you're intentionally updating it. A `.app` that isn't touched
between launches keeps the exact same signature every time, and TCC's
grant sticks — verified live: launched the same release-built app
twice in a row with no rebuild in between, and `codesign`'s reported
`CDHash` was byte-for-byte identical across both launches.
