"""Apple Music control for butler, through the Music app's AppleScript interface.

Works with what is in your Music library (your playlists, and songs, albums and artists you
have added). Catalog-only tracks you have never added cannot be played by script; add them to
the library first. These run on the Mac (hi/host.py proxies them when the backend is in Docker).
"""

import subprocess

from langchain_core.tools import tool

ACTIONS = {
    "play": "play", "pause": "pause", "toggle": "playpause", "stop": "stop",
    "next": "next track", "previous": "previous track",
}


def _osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return f"Music failed: {result.stderr.strip() or 'unknown error'}"
    return result.stdout.strip()


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@tool
def play_music(query: str, shuffle: bool = False) -> str:
    """Play something from the user's Apple Music library: a playlist by name first, otherwise
    the best matching song, album or artist.

    Args:
        query: The playlist, song, album or artist name, e.g. "boom".
        shuffle: Turn shuffle on before playing.
    """
    q = _quote(query)
    script = f"""
tell application "Music"
    set p to missing value
    set shuffle enabled to {"true" if shuffle else "false"}
    set exact to (every user playlist whose name is {q})
    set partial to (every user playlist whose name contains {q})
    if (count of exact) > 0 then
        set p to item 1 of exact
    else if (count of partial) > 0 then
        set p to item 1 of partial
    end if
    if p is not missing value then
        play p
        return "Playing playlist " & (name of p)
    end if
    set found to (search library playlist 1 for {q})
    if (count of found) > 0 then
        play item 1 of found
        return "Playing " & (name of item 1 of found) & " by " & (artist of item 1 of found)
    end if
    return "NOT_FOUND"
end tell
"""
    out = _osascript(script)
    if out == "NOT_FOUND":
        return f"Nothing in your Music library matches '{query}'. Add it to your library first, or check the name with list_playlists."
    return out


@tool
def music_control(action: str) -> str:
    """Control Apple Music playback.

    Args:
        action: One of play, pause, toggle, stop, next, previous.
    """
    verb = ACTIONS.get(action.lower().strip())
    if not verb:
        return f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}."
    out = _osascript(f'tell application "Music" to {verb}')
    return out if out.startswith("Music failed") else f"Music: {action}."


@tool
def now_playing() -> str:
    """Say what Apple Music is playing right now, and whether it is paused."""
    script = """
tell application "Music"
    if player state is stopped then return "Nothing is playing."
    return (player state as string) & ": " & (name of current track) & " by " & (artist of current track) & " (" & (album of current track) & ")"
end tell
"""
    return _osascript(script)


@tool
def list_playlists() -> str:
    """List the names of the user's Apple Music playlists."""
    out = _osascript('tell application "Music" to get name of every user playlist')
    return out if out.startswith("Music failed") else (out or "No playlists.")
