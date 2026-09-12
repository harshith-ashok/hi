"""Shared tone layer prepended to every persona's own system prompt (per
explicit request for a Jarvis-like voice) — one file
(`hi/agents/shared_persona.md`), not four copy-pasted blocks that would
drift. Delivery only: each persona's own grounding/tool-use rules are
appended after it unchanged and still take precedence.
"""

from pathlib import Path

_VOICE_PATH = Path(__file__).parent / "shared_persona.md"


def voiced_prompt(persona_prompt_path: Path) -> str:
    """Reads `persona_prompt_path` and prepends the shared voice block."""
    return f"{_VOICE_PATH.read_text()}\n\n{persona_prompt_path.read_text()}"
