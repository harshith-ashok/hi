from pathlib import Path
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from dev_flow_tool import open_dev_flow
from tools import (
    append_note,
    create_note,
    list_conversations,
    list_notes,
    read_conversation,
    read_note,
)

model = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0,
)

PROMPT_PATH = Path(__file__).parent / "code_prompt.md"

note_agent = create_agent(
    model=model,
    tools=[
        create_note,
        append_note,
        read_note,
        list_notes,
        list_conversations,
        read_conversation,
        open_dev_flow,
    ],
    system_prompt=PROMPT_PATH.read_text(),
)


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    relevant_notes: list[str]
    relevant_logs: list[str]


def select_relevant_notes(state: State) -> dict:
    """Ask the model which existing notes and/or conversation logs are relevant."""
    notes = list_notes.invoke({})
    logs = list_conversations.invoke({})

    known_notes = [] if notes == "No notes exist yet." else notes.splitlines()
    known_logs = [] if logs == "No conversation logs exist yet." else logs.splitlines()
    if not known_notes and not known_logs:
        return {"relevant_notes": [], "relevant_logs": []}

    question = state["messages"][-1].content
    selection_prompt = (
        "Knowledge notes (paths under memory/knowledge/):\n"
        f"{notes}\n\n"
        "Conversation logs (dates under memory/conversations/):\n"
        f"{logs}\n\n"
        f"User question:\n{question}\n\n"
        "Which of these, if any, contain context relevant to answering the "
        "question? Reply with only the relevant note paths and/or dates, or "
        "NONE if none apply."
    )
    reply = model.invoke([SystemMessage(selection_prompt)]).content

    relevant_notes = [path for path in known_notes if path in reply]
    relevant_logs = [d for d in known_logs if d in reply]
    return {"relevant_notes": relevant_notes, "relevant_logs": relevant_logs}


def load_note_context(state: State) -> dict:
    """Read the selected notes/logs and fold their content into the user's question."""
    note_paths = state["relevant_notes"]
    log_dates = state["relevant_logs"]
    if not note_paths and not log_dates:
        return {}

    sections = [
        f"### knowledge/{path}\n\n{read_note.invoke({'path': path})}" for path in note_paths
    ]
    sections += [
        f"### conversations/{d}\n\n{read_conversation.invoke({'date': d})}" for d in log_dates
    ]
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

agent = graph_builder.compile()
