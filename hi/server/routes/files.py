"""Files the agent produced (charts, downloads) and files the user attaches."""

from __future__ import annotations

import re
import tempfile

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi import attachments
from hi.memory.vault import files_dir, plots_dir

PLOT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


async def download(request: Request) -> Response:
    """A file saved by run_python. A download, never a page: agent-written HTML must not run on this
    origin, which can call the rest of this API."""
    relative = request.path_params["relative"]
    path = files_dir() / relative
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", relative) or not path.is_file():
        raise HTTPException(404, "No such file")
    pdf = path.suffix.lower() == ".pdf"
    return Response(
        path.read_bytes(),
        media_type="application/pdf" if pdf else "application/octet-stream",
        headers={
            "Content-Disposition": f'{"inline" if pdf else "attachment"}; filename="{path.name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def plot(request: Request) -> Response:
    """A chart saved by run_python (hi/agents/term/sandbox.py)."""
    name = request.path_params["name"]
    path = plots_dir() / name
    kind = PLOT_TYPES.get(path.suffix.lower())
    if not re.fullmatch(r"[\w-]+\.(png|jpg|webp|svg)", name) or not kind or not path.is_file():
        raise HTTPException(404, "No such plot")
    return Response(
        path.read_bytes(),
        media_type=kind,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "Cache-Control": "max-age=31536000, immutable",
        },
    )


async def upload(request: Request) -> JSONResponse:
    """POST /context?name=<file>[&kind=audio], the raw file as the body. Never starts a reply: the file
    is attached to the next /query that lists its id."""
    name = request.query_params.get("name", "file")
    kind = request.query_params.get("kind", "")
    declared = int(request.headers.get("content-length") or 0)
    if declared <= 0:
        raise HTTPException(400, "Missing file body")
    if declared > attachments.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (1 GB limit)")
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:  # big uploads spill to disk
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > attachments.MAX_UPLOAD_BYTES:
                raise HTTPException(413, "File too large (1 GB limit)")
            spool.write(chunk)
        spool.seek(0)
        try:
            return JSONResponse(await run_in_threadpool(attachments.save, name, spool, size, kind))
        except Exception as e:  # boundary: report the failure to the client instead of dropping the connection
            return JSONResponse({"error": str(e)}, status_code=500)


routes = [
    Route("/files/{relative:path}", download, methods=["GET"]),
    Route("/plots/{name}", plot, methods=["GET"]),
    Route("/context", upload, methods=["POST"]),
]
