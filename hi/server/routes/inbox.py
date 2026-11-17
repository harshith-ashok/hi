"""The Inbox: reports the assistant wrote on its own, and the actions it is waiting for you to approve."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from datetime import datetime

from hi import attachments
from hi.automation import drop, scheduler
from hi.memory import proposals, reports, schedules
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


def _schedule_row(s: schedules.Schedule, now: datetime) -> dict:
    nxt = schedules.next_fires(s, 3, now)
    return {
        "id": s.id, "when": s.when, "enabled": s.enabled, "kind": s.kind, "tier": s.tier, "deliver": s.deliver,
        "prompt": s.prompt, "next": [schedules.say_time(n) for n in nxt], "runs": schedules.runs(s.id, 5),
    }


async def list_schedules(request: Request) -> JSONResponse:
    def load() -> dict:
        errors: list[str] = []
        items = schedules.load_all(errors)
        now = datetime.now()
        return {"schedules": [_schedule_row(s, now) for s in items], "errors": errors}

    return JSONResponse(await run_in_threadpool(load))


async def toggle_schedule(request: Request) -> JSONResponse:
    schedule_id = request.path_params["schedule_id"]
    current = await run_in_threadpool(schedules.load, schedule_id)
    if current is None:
        raise HTTPException(404, "No such schedule")
    await run_in_threadpool(schedules.set_enabled, schedule_id, not current.enabled)
    return JSONResponse({"id": schedule_id, "enabled": not current.enabled})


async def run_schedule(request: Request) -> JSONResponse:
    message = await run_in_threadpool(scheduler.run_now, request.path_params["schedule_id"])
    if message.startswith("No schedule"):
        raise HTTPException(404, message)
    return JSONResponse({"message": message})


async def delete_schedule(request: Request) -> Response:
    if not await run_in_threadpool(schedules.delete, request.path_params["schedule_id"]):
        raise HTTPException(404, "No such schedule")
    return Response(status_code=204)


async def file_attachment(request: Request) -> JSONResponse:
    """Send an uploaded attachment through the drop folder: it is read, filed as a note, and its tasks are added."""
    source = await run_in_threadpool(attachments.original, request.path_params["attachment_id"])
    if source is None:
        raise HTTPException(404, "No such attachment")
    target = await run_in_threadpool(drop.accept, source)
    return JSONResponse({"queued": target.name})


routes = [
    Route("/context/{attachment_id}/file", file_attachment, methods=["POST"]),
    Route("/schedules", list_schedules, methods=["GET"]),
    Route("/schedules/{schedule_id}/toggle", toggle_schedule, methods=["POST"]),
    Route("/schedules/{schedule_id}/run", run_schedule, methods=["POST"]),
    Route("/schedules/{schedule_id}", delete_schedule, methods=["DELETE"]),
    Route("/reports", list_reports, methods=["GET"]),
    Route("/reports/{report_id}", get_report, methods=["GET"]),
    Route("/proposals", list_proposals, methods=["GET"]),
    Route("/proposals/{proposal_id}/approve", approve, methods=["POST"]),
    Route("/proposals/{proposal_id}/deny", deny, methods=["POST"]),
]
