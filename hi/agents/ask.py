"""`ask_user`: put clarifying questions to the user as a form in the chat, the way on-demand agents do.

The tool does not wait. The chat shows the questions (tinyui reads them from the tool call's arguments), the turn
ends, and the user's answers arrive as the next message with the conversation history intact. Nothing blocks, so
there is no timeout and no thread held open.
"""

from __future__ import annotations

from langchain_core.tools import tool

from hi.ui_spec import WAIT_MARKER

MAX_QUESTIONS = 4


@tool
def ask_user(questions: list[str]) -> str:
    """Ask the user short clarifying questions when the request is genuinely ambiguous or missing something you need
    to act correctly or safely (which branches to delete, which environment to deploy to). They appear as a form; the
    answers come back as the user's next message. Ask everything you need in one call, at most four questions, each
    answerable in a few words. Do not use it for things a sensible default handles.

    Args:
        questions: The questions, one string each.
    """
    asked = [q.strip() for q in questions if q and q.strip()][:MAX_QUESTIONS]
    if not asked:
        return "No questions were given. Decide with a sensible default and say what you assumed."
    return (f"The questions are now shown to the user as a form. {WAIT_MARKER} without adding anything: their "
            "answers arrive as their next message, and then you carry on.")
