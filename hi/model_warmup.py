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

`start_keepalive()` (latency fix): "recur on nearly every turn" above
means EVERY classification call (`hi/orchestrator/complexity.py`'s
`classify_with_plan()`, which runs before every single REPL turn) can
silently pay for two full network round trips instead of one — an empty
`done_reason='load'` response, then a real retry. Rather than only
reacting to that after the fact, a background thread keeps the always-
in-use haiku model warm by pinging it periodically through any idle gap
between user turns, so the classification call that actually matters is
more likely to get a real answer on its first attempt.
"""

import logging
import threading
import time

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


def start_keepalive(model: BaseChatModel, interval_seconds: int = 240) -> None:
    """Pings `model` with a trivial call every `interval_seconds`, forever,
    in a daemon background thread — keeps an Ollama Cloud model from
    going cold between user turns during an idle stretch inside one REPL
    session, so the next REAL call is more likely to skip this module's
    own documented "empty done_reason='load' response, retried" tax
    instead of silently paying for it. Only worth doing for a model
    invoked on literally every turn (haiku, via `classify_with_plan()`)
    — pinging every tier/persona a session might touch would just trade
    one kind of wasted call for another. Best-effort: a failed ping is
    silently dropped, never surfaced or retried harder, since missing
    one ping just means the next real call falls back to its own
    existing retry path, not a user-visible failure.
    """
    def _loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                model.invoke("ok")
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()


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
