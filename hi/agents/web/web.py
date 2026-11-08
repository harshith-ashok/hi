"""Web: a search-and-summarize persona built with a LangGraph ReAct agent."""

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from hi.agents.web.tools import find_image, search_wikipedia
from hi.agents.persona_voice import voiced_prompt
from hi.mcp_tools import get_mcp_tools_by_server
from hi.chat_model import make_chat_model
from hi.config import WEB_MODEL

PROMPT_PATH = Path(__file__).parent / "web_prompt.md"
TOOLS = [search_wikipedia, find_image]


def build_agent(model: BaseChatModel):
    """Build a fresh web agent bound to `model` — used directly below for
    the default WEB_MODEL instance, and by hi/router.py to build one on a
    router-selected tier instead."""
    fetch = get_mcp_tools_by_server().get("fetch", [])  # read any URL as markdown, if uvx is installed
    return create_agent(model=model, tools=TOOLS + fetch, system_prompt=voiced_prompt(PROMPT_PATH))


model = make_chat_model(WEB_MODEL, temperature=0, keep_alive="30m")
agent = build_agent(model)
