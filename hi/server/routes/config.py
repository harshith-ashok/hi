"""Settings (GET/POST /config), the model list, and the health report."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import hi.config as config
from hi import llm, probes
from hi.memory import journal
from hi.server.http import json_body

# Settings tinyui's settings screen can read and write. Credentials never appear here: they are write-only
# (see routes/mcp.py), so a GET can't echo a secret back.
CONFIG_FIELDS = (
    "VAULT_PATH", "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "TERM_MODEL",
    "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL", "VISION_MODEL",
    "AI_MODE", "OLLAMA_HOST", "TAILSCALE_OLLAMA_URL", "TTS_MODEL", "TTS_VOICE", "TTS_BACKEND",
)
CLEARABLE = {"TAILSCALE_OLLAMA_URL"}  # may be set to an empty value; other empty values are ignored


async def get_config(request: Request) -> JSONResponse:
    mode = request.query_params.get("mode", config.AI_MODE)
    if mode not in config.MODES:
        raise HTTPException(400, f"Unknown mode '{mode}'")
    payload = {field: str(getattr(config, field)) for field in CONFIG_FIELDS}
    payload.update({role: config.model_for(role, mode) for role in config.MODEL_ROLES})
    payload["MODES"] = list(config.MODES)
    return JSONResponse(payload)


async def post_config(request: Request) -> JSONResponse:
    """Write settings to ~/.hi/.env and apply them to this process now (everything reads `config.X` live)."""
    body = await json_body(request)
    unknown = [k for k in body if k not in CONFIG_FIELDS]
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {', '.join(unknown)}")
    if body.get("AI_MODE", config.AI_MODE) not in config.MODES:
        raise HTTPException(400, f"AI_MODE must be one of: {', '.join(config.MODES)}")

    # AI_MODE goes first: model names are stored per mode, so the rest must land in the mode being switched to.
    updated = []
    for field, value in sorted(body.items(), key=lambda item: item[0] != "AI_MODE"):
        value = str(value).strip()
        if not value and field not in CLEARABLE:
            continue
        config.set_value(field, value)
        updated.append(field)
    if updated:
        journal.record_event("settings", "changed " + ", ".join(updated))
    return JSONResponse({"updated": updated, "note": "Written to ~/.hi/.env and applied immediately — no restart needed."})


async def models(request: Request) -> JSONResponse:
    mode = request.query_params.get("mode")
    host = request.query_params.get("host")
    try:
        return JSONResponse({"models": await run_in_threadpool(llm.list_models, mode=mode, host=host), "error": ""})
    except (OSError, ValueError) as e:
        where = host or llm.ollama_host(mode) or (mode or config.AI_MODE)
        return JSONResponse({"models": [], "error": f"can't reach {where}: {e}"})


async def health(request: Request) -> JSONResponse:
    report = await run_in_threadpool(probes.run)
    return JSONResponse(report, status_code=200 if report["ok"] else 503)


routes = [
    Route("/config", get_config, methods=["GET"]),
    Route("/config", post_config, methods=["POST"]),
    Route("/models", models, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
]
