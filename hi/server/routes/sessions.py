"""Chat sessions: list, create, rename, pin, archive, delete, reopen, search; and drawing a diagram for an answer."""

from __future__ import annotations

from dataclasses import asdict

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi import visuals
from hi.memory import sessions, transcript
from hi.server.http import json_body, require_client

TURN_FIELDS = ("id", "parent", "time", "ask", "answer", "tools", "persona", "tier", "seconds", "visual", "error", "plan")


def _session_or_404(session_id: str) -> sessions.Session:
    s = sessions.get(session_id)
    if s is None:
        raise HTTPException(404, "No such session")
    return s


async def list_sessions(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "").strip()
    include_archived = request.query_params.get("archived") == "1"

    def load() -> list[dict]:
        rows = sessions.list_sessions(include_archived)
        if not query:
            return [asdict(s) for s in rows]
        hits = transcript.search_sessions(query)
        needle = query.lower()
        return [{**asdict(s), "snippet": hits.get(s.id, "")} for s in rows if needle in s.title.lower() or s.id in hits]

    return JSONResponse(await run_in_threadpool(load))


async def create_session(request: Request) -> JSONResponse:
    require_client(request)
    body = await json_body(request)
    return JSONResponse(asdict(await run_in_threadpool(sessions.create, str(body.get("title") or ""))), status_code=201)


async def get_session(request: Request) -> JSONResponse:
    s = _session_or_404(request.path_params["session_id"])
    turns = await run_in_threadpool(transcript.session_turns, s.id, s.head)
    versions = await run_in_threadpool(transcript.versions, s.id)
    return JSONResponse({**asdict(s), "turns": [{**{k: t.get(k, "") for k in TURN_FIELDS}, "versions": versions.get(t["id"])} for t in turns]})


async def patch_session(request: Request) -> JSONResponse:
    require_client(request)
    body = await json_body(request)
    pinned, archived = body.get("pinned"), body.get("archived")
    for value in (pinned, archived):
        if value is not None and not isinstance(value, bool):
            raise HTTPException(400, "pinned and archived must be true or false")
    session_id = request.path_params["session_id"]
    head = body.get("head")
    if head is not None:
        # Switching to another attempt: show the newest branch that goes through the turn chosen.
        if not isinstance(head, str) or not await run_in_threadpool(transcript.has_turn, session_id, head):
            raise HTTPException(400, "head must be the id of a turn in this chat")
        head = await run_in_threadpool(transcript.newest_leaf, session_id, head)
    s = await run_in_threadpool(sessions.update, session_id, body.get("title"), pinned, archived, head)
    if s is None:
        raise HTTPException(404, "No such session")
    return JSONResponse(asdict(s))


async def delete_session(request: Request) -> Response:
    require_client(request)
    if not await run_in_threadpool(sessions.delete, request.path_params["session_id"]):
        raise HTTPException(404, "No such session")
    return Response(status_code=204)


async def draw(request: Request) -> JSONResponse:
    """POST /visual {question, answer, error?}: a Mermaid diagram for an answer (null if there is nothing to draw)."""
    require_client(request)
    body = await json_body(request)
    answer = str(body.get("answer") or "")
    if not answer.strip():
        raise HTTPException(400, "Missing 'answer'")
    mermaid = await run_in_threadpool(visuals.make_visual, str(body.get("question") or ""), answer, str(body.get("error") or ""))
    return JSONResponse({"mermaid": mermaid})


routes = [
    Route("/sessions", list_sessions, methods=["GET"]),
    Route("/sessions", create_session, methods=["POST"]),
    Route("/sessions/{session_id}", get_session, methods=["GET"]),
    Route("/sessions/{session_id}", patch_session, methods=["PATCH"]),
    Route("/sessions/{session_id}", delete_session, methods=["DELETE"]),
    Route("/visual", draw, methods=["POST"]),
]
