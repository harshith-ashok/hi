"""Butler: a macOS system-control persona built with a LangGraph ReAct agent."""

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from hi.agents.persona_voice import voiced_prompt
from hi.toolkit import ToolSelector
from hi.agents.butler.mac_control import (
    adjust_brightness,
    resize_window,
    scale_window,
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
from hi.agents.butler.music import list_playlists, music_control, now_playing, play_music
from hi.agents.butler.timers import cancel_timer, list_timers, set_timer
from hi.agents.butler.todo import add_task, capture_note, complete_task, list_tasks, remove_task
from hi.browser import open_url_in_browser
from hi.agents.base import make_agent
from hi.agents.web.search import web_search
from hi.host import passthrough
from hi.mcp_install import configure_mcp_server, configure_n8n_server, list_available_mcp_servers

PROMPT_PATH = Path(__file__).parent / "butler_prompt.md"
TOOLS = passthrough([
    play_music,
    music_control,
    now_playing,
    list_playlists,
    toggle_bluetooth,
    set_timer,
    list_timers,
    cancel_timer,
    open_app,
    open_url_in_browser,
    adjust_brightness,
    resize_window,
    scale_window,
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
    web_search,
])


def build_agent(model: BaseChatModel):
    """Build a fresh butler agent bound to `model`."""
    selector = ToolSelector(TOOLS, persona_groups={"mac", "tasks", "mcp_setup", "search"})
    return make_agent(model, TOOLS, system_prompt=voiced_prompt(PROMPT_PATH), selector=selector)

