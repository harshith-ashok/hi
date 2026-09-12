"""Grounds docs's answers strictly in the user's Obsidian vault: every
question is answered by searching the whole vault for relevant notes,
citing them, and summarizing only what they say — never from the model's
own general knowledge.

hi/conversations/ (this assistant's own chat logs, shared with `term`) is
excluded from the search scope: this is about the user's actual notes, not
the assistant's memory of past conversations.
"""

from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

import hi.config as config
from hi.model_warmup import invoke_with_retry
from hi.models import fast_variant
from hi.note_preview import note_preview
from hi.tree_cache import read_tree_cache, refresh_tree_cache
from hi.vault import conversations_dir

NO_NOTES_MESSAGE = "No notes exist in the vault yet."


def _is_citable(path: Path) -> bool:
    return not path.is_relative_to(conversations_dir())


def _resolve_vault_path(path: str) -> Path:
    resolved = (config.VAULT_PATH / path).resolve()
    if not resolved.is_relative_to(config.VAULT_PATH.resolve()) or not _is_citable(resolved):
        raise ValueError(f"Invalid path: {path}")
    return resolved


@tool
def list_vault_notes() -> str:
    """List every Markdown note in the user's Obsidian vault (excluding
    this assistant's own conversation logs)."""
    notes = sorted(
        str(p.relative_to(config.VAULT_PATH)) for p in config.VAULT_PATH.rglob("*.md") if _is_citable(p)
    )
    if not notes:
        return NO_NOTES_MESSAGE
    return "\n".join(notes)


@tool
def read_vault_note(path: str) -> str:
    """Read the contents of a note anywhere in the user's Obsidian vault.

    Args:
        path: Path relative to the vault root, e.g. "concepts/Docker.md".
    """
    note_path = _resolve_vault_path(path)
    if not note_path.exists():
        return f"Note '{path}' does not exist."
    return note_path.read_text()


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    relevant_notes: list[str]


def build_vault_rag_graph(note_agent, model: BaseChatModel) -> CompiledStateGraph:
    """Wrap `note_agent` in a strict grounding pass: search the vault for
    notes relevant to the question, then hand the agent only what was
    found (or an explicit "nothing found" signal) — never the bare
    question — so it can't quietly fall back to general knowledge."""

    def select_relevant_notes(state: State) -> dict:
        notes = list_vault_notes.invoke({})
        known_notes = [] if notes == NO_NOTES_MESSAGE else notes.splitlines()
        if not known_notes:
            return {"relevant_notes": []}

        refresh_tree_cache()
        tree = read_tree_cache()

        # BLOCKERS.md #4: same fix as hi/memory_graph.py — selection used
        # to see only bare paths, never content. One preview line per
        # note makes selection content-aware at near-zero added cost.
        notes_with_preview = "\n".join(
            f"{path} — {note_preview(read_vault_note.invoke({'path': path}))}"
            for path in known_notes
        )

        question = state["messages"][-1].content
        selection_prompt = (
            "Notes in the user's Obsidian vault (path — content preview):\n"
            f"{notes_with_preview}\n\n"
            "Vault folder structure, for extra context on how notes are "
            "organized and titled:\n"
            f"{tree}\n\n"
            f"User question:\n{question}\n\n"
            "Which of the notes listed above, if any, are relevant to "
            "answering the question? Judge relevance from each note's path, "
            "filename, and folder — a folder name is itself a strong signal "
            "of what its notes are about collectively (e.g. a 'people' "
            "folder holds notes about people the user knows, even if no "
            "individual filename shares words with the question), so for a "
            "broad or aggregate question ('who do I know', 'what projects "
            "am I working on', 'list my X'), include every note under the "
            "folder that category clearly belongs to, not just ones with "
            "literal keyword overlap. Reply with only the relevant note "
            "paths, or NONE if none apply."
        )
        # A HumanMessage, not SystemMessage — see hi/memory_graph.py's
        # identical fix and its comment for the live-verified root
        # cause: this model returns an empty done_reason='load' response
        # for a SystemMessage-ONLY conversation on every single attempt,
        # not a transient cold-start retrying could ever get past. For
        # `docs` specifically this was a real, silent correctness bug,
        # not just wasted latency: an always-empty reply matches no real
        # note path via `in`, so `docs` — "a strict, whole-vault,
        # citation-only RAG assistant" per this file's own docstring —
        # would have always reported "no relevant notes found" regardless
        # of what actually exists in the vault.
        # fast_variant(model): same plain path-selection judgment call
        # as hi/memory_graph.py's identical step — reasoning on adds
        # several seconds to a call that doesn't need visible chain-of-
        # thought, and does it before docs even starts answering. See
        # hi/memory_graph.py's own comment for the measured motive.
        reply = invoke_with_retry(fast_variant(model), [HumanMessage(selection_prompt)])
        relevant_notes = [path for path in known_notes if path in reply]
        return {"relevant_notes": relevant_notes}

    def load_note_context(state: State) -> dict:
        note_paths = state["relevant_notes"]
        last_message = state["messages"][-1]

        if not note_paths:
            context = "No relevant notes were found in the vault for this question."
        else:
            sections = [
                f"### {path}\n\n{read_vault_note.invoke({'path': path})}" for path in note_paths
            ]
            context = "\n\n".join(sections)

        enriched = HumanMessage(
            content=(
                "Vault search results:\n\n"
                f"{context}\n\n"
                f"---\n\nUser question: {last_message.content}"
            )
        )
        return {"messages": [RemoveMessage(id=last_message.id), enriched]}

    graph_builder = StateGraph(State)
    graph_builder.add_node("select_relevant_notes", select_relevant_notes)
    graph_builder.add_node("load_note_context", load_note_context)
    # note_agent is embedded directly as a subgraph node (not wrapped in a
    # function that calls .invoke()) so its own token-level streaming is
    # visible to callers streaming *this* graph.
    graph_builder.add_node("agent", note_agent)

    graph_builder.add_edge(START, "select_relevant_notes")
    graph_builder.add_edge("select_relevant_notes", "load_note_context")
    graph_builder.add_edge("load_note_context", "agent")
    graph_builder.add_edge("agent", END)

    return graph_builder.compile()
