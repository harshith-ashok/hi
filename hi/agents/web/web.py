"""Web: a search-and-summarize persona built with a LangGraph ReAct agent."""

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from hi.agents.web.tools import find_image, search_wikipedia
from hi.agents.persona_voice import voiced_prompt
from hi.mcp_tools import get_mcp_tools_by_server
from hi.agents.base import make_agent

PROMPT_PATH = Path(__file__).parent / "web_prompt.md"
TOOLS = [search_wikipedia, find_image]


def build_agent(model: BaseChatModel):
    """Build a fresh web agent bound to `model`."""
    fetch = get_mcp_tools_by_server().get("fetch", [])  # read any URL as markdown, if uvx is installed
    return make_agent(model, TOOLS + fetch, system_prompt=voiced_prompt(PROMPT_PATH))

