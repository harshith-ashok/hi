"""The pending-approval queue: destructive actions wait here until the user answers in tinyui."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi.memory import journal
from hi.orchestrator.pending_actions import list_pending, resolve
from hi.server.http import require_client


async def list_actions(request: Request) -> JSONResponse:
    return JSONResponse([{"id": a.id, "description": a.description, "created_at": a.created_at} for a in list_pending()])


def _answer(approved: bool):
    async def answer(request: Request) -> Response:
        require_client(request)
        action_id = request.path_params["action_id"]
        described = next((a.description for a in list_pending() if a.id == action_id), action_id)
        if not resolve(action_id, approved=approved):
            raise HTTPException(404, f"No pending action '{action_id}' (already resolved, or never existed)")
        journal.record_event("approved" if approved else "denied", described)
        return Response(status_code=204)

    return answer


routes = [
    Route("/pending", list_actions, methods=["GET"]),
    Route("/pending/{action_id}/approve", _answer(True), methods=["POST"]),
    Route("/pending/{action_id}/deny", _answer(False), methods=["POST"]),
]
