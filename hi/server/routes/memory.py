"""What `hi` remembers: durable memory, past conversations, the morning briefing, and quick capture."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.briefing import build_briefing
from hi.capture.inbox import write_inbox_item
from hi.memory import extraction
from hi.memory.reflection import latest_reflection
from hi.memory.vault import list_conversations, read_conversation
from hi.server.http import json_body, required_text


async def get_memory(request: Request) -> JSONResponse:
    return JSONResponse({"memory": extraction.read_memory(), "reflection": latest_reflection()})


async def add_memory(request: Request) -> JSONResponse:
    text = required_text(await json_body(request))
    return JSONResponse({"added": extraction.add_items([{"kind": "Facts", "text": text}])})


async def forget_memory(request: Request) -> JSONResponse:
    text = required_text(await json_body(request))
    return JSONResponse({"forgot": extraction.forget_line(text)})


async def briefing(request: Request) -> JSONResponse:
    result = await run_in_threadpool(build_briefing)
    if result is None:
        return JSONResponse(None)
    context, suggestion, action = result
    return JSONResponse({"context": context, "suggestion": suggestion, "action": action})


async def conversations(request: Request) -> JSONResponse:
    dates_text = list_conversations.invoke({})
    dates = [] if dates_text == "No conversation logs exist yet." else dates_text.splitlines()
    return JSONResponse(sorted(dates, reverse=True))


async def conversation(request: Request) -> JSONResponse:
    date = request.path_params["date"]
    content = read_conversation.invoke({"date": date})
    if content.startswith("No conversation log for"):
        raise HTTPException(404, content)
    return JSONResponse({"date": date, "content": content})


async def capture(request: Request) -> JSONResponse:
    """The dashboard's quick-capture tile: writes into the same untriaged inbox the global hotkey uses."""
    path = write_inbox_item(required_text(await json_body(request)))
    return JSONResponse({"saved": True, "path": str(path)})


routes = [
    Route("/memory", get_memory, methods=["GET"]),
    Route("/memory/add", add_memory, methods=["POST"]),
    Route("/memory/forget", forget_memory, methods=["POST"]),
    Route("/briefing", briefing, methods=["GET"]),
    Route("/conversations", conversations, methods=["GET"]),
    Route("/conversations/{date}", conversation, methods=["GET"]),
    Route("/capture", capture, methods=["POST"]),
]
