"""Warms up an Ollama model with a cheap throwaway call before real use.

Ollama Cloud models can intermittently return a response that ends
immediately with done_reason='load' and no generated content, when the
model wasn't already loaded server-side — this races with the first real
request of a session. Warming the model up once at persona startup, with a
short retry, keeps that race from hitting an actual conversation turn.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage


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
