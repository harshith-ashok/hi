# Trying out `hi` — commands and prompts worth running

A curated tour, not a full manual (see `README.md` for that) — copy-paste
these into a real `hi` session to see what's actually built, roughly in
the order that shows the most range for the least typing.

Two ways in, same backend, same memory:

```bash
cd ~/Projects/whatever   # any directory — term/butler ground answers in it
hi                       # auto-routing mode, right-hand tmux pane
hi --term                # force a specific persona instead (--butler/--docs/--web also work)
```

or open **hi Voice.app** (the native app) for a proper window: sidebar
with New Chat / conversation history / Settings, plus the Option+Space
quick-access popup from anywhere. Everything below works from either —
the terminal and the app share the exact same backend.

---

## 1. Instant commands — zero model calls, sub-10ms

These skip classification *and* generation entirely, calling the real
tool directly. Say them exactly (a real question wearing one of these as
its first word still routes normally):

```
hi
thanks
show my tasks
what apps are running
mute
unmute
set volume to 40
turn on wifi
take a screenshot
quit safari
add task: reply to the email
```

## 2. Auto-routing — watch it pick the right persona and model tier

No flag needed — just ask. Each of these should land on a different
persona/tier without you saying which:

```
what's the wifi status and can you turn on do not disturb
what do my notes say about <a real project name in your vault>
what's the population of Japan
read the README in this directory and tell me what it does
```

## 3. `docs` — strict, cited vault search

Never answers from general knowledge — says so plainly if nothing's
found. Try a note whose *filename* shares no words with the question
(content-preview grounding should still surface it):

```
hi --docs
> what are my interests
> what do I know about <a real project you've saved to the vault>
> summarize everything I know about <a topic across multiple notes>
```

## 4. `term` — real filesystem access, not just shell guessing

```
hi --term
> read the README in this project and summarize it
> find the file that handles the MCP client setup
> save this project to the vault
> what's on my screen right now
> write a script that prints the first 20 Fibonacci numbers, run it, and confirm the output
> fix the failing test and show me the diff
```

The last two run in a real Docker sandbox with no network access, verify
real output, and retry with the actual failure text if wrong — not a
one-shot guess.

## 5. `butler` — macOS control + tasks

```
hi --butler
> mark "buy milk" as done
> what's using my clipboard right now
> open basecamp     # (a saved dev flow, if you have one — or "save this as a dev flow called X")
```

## 6. Multi-agent orchestration — a real parallel task DAG

A genuinely multi-part request decomposes into independent subagents
that actually run *concurrently*, not sequentially — watch the tmux pane
print live `[t1: web] starting…` / `[t2: web] starting…` status lines:

```
search wikipedia for Docker and separately for Kubernetes, then save a note comparing them
check my deadlines, then look up what's new in Python 3.14, and tell me if any of my notes are stale
```

Afterward:

```
show me how you did that
```

replays the run's own trace note — which subagent did what, real tool
calls made, dependency order.

Tune how aggressively it plans:

```
budget
budget quick
budget thorough
```

## 7. Destructive actions — real confirmation, not blind execution

```
hi --term
> delete the file /tmp/some_test_file.txt
```

You'll see a y/N prompt — and if it's flagged as genuinely risky
(broad path, chained commands), a second cheap-tier model's own concern
line appended before you decide. From an orchestrated run instead of a
live pane, the same action shows up as a real inline **Approve/Deny**
card in the native app (or `curl` commands printed to the terminal) —
never silently done, never silently skipped.

## 8. Conversational MCP setup

```
hi --butler
> what MCP servers are available and which are already set up
> configure the github MCP server, here's my token: <your real PAT>
```

Writes straight to `~/.hi/.env` instead of you hand-editing it — gated
by the same y/N confirmation as any other destructive-ish action.

## 9. The daily flow — things worth running once a session

```
hi
```

opens with a real briefing (pending tasks, deadlines, idle repos,
application follow-ups) and one concrete suggested action — say **yes**
to just run it. Also worth asking directly:

```
what should I work on
open today's leetcode problem
```

`what should I work on` gives exactly one recommendation, not a list —
say "not that" and it picks something else, excluding what you just
turned down.

## 10. Voice + the native app

- **Dictate**: Ctrl-V in the terminal, or the mic button in the app —
  transcribes locally, drops the text in for you to edit before sending.
- **Hands-free**: `hi --wake-daemon` in its own terminal, then just say
  "Hey Jarvis" followed by your question — no typing, no button, spoken
  answer back.
- **In the app**: check **Settings** (model tiers + vault path, written
  straight to `~/.hi/.env`) and click through **History** in the sidebar
  to revisit a past day's real conversation, nicely formatted.

## 11. Turn it off and watch nothing break

```
hi --docs
> what do my notes say about something that genuinely isn't in your vault
```

Should get a plain "couldn't find anything about that" — never a
confident, made-up answer. That honesty is the point of `docs` existing
at all.

---

**A good 5-minute version of this whole list**, if you're short on time:
§1 (a couple instant commands), §3 or §4 (one grounded question against
your real vault), §6 (the orchestration prompt — this is the one that
looks the most like magic), §7 (the confirm prompt), done.
