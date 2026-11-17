# 0002: Work `hi` does without being asked (2026-11-17)

Context: `hi` knew what was on the screen and in the vault but only used it when asked. The plan is in
`GAMEPLAN.md`. This records the decisions that differ from it or that are easy to get wrong.

Decisions:

1. **A run has a policy** (`hi/core/runpolicy.py`). An interactive turn has none. A background run (schedule,
   heartbeat, drop) runs under `UNATTENDED`: reads are free, anything else becomes a **proposal**
   (`hi/memory/proposals.py`) that the user approves later. The check is one middleware, `RunGuard`
   (`hi/agents/guard.py`), that every agent has and that does nothing in an interactive turn. The policy travels in
   a `ContextVar`, so one cached agent serves both kinds of turn (the plan keyed the agent cache by policy; that
   is not needed). A test runs a real LangGraph agent to prove the variable reaches the tool threads.
2. **Background runs get their own agent instance** (`turn._get_agent(..., isolated=True)`). `term` remembers the
   conversation and a "fresh" turn resets it; a background run must neither read your chat nor reset it.
3. **Background turns never join your chat.** The transcript records them with their `origin` and `history()`
   skips them; they are not written to the conversation log and nothing is learned from them (a prompt written by
   a schedule is not something you said).
4. **Proposals execute once.** `begin_execution` moves a proposal out of `created` under a lock before the tool
   runs. A proposal found `executing` after a restart becomes `failed`, never re-run. Executing a proposal runs
   under `pre_approved()`, so the tool does not ask a second time.
5. **One delivery gate** (`hi/context/inbox.py`, on the Mac): dedupe per day, one shared hourly budget, quiet
   after ignored messages. Approvals, reminders, failures and urgent messages skip the budget, never the dedupe.
   The backend reaches it through the host bridge (`post_to_inbox`); natively it calls it directly.
6. **The island answers approvals through its reply box** ("yes" / "no"), not buttons. The parsing lives in
   `inbox.answer_approval` (tested); the island only calls it. A live approval whose description was cut for
   length cannot be approved from the island, only denied.
7. **Headlines are deterministic** (`deliver.headline_from`: first heading or sentence, cleaned). Reports are asked
   to start with one, so no model call is spent on it. The plan's summarizer fallback was dropped.
8. **Screen-derived data goes only to local models** (`registry.is_local(tier)`: every model the tier could fall
   back to must be local).
9. **Search is a private SearXNG** (`searxng` compose service, pinned tag, JSON enabled, not published). A query
   containing a secret is refused, not redacted.

Consequences: `hi.automation` sits beside `agents` and may not import `hi.server` (the server passes it a
`run_turn`); `GET /health` lists jobs; `/livez` exists for Docker's healthcheck because `/health` is 503 whenever
Ollama is down. `hi --suggest-daemon` overlaps with the heartbeat and is deprecated once the heartbeat ships.
