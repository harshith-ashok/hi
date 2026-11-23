"""GET /preferences and PUT /preferences {text}: the standing preferences that ride in every prompt."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.memory import preferences
from hi.server.http import json_body, require_client


async def get_preferences(request: Request) -> JSONResponse:
    return JSONResponse({"text": await run_in_threadpool(preferences.read), "max_chars": preferences.MAX_CHARS})


async def put_preferences(request: Request) -> JSONResponse:
    require_client(request)
    body = await json_body(request)
    if not isinstance(body.get("text"), str):
        raise HTTPException(400, "text must be a string")
    try:
        await run_in_threadpool(preferences.write, body["text"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"text": await run_in_threadpool(preferences.read), "max_chars": preferences.MAX_CHARS})


routes = [
    Route("/preferences", get_preferences, methods=["GET"]),
    Route("/preferences", put_preferences, methods=["PUT"]),
]
