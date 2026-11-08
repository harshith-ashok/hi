"""Pass-through to the user's Mac for tools that can only run there.

The backend normally runs in Docker (Linux), where "open Safari", "turn off
Bluetooth" or "read my screen" cannot work. `passthrough(tools)` swaps each such
tool for a proxy with the same name and schema that asks the host bridge
(hi/host_bridge.py, running natively on the Mac) to run the real tool. On a Mac
it returns the tools unchanged.
"""

from __future__ import annotations

import sys

import httpx
from langchain_core.tools import BaseTool, StructuredTool

import hi.config as config

# The only tools the bridge will run (it never executes arbitrary commands).
HOST_TOOLS = frozenset({
    "set_volume", "mute", "unmute", "toggle_wifi", "toggle_bluetooth", "toggle_dnd", "adjust_brightness",
    "lock_screen", "open_app", "quit_app", "list_running_apps", "take_screenshot", "read_clipboard",
    "write_clipboard", "open_url_in_browser", "observe_current_tab", "read_screen", "ask_about_screen",
    "play_music", "music_control", "now_playing", "list_playlists",
})
CALL_TIMEOUT_SECONDS = 180  # ask_about_screen waits on a vision model


def call(name: str, args: dict) -> str:
    """Run host tool `name` on the Mac; always returns text, never raises."""
    if not config.HOST_BRIDGE_TOKEN:
        return "The Mac bridge has no token yet. Start hi from your Mac terminal (`hi`) so it can set one up."
    try:
        response = httpx.post(
            f"{config.HOST_BRIDGE_URL.rstrip('/')}/tool",
            json={"name": name, "args": args},
            headers={"Authorization": f"Bearer {config.HOST_BRIDGE_TOKEN}"},
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        return f"Can't reach the Mac bridge at {config.HOST_BRIDGE_URL} ({e}). It starts with `hi` on your Mac."
    if response.status_code != 200:
        return f"Mac bridge error {response.status_code}: {response.text[:300]}"
    return response.json()["result"]


def _proxy(tool: BaseTool) -> BaseTool:
    def run_on_mac(**kwargs) -> str:
        return call(tool.name, kwargs)

    return StructuredTool.from_function(
        func=run_on_mac,
        name=tool.name,
        description=f"{tool.description} (Runs on the user's Mac.)",
        args_schema=tool.args_schema,
    )


def passthrough(tools: list[BaseTool]) -> list[BaseTool]:
    if sys.platform == "darwin":
        return tools
    return [_proxy(t) if t.name in HOST_TOOLS else t for t in tools]
