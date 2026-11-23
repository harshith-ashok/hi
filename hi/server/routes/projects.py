"""Projects: a named workspace (instructions + files) that chats can belong to. See hi/memory/projects.py."""

from __future__ import annotations

import tempfile
from dataclasses import asdict

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi.memory import projects, sessions
from hi.server.http import json_body, require_client


def _project(request: Request) -> projects.Project:
    p = projects.get(request.path_params["slug"])
    if p is None:
        raise HTTPException(404, "No such project")
    return p


def _detail(p: projects.Project) -> dict:
    chats = [asdict(s) for s in sessions.list_sessions(include_archived=True) if s.project == p.slug]
    return {**asdict(p), "files": projects.files(p.slug), "chats": chats}


def _summary(p: projects.Project) -> dict:
    return {"slug": p.slug, "name": p.name, "description": p.description, "files": len(projects.files(p.slug))}


async def list_projects(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(lambda: [_summary(p) for p in projects.list_projects()]))


async def create_project(request: Request) -> JSONResponse:
    require_client(request)
    body = await json_body(request)
    try:
        p = await run_in_threadpool(projects.create, str(body.get("name") or ""), str(body.get("description") or ""), str(body.get("instructions") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(await run_in_threadpool(_detail, p), status_code=201)


async def get_project(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(lambda: _detail(_project(request))))


async def patch_project(request: Request) -> JSONResponse:
    require_client(request)
    body = await json_body(request)
    slug = _project(request).slug
    fields = {k: body.get(k) for k in ("name", "description", "instructions")}
    if any(v is not None and not isinstance(v, str) for v in fields.values()):
        raise HTTPException(400, "name, description and instructions must be text")
    p = await run_in_threadpool(lambda: projects.update(slug, **fields))
    return JSONResponse(await run_in_threadpool(_detail, p))


async def delete_project(request: Request) -> Response:
    require_client(request)
    await run_in_threadpool(projects.delete, _project(request).slug)
    return Response(status_code=204)


async def upload_file(request: Request) -> JSONResponse:
    """POST /projects/{slug}/files?name=<file>, the raw file as the body."""
    require_client(request)
    slug = _project(request).slug
    name = request.query_params.get("name", "")
    if not projects.valid_file_name(name):
        raise HTTPException(400, "That file name is not allowed")
    if int(request.headers.get("content-length") or 0) > projects.MAX_FILE_BYTES:
        raise HTTPException(413, "That file is too large")
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:
        async for chunk in request.stream():
            spool.write(chunk)
        spool.seek(0)
        try:
            return JSONResponse(await run_in_threadpool(projects.save_file, slug, name, spool), status_code=201)
        except ValueError as e:
            raise HTTPException(413 if "large" in str(e) else 400, str(e))


async def delete_project_file(request: Request) -> Response:
    require_client(request)
    slug = _project(request).slug
    if not await run_in_threadpool(projects.delete_file, slug, request.path_params["name"]):
        raise HTTPException(404, "No such file")
    return Response(status_code=204)


routes = [
    Route("/projects", list_projects, methods=["GET"]),
    Route("/projects", create_project, methods=["POST"]),
    Route("/projects/{slug}", get_project, methods=["GET"]),
    Route("/projects/{slug}", patch_project, methods=["PATCH"]),
    Route("/projects/{slug}", delete_project, methods=["DELETE"]),
    Route("/projects/{slug}/files", upload_file, methods=["POST"]),
    Route("/projects/{slug}/files/{name}", delete_project_file, methods=["DELETE"]),
]
