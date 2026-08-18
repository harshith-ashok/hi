"""Warms up an Ollama model with a cheap throwaway call before real use.

Ollama Cloud models can intermittently return a response that ends
immediately with done_reason='load' and no generated content, when the
model wasn't already loaded server-side. Large cloud models (like
gpt-oss:120b-cloud) can get unloaded between turns, not just at session
start, so this can recur on nearly every turn rather than only the first —
warm_up (called once at persona startup) and invoke_with_retry (used for
every model call that needs a real answer, not just tool-loop generation)
both retry past it rather than treating an empty response as real.

langchain_ollama logs each occurrence via logging.warning(), which prints
to stderr by default (nothing in this project configures its own logging
handlers, so Python's last-resort handler catches it) — right in the
middle of the REPL, ahead of every retried reply. It's harmless once
retried, so it's suppressed here rather than left to alarm the user on
every single turn.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

logging.getLogger("langchain_ollama.chat_models").setLevel(logging.ERROR)


def warm_up(model: BaseChatModel, attempts: int = 3) -> None:
    for _ in range(attempts):
        try:
            if model.invoke("hi").content.strip():
                return
        except Exception:
            pass


def invoke_with_retry(model: BaseChatModel, messages: list[BaseMessage], attempts: int = 3) -> str:
    """Like model.invoke(messages).content, but retries past Ollama's
    occasional empty done_reason='load' response instead of silently
    treating it as a real (empty) answer."""
    content = ""
    for _ in range(attempts):
        content = model.invoke(messages).content
        if content.strip():
            break
    return content
