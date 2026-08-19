"""Generalizes hi/agents/term/danger.py's shell-command-only destructive
gate into a reusable confirm-before-acting helper for non-shell tool
actions — deleting a task, a person's note, quitting an app — that
previously had no gate at all. Three tiers, though only one needs code:

- read-only: no gate (list/get/read tools)
- reversible: no gate either — a vault file mutation (add/complete a
  task, append a note) is trivially undoable by editing the file back,
  so a confirmation prompt would just be friction with no real safety
  payoff
- destructive: gated via confirm_destructive() below — same y/N UX as
  hi/agents/term/term.py's run_shell_command, reused here instead of
  duplicated, for anything hard to casually undo (deleting a note
  outright, quitting a running app)

Shell commands keep using danger.py's own regex-based looks_destructive()
to DETECT a destructive command — that's already tuned for command
syntax specifically, not reimplemented here — but now share this same
confirm_destructive() for the actual confirmation UX, rather than
duplicating a second inline input() prompt (TODO.md Phase 17).

confirm_destructive() itself is orchestrator-aware (Phase 17): a
destructive action requested by a normal interactive turn still blocks
on input() in the terminal the user is actually watching, unchanged —
but one requested by an orchestrated subagent
(hi/orchestrator/graph.py) routes to hi/orchestrator/pending_actions.py's
async-safe approval queue instead, since there's no terminal pane a
subagent's own confirmation prompt could sensibly block in (the REPL's
terminal is itself synchronously blocked waiting on the whole DAG at
that point — the actual reason this split exists).
"""

from __future__ import annotations


def confirm_destructive(description: str) -> bool:
    """Pause for a y/N confirmation before a destructive action —
    or, from inside an orchestrated subagent, queue it for asynchronous
    approval instead (see module docstring).

    Args:
        description: What's about to happen, e.g. "delete the note for Dean Haidt".
    """
    from hi.orchestrator.pending_actions import is_orchestrated_context, wait_for_approval

    if is_orchestrated_context():
        return wait_for_approval(description)

    print(f"\nAbout to: {description}")
    confirm = input("Proceed? [y/N] ").strip().lower()
    return confirm in ("y", "yes")
