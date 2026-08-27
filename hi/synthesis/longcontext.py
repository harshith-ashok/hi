"""Long-context synthesis mode (TODO.md Phase 14, `BLOCKERS.md` ->
"Suggested feature improvements" E): a complement to
`hi/memory_graph.py`'s existing grounding graph, not a replacement for
it. That graph is built for point-lookup questions — it asks a model
which *specific* notes/logs look relevant to *this* question, then loads
only those. That's the right shape for "what did I decide about X", but
the wrong shape for "summarize everything in my vault" / "find patterns
across all my notes" — a relevance-selection step is actively the wrong
tool there, since the whole point is *everything*, not a relevant
subset.

This reads every note (and, opt-in, every conversation log) in full and
hands it all to one model call — genuinely long-context, not selective.
Bounded by a real character cap (`_MAX_CONTEXT_CHARS`) rather than an
assumed-infinite context window; if the vault is larger than that, the
truncation is stated plainly in the result rather than silently
answering from a partial view as if it were the whole thing.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.vault import (
    CONVERSATIONS_DIR,
    KNOWLEDGE_DIR,
    list_conversations,
    list_notes,
    read_conversation,
    read_note,
)

# A real, generous ceiling — not a guess at "the" context window, since
# that varies per cloud model and isn't reliably introspectable here.
# Comfortably fits a personal vault's worth of Markdown notes; if it's
# ever exceeded, the truncation is reported to the caller rather than
# silently dropped.
_MAX_CONTEXT_CHARS = 300_000


def _gather_notes() -> str:
    listing = list_notes.invoke({})
    if listing == "No notes exist yet.":
        return ""
    paths = listing.splitlines()
    sections = [f"### knowledge/{path}\n\n{read_note.invoke({'path': path})}" for path in paths]
    return "\n\n".join(sections)


def _gather_conversations() -> str:
    listing = list_conversations.invoke({})
    if listing == "No conversation logs exist yet.":
        return ""
    dates = listing.splitlines()
    sections = [
        f"### conversations/{d}\n\n{read_conversation.invoke({'date': d})}" for d in dates
    ]
    return "\n\n".join(sections)


def synthesize_across_vault(question: str, include_conversations: bool = False) -> str:
    """Reads the whole vault (every knowledge note, and every
    conversation log if `include_conversations`) and answers `question`
    against all of it in one real model call — for "summarize
    everything" / "find patterns across all my notes" style questions
    that a relevance-selecting retrieval step would wrongly narrow down.
    """
    if not KNOWLEDGE_DIR.exists() and not CONVERSATIONS_DIR.exists():
        return "The vault has no notes or conversation logs yet — nothing to synthesize."

    sections = [_gather_notes()]
    if include_conversations:
        sections.append(_gather_conversations())
    context = "\n\n".join(s for s in sections if s)
    if not context.strip():
        return "The vault has no notes yet — nothing to synthesize."

    truncated = len(context) > _MAX_CONTEXT_CHARS
    if truncated:
        context = context[:_MAX_CONTEXT_CHARS]

    prompt = (
        "Below is the full content of the user's personal knowledge "
        "vault" + (" and conversation history" if include_conversations else "") + ". "
        "Answer the question by synthesizing across ALL of it — find real "
        "patterns, connections, or a genuine summary, not just the first "
        "thing that looks relevant. Be specific: reference actual notes/"
        "content, don't speak in generalities.\n\n"
        f"Question: {question}\n\n"
        f"Full vault content:\n{context}"
    )
    model = get_tier_model("opus")
    answer = invoke_with_retry(model, [HumanMessage(prompt)])
    if truncated:
        answer += (
            f"\n\n(Note: the vault is larger than this tool's {_MAX_CONTEXT_CHARS:,}-char "
            "limit — this answer is based on a truncated view, not the complete vault.)"
        )
    return answer


@tool
def synthesize_vault(question: str, include_conversations: bool = False) -> str:
    """Answer a "summarize everything" / "find patterns across all my
    notes" style question by reading the ENTIRE vault (every knowledge
    note, and every conversation log if include_conversations=True) in
    one real model call — not a relevance-selected subset. Use this
    instead of relying on normal grounding when the question is
    genuinely about the whole vault, not a specific note/topic (for a
    specific-topic question, normal grounding already handles it better
    and faster). Can be slow on a large vault; only reach for it when
    the question actually needs everything.

    Args:
        question: What to find/summarize across the whole vault.
        include_conversations: Also include every conversation log, not
            just knowledge notes. Off by default (logs can be large and
            usually aren't what "my notes" means).
    """
    return synthesize_across_vault(question, include_conversations)
