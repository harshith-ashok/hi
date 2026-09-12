"""On-demand "what's on my screen" vision Q&A — a single screenshot
answered by a real vision-capable model (`gemma4:31b-cloud` by default,
per explicit request; configurable via VISION_MODEL in ~/.hi/.env) rather
than OCR. Complements hi/perception/screen.py's read_screen(): OCR is
faster and good for verbatim text (an error message, a log line), but
can't answer "what app is this", "describe this diagram", "is this UI
showing an error state" — questions that need actual scene understanding,
not just character recognition.

Callable directly whenever a prompt calls for it, no separate enable
step (an earlier version required one; removed per explicit request, see
privacy.py's docstring). Same discipline as read_screen() either way:
the screenshot is deleted immediately after use, never saved, and this
goes through hi/perception/privacy.py's sensitive-context refusal on
every call, with no opt-out.
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import ollama
from langchain_core.tools import tool

import hi.config as config
from hi.models import ensure_pulled
from hi.perception.privacy import sensitive_context_reason

DEFAULT_QUESTION = "Describe what's on the screen."


def _screenshot_b64() -> str | None:
    path = Path(tempfile.mktemp(suffix=".png"))
    try:
        result = subprocess.run(["screencapture", "-x", str(path)], capture_output=True, text=True)
        if result.returncode != 0 or not path.exists():
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    finally:
        path.unlink(missing_ok=True)


@tool
def ask_about_screen(question: str = DEFAULT_QUESTION) -> str:
    """Take a single screenshot right now and ask a vision model a
    question about it — for anything OCR alone can't answer ("what app
    is this", "describe this diagram/image", "does this look like an
    error"). The screenshot is discarded immediately after, never saved.
    Callable directly, no enable step needed. Refuses if the active
    window looks private/incognito or a password manager is frontmost.

    Args:
        question: What to ask about the screen. Defaults to a general description.
    """
    reason = sensitive_context_reason()
    if reason:
        return f"Refused: {reason}"

    image_b64 = _screenshot_b64()
    if image_b64 is None:
        return "Screenshot failed."

    ensure_pulled(config.VISION_MODEL)
    response = ollama.chat(
        model=config.VISION_MODEL,
        messages=[{"role": "user", "content": question, "images": [image_b64]}],
    )
    return response["message"]["content"]
