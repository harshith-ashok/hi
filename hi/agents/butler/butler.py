"""Butler: a macOS system-control persona built with a LangGraph ReAct agent."""

import shutil
import subprocess
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from hi.agents.butler.mac_control import (
    list_running_apps,
    mute,
    quit_app,
    read_clipboard,
    set_volume,
    take_screenshot,
    toggle_dnd,
    toggle_wifi,
    unmute,
    write_clipboard,
)
from hi.agents.butler.todo import add_task, capture_note, complete_task, list_tasks, remove_task
from hi.browser import open_url_in_browser
from hi.chat_model import make_chat_model
from hi.config import BUTLER_MODEL
from hi.mcp_install import configure_mcp_server, list_available_mcp_servers

BRIGHTNESS_KEY_CODES = {"up": "144", "down": "145"}


@tool
def toggle_bluetooth(state: str) -> str:
    """Turn Bluetooth on or off.

    Requires the third-party `blueutil` CLI (macOS has no first-party tool
    for this). Install it with `brew install blueutil` if missing.

    Args:
        state: Either "on" or "off".
    """
    if state not in ("on", "off"):
        return f"Invalid state '{state}'. Use 'on' or 'off'."
    if shutil.which("blueutil") is None:
        return (
            "blueutil is not installed, so I can't control Bluetooth. "
            "Install it with `brew install blueutil` and try again."
        )
    try:
        subprocess.run(
            ["blueutil", "--power", "1" if state == "on" else "0"],
            check=True,
            capture_output=True,
            text=True,
        )
        return f"Bluetooth turned {state}."
    except subprocess.CalledProcessError as e:
        return f"Failed to turn Bluetooth {state}: {e.stderr.strip() or e}"
    except (FileNotFoundError, OSError) as e:
        return f"Failed to turn Bluetooth {state}: {e}"


@tool
def open_app(name: str) -> str:
    """Open a macOS application by name.

    Args:
        name: The application's name as it appears in /Applications, e.g. "Safari".
    """
    try:
        subprocess.run(["open", "-a", name], check=True, capture_output=True, text=True)
        return f"Opened {name}."
    except subprocess.CalledProcessError as e:
        return f"Failed to open '{name}': {e.stderr.strip() or e}"
    except (FileNotFoundError, OSError) as e:
        return f"Failed to open '{name}': {e}"


@tool
def adjust_brightness(direction: str, steps: int = 1) -> str:
    """Increase or decrease screen brightness.

    Uses System Events key codes via osascript, which requires the terminal
    app to have Accessibility permission granted in System Settings.

    Args:
        direction: Either "up" or "down".
        steps: Number of times to press the brightness key. Defaults to 1.
    """
    if direction not in BRIGHTNESS_KEY_CODES:
        return f"Invalid direction '{direction}'. Use 'up' or 'down'."
    key_code = BRIGHTNESS_KEY_CODES[direction]
    script = f'tell application "System Events" to key code {key_code}'
    try:
        for _ in range(steps):
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or result.stderr.strip():
                return (
                    f"Failed to adjust brightness: {result.stderr.strip()}. "
                    "This likely requires granting Accessibility permission to "
                    "your terminal app in System Settings > Privacy & Security > "
                    "Accessibility."
                )
        return f"Brightness adjusted {direction} ({steps} step{'s' if steps != 1 else ''})."
    except (FileNotFoundError, OSError) as e:
        return f"Failed to adjust brightness: {e}"


@tool
def lock_screen() -> str:
    """Lock the screen immediately using macOS's native lock shortcut.

    Requires the terminal app to have Accessibility permission granted in
    System Settings.
    """
    script = (
        'tell application "System Events" to keystroke "q" using {command down, control down}'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stderr.strip():
            return (
                f"Failed to lock the screen: {result.stderr.strip()}. "
                "This likely requires granting Accessibility permission to "
                "your terminal app in System Settings > Privacy & Security > "
                "Accessibility."
            )
        return "Screen locked."
    except (FileNotFoundError, OSError) as e:
        return f"Failed to lock the screen: {e}"


PROMPT_PATH = Path(__file__).parent / "butler_prompt.md"
TOOLS = [
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
]


def build_agent(model: BaseChatModel):
    """Build a fresh butler agent bound to `model` — used directly below
    for the default BUTLER_MODEL instance, and by hi/router.py to build one
    on a router-selected tier instead."""
    return create_agent(model=model, tools=TOOLS, system_prompt=PROMPT_PATH.read_text())


model = make_chat_model(BUTLER_MODEL, temperature=0, keep_alive="30m")
agent = build_agent(model)
