"""Numbers and snapshots for tinyui's dashboard views."""

from __future__ import annotations

import hi.config as config
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi.dashboard import get_last_project, get_today_stats, get_vault_stats, get_vitals
from hi.orchestrator.graph import latest_run_trace


async def vitals(request: Request) -> JSONResponse:
    return JSONResponse(get_vitals(active_model=config.SONNET_MODEL))


async def vault_stats(request: Request) -> JSONResponse:
    return JSONResponse(get_vault_stats())


async def today(request: Request) -> JSONResponse:
    return JSONResponse(get_today_stats())


async def last_project(request: Request) -> JSONResponse:
    return JSONResponse({"name": get_last_project()})


async def trace(request: Request) -> JSONResponse:
    content = latest_run_trace()
    if content is None:
        raise HTTPException(404, "No orchestrated run has completed yet.")
    return JSONResponse({"content": content})


routes = [
    Route("/vitals", vitals, methods=["GET"]),
    Route("/vault-stats", vault_stats, methods=["GET"]),
    Route("/today", today, methods=["GET"]),
    Route("/last-project", last_project, methods=["GET"]),
    Route("/trace", trace, methods=["GET"]),
]
