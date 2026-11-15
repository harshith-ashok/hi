"""On-demand agents the user can task, and the long-running background commands the shell agent started."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.agents.term.background_tasks import get_process, list_processes, stop_process
from hi.agents_ondemand import answer_questions, create_run, get_run, list_presets, list_runs
from hi.server.http import json_body


async def list_agents(request: Request) -> JSONResponse:
    return JSONResponse([r.to_dict() for r in list_runs()])


async def presets(request: Request) -> JSONResponse:
    return JSONResponse(list_presets())


async def create_agent(request: Request) -> JSONResponse:
    """{prompt, preset?, mcp_server?}: returns at once, either "clarifying" (with questions) or "running"."""
    body = await json_body(request)
    preset = body.get("preset") or None
    prompt = (body.get("prompt") or "").strip()
    if not preset and not prompt:
        raise HTTPException(400, "Missing 'prompt' (or a recognized 'preset')")
    run = await run_in_threadpool(create_run, prompt, preset=preset, mcp_server=body.get("mcp_server") or None)
    return JSONResponse(run.to_dict())


async def get_agent(request: Request) -> JSONResponse:
    run = get_run(request.path_params["run_id"])
    if run is None:
        raise HTTPException(404, "No agent run with that id.")
    return JSONResponse(run.to_dict())


async def answer_agent(request: Request) -> JSONResponse:
    """{answers: [str, ...]}: answers to the run's current questions, in order."""
    answers = (await json_body(request)).get("answers")
    if not isinstance(answers, list):
        raise HTTPException(400, "Expected {'answers': [str, ...]}")
    run = await run_in_threadpool(answer_questions, request.path_params["run_id"], [str(a) for a in answers])
    if run is None:
        raise HTTPException(404, "No agent run with that id.")
    return JSONResponse(run.to_dict())


async def list_background(request: Request) -> JSONResponse:
    return JSONResponse([p.to_dict() for p in list_processes()])


async def get_background(request: Request) -> JSONResponse:
    task = get_process(request.path_params["task_id"])
    if task is None:
        raise HTTPException(404, "No background task with that id.")
    return JSONResponse(task.to_dict())


async def stop_background(request: Request) -> JSONResponse:
    return JSONResponse({"stopped": stop_process(request.path_params["task_id"])})


routes = [
    Route("/agents", list_agents, methods=["GET"]),
    Route("/agents", create_agent, methods=["POST"]),
    Route("/agents/presets", presets, methods=["GET"]),
    Route("/agents/{run_id}", get_agent, methods=["GET"]),
    Route("/agents/{run_id}/answer", answer_agent, methods=["POST"]),
    Route("/background", list_background, methods=["GET"]),
    Route("/background/{task_id}", get_background, methods=["GET"]),
    Route("/background/{task_id}/stop", stop_background, methods=["POST"]),
]
