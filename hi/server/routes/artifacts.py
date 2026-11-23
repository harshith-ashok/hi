"""GET /artifacts/{session}: the artifacts of a chat; GET /artifacts/{session}/{slug}/{n}: one version as JSON.

Artifact content is never served as a page: it was written by a model and must not run on this origin (see files.py).
tinyui draws it in a sandboxed frame from the JSON.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.memory import artifacts, sessions


def _session(request: Request) -> str:
    session = request.path_params["session"]
    if not sessions.valid_id(session):
        raise HTTPException(404, "No such chat")
    return session


async def list_artifacts(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(artifacts.listing, _session(request)))


async def get_artifact(request: Request) -> JSONResponse:
    session, slug = _session(request), request.path_params["slug"]
    try:
        version = int(request.path_params["n"])
    except ValueError:
        raise HTTPException(404, "No such version")
    found = await run_in_threadpool(artifacts.read, session, slug, version)
    if found is None:
        raise HTTPException(404, "No such artifact")
    return JSONResponse(found)


routes = [
    Route("/artifacts/{session}", list_artifacts, methods=["GET"]),
    Route("/artifacts/{session}/{slug}/{n}", get_artifact, methods=["GET"]),
]
