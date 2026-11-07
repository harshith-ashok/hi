"""Butler: a macOS system-control persona built with a LangGraph ReAct agent."""

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from hi.agents.persona_voice import voiced_prompt
from hi.toolkit import ToolSelector
from hi.agents.butler.mac_control import (
    adjust_brightness,
    list_running_apps,
    lock_screen,
    mute,
    open_app,
    quit_app,
    read_clipboard,
    set_volume,
    take_screenshot,
    toggle_bluetooth,
    toggle_dnd,
    toggle_wifi,
    unmute,
    write_clipboard,
)
from hi.agents.butler.todo import add_task, capture_note, complete_task, list_tasks, remove_task
from hi.browser import open_url_in_browser
from hi.chat_model import make_chat_model
from hi.config import BUTLER_MODEL
from hi.host import passthrough
from hi.mcp_install import configure_mcp_server, configure_n8n_server, list_available_mcp_servers

PROMPT_PATH = Path(__file__).parent / "butler_prompt.md"
TOOLS = passthrough([
    toggle_bluetooth,
    open_app,
    open_url_in_browser,
    adjust_brightness,
    lock_screen,
    add_task,
    capture_note,
    complete_task,
    remove_task,
    list_tasks,
    set_volume,
    mute,
    unmute,
    toggle_wifi,
    toggle_dnd,
    take_screenshot,
    read_clipboard,
    write_clipboard,
    list_running_apps,
    quit_app,
    list_available_mcp_servers,
    configure_mcp_server,
    configure_n8n_server,
])


def build_agent(model: BaseChatModel):
    """Build a fresh butler agent bound to `model` — used directly below
    for the default BUTLER_MODEL instance, and by hi/router.py to build one
    on a router-selected tier instead."""
    selector = ToolSelector(TOOLS, persona_groups={"mac", "tasks", "mcp_setup"})
    return create_agent(
        model=model, tools=TOOLS + [selector.more_tools], system_prompt=voiced_prompt(PROMPT_PATH), middleware=[selector]
    )


model = make_chat_model(BUTLER_MODEL, temperature=0, keep_alive="30m")
agent = build_agent(model)
