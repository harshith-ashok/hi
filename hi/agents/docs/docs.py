from pathlib import Path

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from hi.agents.docs.vault_rag import build_vault_rag_graph, list_vault_notes, read_vault_note
from hi.config import DOCS_MODEL
from hi.vault import append_note, create_note, list_notes, read_note

model = ChatOllama(
    model=DOCS_MODEL,
    temperature=0,
)

PROMPT_PATH = Path(__file__).parent / "docs_prompt.md"

note_agent = create_agent(
    model=model,
    tools=[list_vault_notes, read_vault_note, create_note, append_note, read_note, list_notes],
    system_prompt=PROMPT_PATH.read_text(),
)

agent = build_vault_rag_graph(note_agent, model)
