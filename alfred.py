"""Alfred: a macOS system-control persona built with a LangGraph ReAct agent."""

import shutil
import subprocess
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

BRIGHTNESS_KEY_CODES = {"up": "144", "down": "145"}

model = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0,
)


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


PROMPT_PATH = Path(__file__).parent / "alfred_prompt.md"

agent = create_agent(
    model=model,
    tools=[toggle_bluetooth, open_app, adjust_brightness, lock_screen],
    system_prompt=PROMPT_PATH.read_text(),
)
