"""GET /styles: the writing styles the chat can use (built in, and your own in <vault>/hi/styles)."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.automation.profiles import list_styles


async def styles(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(list_styles))


routes = [Route("/styles", styles, methods=["GET"])]
