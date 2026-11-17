"""Test doubles shared by several test files."""

from __future__ import annotations

import json
from typing import Any, Iterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class Scripted(BaseChatModel):
    """A chat model that replies with `messages` in order, tool calls included, both when invoked and when streamed
    (which is how the turn pipeline calls it). Accepts bind_tools."""

    messages: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _next(self) -> AIMessage:
        return next(self.messages)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator[ChatGenerationChunk]:
        message = self._next()
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
            for i, c in enumerate(message.tool_calls)
        ]
        yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, tool_call_chunks=chunks))


def tool_call(name: str, args: dict | None = None, id: str = "c1") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args or {}, "id": id}])
