"""The Inbox: reports the assistant wrote on its own, and the actions it is waiting for you to approve."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi.memory import proposals, reports
from hi.server import proposals_exec


async def list_reports(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(reports.list_reports))


async def get_report(request: Request) -> JSONResponse:
    report = await run_in_threadpool(reports.read_report, request.path_params["report_id"])
    if report is None:
        raise HTTPException(404, "No such report")
    return JSONResponse(report)


async def list_proposals(request: Request) -> JSONResponse:
    rows = await run_in_threadpool(proposals.all_proposals)
    if request.query_params.get("status") == "pending":
        rows = [p for p in rows if p["status"] == proposals.CREATED]
    return JSONResponse([{**p, "summary": proposals.describe(p)} for p in rows[:100]])


async def approve(request: Request) -> JSONResponse:
    try:
        outcome = await run_in_threadpool(proposals_exec.run, request.path_params["proposal_id"])
    except proposals_exec.NotWaiting:
        raise HTTPException(409, "That proposal is not waiting (already answered, expired, or unknown)")
    return JSONResponse(outcome)


async def deny(request: Request) -> Response:
    try:
        await run_in_threadpool(proposals_exec.deny, request.path_params["proposal_id"])
    except proposals_exec.NotWaiting:
        raise HTTPException(409, "That proposal is not waiting (already answered, expired, or unknown)")
    return Response(status_code=204)


routes = [
    Route("/reports", list_reports, methods=["GET"]),
    Route("/reports/{report_id}", get_report, methods=["GET"]),
    Route("/proposals", list_proposals, methods=["GET"]),
    Route("/proposals/{proposal_id}/approve", approve, methods=["POST"]),
    Route("/proposals/{proposal_id}/deny", deny, methods=["POST"]),
]
