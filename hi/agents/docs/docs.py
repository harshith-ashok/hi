from pathlib import Path

from langchain_core.language_models import BaseChatModel
from hi.agents.docs.vault_rag import build_vault_rag_graph, list_vault_notes, read_vault_note
from hi.agents.persona_voice import voiced_prompt
from hi.agents.base import make_agent
from hi.memory.vault import append_note, create_note, list_notes, read_note
from hi.memory.widgets import recall_widget

PROMPT_PATH = Path(__file__).parent / "docs_prompt.md"
TOOLS = [list_vault_notes, read_vault_note, create_note, append_note, read_note, list_notes, recall_widget]


def build_agent(model: BaseChatModel):
    """Build a fresh docs agent bound to `model`."""
    note_agent = make_agent(model, TOOLS, system_prompt=voiced_prompt(PROMPT_PATH))
    return build_vault_rag_graph(note_agent, model)

