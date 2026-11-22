"""POST /suggest: a short continuation of what the user has typed, for the chat box's Tab-to-accept ghost text."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.server.http import json_body
from hi.server.suggest import suggest


async def suggestion(request: Request) -> JSONResponse:
    body = await json_body(request)
    recent = body.get("recent")
    recent = [str(m) for m in recent] if isinstance(recent, list) else []
    return JSONResponse({"suggestion": await run_in_threadpool(suggest, str(body.get("text") or ""), recent)})


routes = [Route("/suggest", suggestion, methods=["POST"])]
