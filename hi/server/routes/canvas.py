"""The drop box: text, images, voice notes and files, sorted into groups on a canvas (hi/canvas/)."""

from __future__ import annotations

import tempfile

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi.canvas import board, organise
from hi.core.jobs import run_background
from hi.server.http import json_body, require_client, required_text

INLINE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
                ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg", ".webm": "audio/webm"}


async def get_canvas(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(board.snapshot))


async def drop_text(request: Request) -> JSONResponse:
    require_client(request)
    item_id = await run_in_threadpool(board.add_text, required_text(await json_body(request)))
    run_background("canvas-organise", lambda: organise.process(item_id))
    return JSONResponse({"id": item_id})


async def drop_file(request: Request) -> JSONResponse:
    """POST /canvas/file?name=<file>[&kind=audio], the raw file as the body."""
    require_client(request)
    name, kind = request.query_params.get("name", "file"), request.query_params.get("kind", "")
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > board.MAX_FILE_BYTES:
                raise HTTPException(413, "File too large")
            spool.write(chunk)
        if size == 0:
            raise HTTPException(400, "Missing file body")
        spool.seek(0)
        item_id = await run_in_threadpool(board.add_file, name, spool, size, kind)
    run_background("canvas-organise", lambda: organise.process(item_id))
    return JSONResponse({"id": item_id})


async def regroup(request: Request) -> JSONResponse:
    """Sort again: the Inbox only, or with {"all": true} every item not placed by hand."""
    require_client(request)
    moved = await run_in_threadpool(organise.organise, bool((await json_body(request)).get("all")))
    return JSONResponse({"moved": moved, **await run_in_threadpool(board.snapshot)})


async def edit_item(request: Request) -> JSONResponse:
    require_client(request)
    item_id, body = request.path_params["item_id"], await json_body(request)
    ok = True
    if "text" in body:
        ok = await run_in_threadpool(board.set_text, item_id, str(body["text"]))
    if ok and (body.get("group_id") or body.get("group")):
        ok = await run_in_threadpool(board.move_item, item_id, body.get("group_id"), body.get("group"))
    if not ok:
        raise HTTPException(404, "No such item or group")
    return JSONResponse(await run_in_threadpool(board.snapshot))


async def remove_item(request: Request) -> JSONResponse:
    require_client(request)
    if not await run_in_threadpool(board.delete_item, request.path_params["item_id"]):
        raise HTTPException(404, "No such item")
    return JSONResponse(await run_in_threadpool(board.snapshot))


async def edit_group(request: Request) -> JSONResponse:
    require_client(request)
    label = required_text(await json_body(request), "label")
    if not await run_in_threadpool(board.rename_group, request.path_params["group_id"], label):
        raise HTTPException(404, "No such group")
    return JSONResponse(await run_in_threadpool(board.snapshot))


async def item_file(request: Request) -> Response:
    """A dropped image or voice note. Images and audio show inline; anything else downloads, never runs on this origin."""
    path = board.file_path(request.path_params["item_id"], request.path_params["name"])
    if path is None:
        raise HTTPException(404, "No such file")
    kind = INLINE_TYPES.get(path.suffix.lower())
    return Response(path.read_bytes(), media_type=kind or "application/octet-stream", headers={
        "Content-Disposition": f'{"inline" if kind else "attachment"}; filename="{path.name}"',
        "Content-Security-Policy": "default-src 'none'", "X-Content-Type-Options": "nosniff",
    })


routes = [
    Route("/canvas", get_canvas, methods=["GET"]),
    Route("/canvas/text", drop_text, methods=["POST"]),
    Route("/canvas/file", drop_file, methods=["POST"]),
    Route("/canvas/regroup", regroup, methods=["POST"]),
    Route("/canvas/items/{item_id}", edit_item, methods=["PATCH"]),
    Route("/canvas/items/{item_id}", remove_item, methods=["DELETE"]),
    Route("/canvas/groups/{group_id}", edit_group, methods=["PATCH"]),
    Route("/canvas/files/{item_id}/{name}", item_file, methods=["GET"]),
]
