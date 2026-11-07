"""Additional macOS system-control tools for butler: volume, Wi-Fi, Do Not
Disturb, screenshots, clipboard, and window/app management. Follows the
same pattern as the tools already in butler.py — a subprocess/osascript
call with a clear error message on failure, never a silent no-op.
"""

import shutil
import subprocess

from langchain_core.tools import tool



def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


@tool
def set_volume(level: int) -> str:
    """Set the system output volume.

    Args:
        level: Volume level from 0 (silent) to 100 (max).
    """
    if not 0 <= level <= 100:
        return f"Invalid volume level '{level}'. Use 0-100."
    result = _run_osascript(f"set volume output volume {level}")
    if result.returncode != 0:
        return f"Failed to set volume: {result.stderr.strip()}"
    return f"Volume set to {level}."


@tool
def mute() -> str:
    """Mute system audio output."""
    result = _run_osascript("set volume with output muted")
    if result.returncode != 0:
        return f"Failed to mute: {result.stderr.strip()}"
    return "Muted."


@tool
def unmute() -> str:
    """Unmute system audio output."""
    result = _run_osascript("set volume without output muted")
    if result.returncode != 0:
        return f"Failed to unmute: {result.stderr.strip()}"
    return "Unmuted."


def _wifi_device() -> str | None:
    result = subprocess.run(
        ["networksetup", "-listallhardwareports"], capture_output=True, text=True
    )
    lines = result.stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip() in ("Hardware Port: Wi-Fi", "Hardware Port: AirPort"):
            for following in lines[i + 1 : i + 3]:
                if following.startswith("Device:"):
                    return following.split(":", 1)[1].strip()
    return None


@tool
def toggle_wifi(state: str) -> str:
    """Turn Wi-Fi on or off.

    Args:
        state: Either "on" or "off".
    """
    if state not in ("on", "off"):
        return f"Invalid state '{state}'. Use 'on' or 'off'."
    device = _wifi_device()
    if not device:
        return "Couldn't find a Wi-Fi hardware port on this Mac."
    result = subprocess.run(
        ["networksetup", "-setairportpower", device, state],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"Failed to turn Wi-Fi {state}: {result.stderr.strip()}"
    return f"Wi-Fi turned {state}."


@tool
def toggle_dnd(shortcut_name: str = "Toggle Do Not Disturb") -> str:
    """Toggle Do Not Disturb / Focus mode, by running a Shortcuts.app
    automation. macOS removed the old defaults-based DND toggle in
    Monterey+; Focus state now lives in a system-managed store with no
    stable public API, so this only works if the user has created a
    Shortcuts automation with this name (Shortcuts.app -> create a
    shortcut that toggles Focus -> name it to match).

    Args:
        shortcut_name: The Shortcuts.app automation to run. Defaults to
            "Toggle Do Not Disturb" — the user must have created a
            shortcut with this exact name for this to work.
    """
    result = subprocess.run(
        ["shortcuts", "run", shortcut_name], capture_output=True, text=True
    )
    if result.returncode != 0:
        return (
            f"Couldn't run the '{shortcut_name}' shortcut: {result.stderr.strip() or 'not found'}. "
            "Do Not Disturb has no stable command-line toggle on modern macOS — create a "
            f"Shortcuts.app automation named '{shortcut_name}' that toggles Focus, then retry."
        )
    return "Toggled Do Not Disturb."


@tool
def take_screenshot(path: str) -> str:
    """Take a screenshot of the whole screen and save it to a file.

    Args:
        path: Where to save the screenshot, e.g. "/Users/me/Desktop/shot.png".
    """
    result = subprocess.run(["screencapture", "-x", path], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Failed to take screenshot: {result.stderr.strip()}"
    return f"Screenshot saved to {path}."


@tool
def read_clipboard() -> str:
    """Read the current text contents of the clipboard."""
    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Failed to read clipboard: {result.stderr.strip()}"
    return result.stdout


@tool
def write_clipboard(text: str) -> str:
    """Write text to the clipboard.

    Args:
        text: The text to copy to the clipboard.
    """
    result = subprocess.run(["pbcopy"], input=text, capture_output=True, text=True)
    if result.returncode != 0:
        return f"Failed to write clipboard: {result.stderr.strip()}"
    return "Copied to clipboard."


@tool
def list_running_apps() -> str:
    """List the names of currently running applications with a user interface."""
    script = (
        'tell application "System Events" to get name of every process whose background only is false'
    )
    result = _run_osascript(script)
    if result.returncode != 0:
        return f"Failed to list running apps: {result.stderr.strip()}"
    apps = [name.strip() for name in result.stdout.split(",")]
    return "\n".join(sorted(apps))


@tool
def quit_app(name: str) -> str:
    """Quit a running application by name.

    Args:
        name: The application's name, e.g. "Safari".
    """
    result = _run_osascript(f'quit app "{name}"')
    if result.returncode != 0:
        return f"Failed to quit '{name}': {result.stderr.strip()}"
    return f"Quit {name}."


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
