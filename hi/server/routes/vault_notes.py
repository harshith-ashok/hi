"""GET /vault/notes?q=: find your notes; GET /vault/note?path=: read one. For adding a note to a chat as context."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.memory import vault_notes


async def find(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(vault_notes.search, request.query_params.get("q", "")))


async def read(request: Request) -> JSONResponse:
    path = request.query_params.get("path", "")
    text = await run_in_threadpool(vault_notes.read, path)
    if text is None:
        raise HTTPException(404, "No such note")
    return JSONResponse({"path": path, "text": text})


routes = [
    Route("/vault/notes", find, methods=["GET"]),
    Route("/vault/note", read, methods=["GET"]),
]
