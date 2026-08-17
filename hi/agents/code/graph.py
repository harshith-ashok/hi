from pathlib import Path

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from hi.agents.code.dev_flow_tool import open_dev_flow
from hi.config import CODE_MODEL
from hi.memory_graph import build_memory_graph
from hi.vault import (
    append_note,
    create_note,
    list_conversations,
    list_notes,
    read_conversation,
    read_note,
)

model = ChatOllama(
    model=CODE_MODEL,
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

agent = build_memory_graph(note_agent, model)
