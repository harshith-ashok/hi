from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from hi.agents.docs.vault_rag import build_vault_rag_graph, list_vault_notes, read_vault_note
from hi.config import DOCS_MODEL
from hi.vault import append_note, create_note, list_notes, read_note

PROMPT_PATH = Path(__file__).parent / "docs_prompt.md"
TOOLS = [list_vault_notes, read_vault_note, create_note, append_note, read_note, list_notes]


def build_agent(model: BaseChatModel):
    """Build a fresh docs agent bound to `model` — used directly below for
    the default DOCS_MODEL instance, and by hi/router.py to build one on a
    router-selected tier instead."""
    note_agent = create_agent(model=model, tools=TOOLS, system_prompt=PROMPT_PATH.read_text())
    return build_vault_rag_graph(note_agent, model)


model = ChatOllama(
    model=DOCS_MODEL,
    temperature=0,
    keep_alive="30m",
)
agent = build_agent(model)
