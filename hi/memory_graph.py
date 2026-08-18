"""LangGraph wrapper that grounds `term`'s answers in its own hi/knowledge/
and hi/conversations/ memory: before the underlying ReAct agent runs, it
asks the model which existing notes/conversation logs are relevant to the
question, folds their content into the prompt, and refreshes the tree-cache
snapshot of the vault's structure as extra context for that selection.

`term` can still fall back to general knowledge when nothing relevant is
found — unlike `docs` (see hi/agents/docs/vault_rag.py), which is a strict,
whole-vault, citation-only RAG assistant with its own graph.
"""

from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from hi.model_warmup import invoke_with_retry
from hi.tree_cache import read_tree_cache, refresh_tree_cache
from hi.vault import KNOWLEDGE_DIR, list_conversations, list_notes, read_conversation, read_note

PREFERENCES_PATH = "preferences.md"


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    relevant_notes: list[str]
    relevant_logs: list[str]


def build_memory_graph(note_agent, model: BaseChatModel) -> CompiledStateGraph:
    """Wrap `note_agent` (a ReAct agent with the shared vault tools) in a
    grounding pass: select relevant notes/logs, load their content into the
    question, then hand off to the agent."""

    def select_relevant_notes(state: State) -> dict:
        notes = list_notes.invoke({})
        logs = list_conversations.invoke({})

        known_notes = [] if notes == "No notes exist yet." else notes.splitlines()
        known_logs = [] if logs == "No conversation logs exist yet." else logs.splitlines()
        if not known_notes and not known_logs:
            return {"relevant_notes": [], "relevant_logs": []}

        refresh_tree_cache()
        tree = read_tree_cache()

        question = state["messages"][-1].content
        selection_prompt = (
            "Knowledge notes (paths under hi/knowledge/):\n"
            f"{notes}\n\n"
            "Conversation logs (dates under hi/conversations/):\n"
            f"{logs}\n\n"
            "Vault folder structure, for extra context on how notes are "
            "organized and titled:\n"
            f"{tree}\n\n"
            f"User question:\n{question}\n\n"
            "Which of the knowledge notes and/or conversation logs listed "
            "above, if any, contain context relevant to answering the "
            "question? Reply with only the relevant note paths and/or "
            "dates, or NONE if none apply."
        )
        reply = invoke_with_retry(model, [SystemMessage(selection_prompt)])

        relevant_notes = [path for path in known_notes if path in reply]
        relevant_logs = [d for d in known_logs if d in reply]
        return {"relevant_notes": relevant_notes, "relevant_logs": relevant_logs}

    def load_note_context(state: State) -> dict:
        note_paths = [p for p in state["relevant_notes"] if p != PREFERENCES_PATH]
        log_dates = state["relevant_logs"]

        sections = []
        # Always included, not just when the relevance-selection step
        # happens to surface it — selection is keyword/topic based and
        # won't reliably match an unrelated question to a general
        # preferences note, but preferences should apply regardless of
        # what the question is about.
        if (KNOWLEDGE_DIR / PREFERENCES_PATH).exists():
            sections.append(
                f"### knowledge/{PREFERENCES_PATH} (always included)\n\n"
                f"{read_note.invoke({'path': PREFERENCES_PATH})}"
            )
        sections += [
            f"### knowledge/{path}\n\n{read_note.invoke({'path': path})}" for path in note_paths
        ]
        sections += [
            f"### conversations/{d}\n\n{read_conversation.invoke({'date': d})}"
            for d in log_dates
        ]
        if not sections:
            return {}
        context = "\n\n".join(sections)

        last_message = state["messages"][-1]
        enriched = HumanMessage(
            content=(
                "Relevant context from memory:\n\n"
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
    # visible to callers streaming *this* graph — verified that a wrapper
    # function only surfaces whole-message chunks, not real token deltas,
    # even with the run config threaded through.
    graph_builder.add_node("agent", note_agent)

    graph_builder.add_edge(START, "select_relevant_notes")
    graph_builder.add_edge("select_relevant_notes", "load_note_context")
    graph_builder.add_edge("load_note_context", "agent")
    graph_builder.add_edge("agent", END)

    return graph_builder.compile()
