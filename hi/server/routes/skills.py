"""GET /skills: the vault skills that `/name` can run, for the composer's autocomplete."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.memory.skills import slash_commands


async def skills(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(slash_commands))


routes = [Route("/skills", skills, methods=["GET"])]
