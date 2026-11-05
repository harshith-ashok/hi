"""Parallel "speaker": runs alongside the main model and decides what gets
spoken while the answer is still streaming.

As soon as the first sentence of the answer is complete, a worker thread
turns it into something sayable (plain words, no URLs/markdown) with the
haiku tier — concurrently with the main model still generating the rest —
and the result is emitted as a `spoken_chunk` event. If the rewrite is slow
or fails, the regex-cleaned sentence is spoken instead, so speech never waits
on a second model.

Only the first sentence of the *final* text block is spoken: a block that is
followed by a tool call resets it, and the full answer stays on screen.
"""

from __future__ import annotations

import queue
import re
import threading

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model_fast

MIN_CHARS = 12
REWRITE_TIMEOUT_S = 2.0
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)|(?<=[.!?])\n")
_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)

_REWRITE_PROMPT = (
    "Rewrite this as ONE short sentence a voice assistant says out loud. "
    "Plain spoken English, outcome only, never mention tools. Round numbers. "
    "No markdown, URLs or file paths — say what they mean. "
    "Reply with only the sentence:\n\n"
)


_NEEDS_REWRITE = re.compile(r"https?://|[/\\_]|\d{4,}|\.\w{2,4}\b|^.{160,}$", re.DOTALL)


def needs_rewrite(text: str) -> bool:
    """URLs, paths, long numbers, filenames, very long sentences: worth a
    model pass. Anything else is already sayable once the markdown is gone."""
    return bool(_NEEDS_REWRITE.search(text))


def plain(text: str) -> str:
    """Strip markdown/code/links down to what can be read aloud."""
    text = _FENCE.sub(" ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[`*_#>|~]+", "", text)
    text = re.sub(r"^\s*(?:[-+]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


class Speaker:
    def __init__(self) -> None:
        self._block = ""
        self._spoken = False
        self._results: queue.Queue[str] = queue.Queue()
        self._threads: list[threading.Thread] = []

    @property
    def has_spoken(self) -> bool:
        return self._spoken

    def feed(self, delta: str) -> None:
        if self._spoken:
            return
        self._block += delta
        match = _SENTENCE_END.search(self._block)
        if match and len(plain(self._block[: match.start()])) >= MIN_CHARS:
            self._spoken = True
            sentence = self._block[: match.start()]
            if needs_rewrite(sentence):
                thread = threading.Thread(target=self._speak, args=(sentence,), daemon=True)
                thread.start()
                self._threads.append(thread)
            else:  # instant: no model call
                self._results.put(plain(sentence))

    def block_ended_by_tool(self) -> None:
        """Text before a tool call is a preamble, not the answer."""
        if not self._spoken:
            self._block = ""

    def _speak(self, sentence: str) -> None:
        cleaned = plain(sentence)
        holder: list[str] = []

        def rewrite() -> None:
            try:
                holder.append(invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(_REWRITE_PROMPT + cleaned)]).strip())
            except Exception:
                pass

        worker = threading.Thread(target=rewrite, daemon=True)
        worker.start()
        worker.join(REWRITE_TIMEOUT_S)
        self._results.put(holder[0] if holder and holder[0] else cleaned)

    def ready(self) -> list[str]:
        lines = []
        while True:
            try:
                lines.append(self._results.get_nowait())
            except queue.Empty:
                return lines

    def finish(self) -> list[str]:
        """Wait (briefly) for any in-flight rewrite, then return what's left."""
        for thread in self._threads:
            thread.join(REWRITE_TIMEOUT_S + 1)
        return self.ready()
