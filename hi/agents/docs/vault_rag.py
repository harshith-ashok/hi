"""Grounds docs's answers strictly in the user's Obsidian vault: every
question is answered by searching the whole vault for relevant notes,
citing them, and summarizing only what they say — never from the model's
own general knowledge.

hi/conversations/ (this assistant's own chat logs, shared with `code`) is
excluded from the search scope: this is about the user's actual notes, not
the assistant's memory of past conversations.
"""

from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from hi.config import VAULT_PATH
from hi.model_warmup import invoke_with_retry
from hi.tree_cache import read_tree_cache, refresh_tree_cache
from hi.vault import CONVERSATIONS_DIR

NO_NOTES_MESSAGE = "No notes exist in the vault yet."


def _is_citable(path: Path) -> bool:
    return not path.is_relative_to(CONVERSATIONS_DIR)


def _resolve_vault_path(path: str) -> Path:
    resolved = (VAULT_PATH / path).resolve()
    if not resolved.is_relative_to(VAULT_PATH.resolve()) or not _is_citable(resolved):
        raise ValueError(f"Invalid path: {path}")
    return resolved


@tool
def list_vault_notes() -> str:
    """List every Markdown note in the user's Obsidian vault (excluding
    this assistant's own conversation logs)."""
    notes = sorted(
        str(p.relative_to(VAULT_PATH)) for p in VAULT_PATH.rglob("*.md") if _is_citable(p)
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

        question = state["messages"][-1].content
        selection_prompt = (
            "Notes in the user's Obsidian vault (paths relative to the vault root):\n"
            f"{notes}\n\n"
            "Vault folder structure, for extra context on how notes are "
            "organized and titled:\n"
            f"{tree}\n\n"
            f"User question:\n{question}\n\n"
            "Which of the notes listed above, if any, are relevant to "
            "answering the question? Judge relevance from each note's path, "
            "filename, and folder. Reply with only the relevant note paths, "
            "or NONE if none apply."
        )
        reply = invoke_with_retry(model, [SystemMessage(selection_prompt)])
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

    def run_agent(state: State, config: RunnableConfig) -> dict:
        result = note_agent.invoke({"messages": state["messages"]}, config)
        return {"messages": result["messages"]}

    graph_builder = StateGraph(State)
    graph_builder.add_node("select_relevant_notes", select_relevant_notes)
    graph_builder.add_node("load_note_context", load_note_context)
    graph_builder.add_node("agent", run_agent)

    graph_builder.add_edge(START, "select_relevant_notes")
    graph_builder.add_edge("select_relevant_notes", "load_note_context")
    graph_builder.add_edge("load_note_context", "agent")
    graph_builder.add_edge("agent", END)

    return graph_builder.compile()
