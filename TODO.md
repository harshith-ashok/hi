# TODO — toward a Jarvis/Friday-style assistant

Order matters: reliability and latency first, because everything else is
annoying on a slow or flaky base.

## 1. Voice: speak short, show the rest

Principle: **two output channels.** The assistant *says* a short, plain
sentence and *shows* everything else (tool calls, diffs, lists, code, links).
Actions are never narrated aloud.

- [x] (via the existing `spoken_summary` event) Add a `spoken` channel separate from the visual transcript. The model
      writes the full answer for the screen plus a one-line `speak` summary
      (e.g. a `speak` tool call, or a tagged first line), and only that
      line goes to TTS.
- [x] Spoken style rules in the prompt: max ~2 sentences, plain words, no
      markdown/paths/URLs/code read out, no "I will now call tool X".
      Numbers and names are rounded or simplified ("about three hours").
- [x] Never speak tool activity. Tool calls, approvals and results render
      visually only (tinyui trace + TUI). Speech is reserved for the outcome
      ("Done, I saved it to your ideas note") or a question.
- [x] Visual action feedback in tinyui/TUI: status pill (listening ·
      thinking · acting · speaking), tool-call chips, approval card.
- [x] TTS is **Phonon** (Gradium's on-device model, "xn-ptts") served by
      Ollama: `ollama pull phonon`; backend `/tts` -> Ollama
      `/v1/audio/speech` (`hi/tts_ollama.py`). Falls back to Kokoro on
      native installs, then to the browser's own voice in tinyui.
- [ ] Voice picker (Ollama lists ~35 voices; `TTS_VOICE`, default `default`)
      in tinyui settings.
- [ ] Speak per sentence as the answer streams (measure time-to-first-audio:
      a 3s clip took about 1s to synthesize on a first test).
- [ ] Voice cloning from a short reference clip, if Ollama exposes it.
- [ ] Switch the wake daemon (`hi/wake.py`) from `say` to Phonon.

## 1b. Voice input: whisper.cpp STT for quick conversations

Status: backend + tinyui written; needs a live test with a real
`whisper-server` (`brew install whisper-cpp`, then
`whisper-server -m ggml-base.en.bin --port 8080`) and a real mic.

Goal: press a key (or click the mic in tinyui), talk, get a reply — no
typing, no wake word needed for short exchanges.

- [ ] Run **whisper.cpp** natively on the Mac (Metal), not in Docker. Use
      `whisper-server` (HTTP) or `whisper-cli`, with a small English model
      (`base.en` / `small.en`); measure latency per utterance.
- [ ] `STT_ENGINE=whispercpp|faster-whisper` setting; today
      `WHISPER_MODEL` / faster-whisper is used by the wake daemon. Keep one
      `transcribe(audio) -> text` function so engines stay swappable.
- [x] Backend `POST /stt` (audio in, text out) that forwards to the native
      whisper.cpp server; the containerized backend reaches it via
      `host.docker.internal`.
- [x] tinyui: mic button (`[mic]`, no push-to-talk key yet). Record with `MediaRecorder`,
      show live state (listening · transcribing), put the transcript in the
      input and send it.
- [x] Voice activity detection to end the utterance automatically (silence
      ~700ms), plus a hard max length.
- [x] Quick-conversation mode: after a reply, keep the mic open a few
      seconds for a follow-up without pressing again.
- [x] Transcript is always shown on screen before/while the agent acts, so
      mishears are visible; short destructive commands still need approval.
- [x] Pair with the speak-short TTS channel in section 1 for a full
      voice loop (mic → whisper.cpp → agent → short spoken reply + visuals).

## 1c. Rambler: structure speech before it reaches the agent
- [x] `hi/rambler.py` + `POST /ramble`: haiku-tier (reasoning off) cleanup of
      a transcript: drops filler, applies self-corrections, outputs one
      sentence or Goal/Details/Steps. Under 8 words skips the model.
- [x] tinyui `[ramble]` toggle (on by default): voice input is structured,
      the original is shown as a "heard: ..." note.
- [ ] Show the structured version for approval before sending (optional).
- [ ] Feed recent conversation to the rambler so "do that again" resolves.
- [ ] Rambler for typed text too (`/ramble` on long pasted messages).
- [ ] Eval: ~20 messy transcripts, check no facts invented.

## 1d. Tool overhaul (less overlap, less overthinking)
- [x] `hi/toolkit.py`: every tool has a group + priority (P1 always, P2 on
      keyword match, P3 only via `more_tools(group)`); duplicates hidden.
      `term` went from 134 registered tools to 10 visible on a plain turn.
- [x] term system prompt follows the same selection (16.8 KB -> 8.9 KB on a
      plain turn); sections only appear when their group is on offer.
- [x] butler uses the selector (15 visible, tasks/MCP setup on demand).
- [x] `fetch` MCP (uvx) added for the web persona.
- [x] GitHub writes (merge/push/delete/fork) and advanced Playwright are P3.
- [ ] Filesystem MCP: NOT adopted. Its writes skip `confirm_destructive`;
      native write/edit keep the y/N gate and previews. Revisit if MCP
      gets a confirm hook.
- [ ] Decide on docs persona (7 tools, kept as is) and merging
      `list_vault_notes`/`list_notes`, `read_vault_note`/`read_note`.
- [x] GitHub + fetch MCP servers work in Docker (binaries in the image; token
      forwarded from ~/.hi/.env by `hi`). Voice TTS = phonon via Ollama.
- [ ] n8n MCP server fails to connect ("unhandled errors in a TaskGroup").
- [ ] Keyword rules miss paraphrases; log which group each turn unlocked and
      tune, or fall back to a haiku selector for ambiguous turns.
- [ ] Models sometimes call a group name as a tool (`github`); handle by
      returning the unlock hint from a no-op alias.
- [ ] Shrink the remaining term prompt (core sections are still long).

## 1e. The vault as the agent's memory (Hermes-style wrapper)
- [x] `hi/journal.py`: every turn is journaled to `<vault>/hi/journal/YYYY-MM-DD.md`
      by the wrapper (ask, each tool call + result, answer, time, `[[links]]` to
      notes touched); approvals, settings changes and errors too.
- [x] `hi/vault_context.py`: each turn the term prompt gets recent journal
      activity + the notes best matching the message (name/path matching,
      no embeddings), plus `search_vault` / `read_vault_note` tools.
- [x] Docker uses the real vault: `hi` mounts `VAULT_PATH` at `/vault`.
- [x] Memory extraction (`hi/memory.py`): after each turn a haiku-tier model
      appends durable preferences/facts/projects/people/decisions to
      `hi/memory/memory.md` (background thread; sees only what you said, the
      answer and tool names; secrets filtered; deduped). `MEMORY_EXTRACTION=off`.
- [x] Reflection agent (`hi/reflection_agent.py`): yesterday's journal ->
      `hi/reflections/YYYY-MM-DD.md` (summary, decisions, open loops, lessons),
      started on the first turn of a day; then memory consolidation with a
      backup in `hi/memory/history/`. `REFLECTION=off`. Open loops feed context.
- [x] tinyui `memory` view; `GET /memory`.
- [ ] Extraction quality: eval on ~30 real turns; check false positives
      (the model remembers things the user only asked about).
- [ ] Contradictions: consolidation drops stale items only if the model sees
      them; verify on real data. Add an "ignored"/"forget" list.
- [ ] A `forget` tool and a "what do you remember about X" answer path.
- [ ] Reflection for non-HTTP entry points once they journal.
- [ ] Skills, Hermes-style: when a multi-step task succeeds, save the
      procedure as `hi/skills/<name>.md` and load matching skills as context.
- [ ] Journal the other entry points: wake daemon, TUI, CLI repl (only the
      HTTP server records turns today), voice-mode raw transcript vs rambler.
- [ ] Context from content, not just names (grep headings/tags), limited to
      files that are downloaded locally (iCloud may offload the rest).
- [ ] Give `docs`, `butler`, `web` the same context block.
- [ ] A journal view in tinyui; link journal entries from History.
- [ ] iCloud + Obsidian Git both touch this vault: check the journal does not
      create merge noise (one file per day, append-only).

## 2. Reliability
- [ ] Test the orchestrated-plan path end to end.
- [ ] Test a real OpenRouter chat with a valid key.
- [ ] Test TUI approval popup and agent flows.
- [ ] Eval set: ~30 realistic requests, run per model, track success rate.
- [ ] Retries and graceful fallback to another model on tool-call errors.

## 3. Latency
- [x] Per-turn timing trace (router, first token, each tool, total).
- [x] Router: keyword rules + sticky follow-ups skip the model call
      (`hi/router.py fast_route`; measured route 0.0s). Ambiguous turns still
      use the haiku classifier.
- [x] Stream first sentence to TTS as soon as it is complete (`hi/speaker.py`:
      a speaker runs in parallel with the main model, emits `spoken_chunk`).
- [x] Keep Ollama models warm.

## 4. Proactivity
- [x] Interruption budget: at most N unprompted messages per hour.
- [ ] Context model: calendar, active project, what was ignored before.
- [ ] Learn from dismissals; suggest less after being ignored.
- [ ] Proactive output is visual first, spoken only when urgent.

## 5. Memory (intentionally deferred by CLAUDE.md)
- [ ] Reflection pass that turns conversations into knowledge notes.
- [ ] Retrieval of relevant notes without embeddings first (titles, tags).
- [ ] Revisit embeddings only if that proves too weak.

## 6. Reach
- [ ] Calendar, email, music, home control (one integration at a time).
- [ ] Permission tiers beyond destructive confirmation, e.g. "send as me"
      always asks.
- [ ] Phone/remote access over Tailscale.

## 7. Cleanup
- [ ] Decide whether to remove slash commands from the TUI.
- [ ] Commit the current work; `frontend/` is still deleted in the tree.
- [ ] Resolve the port 5173 clash with checklister (use `HI_WEB_PORT`).
