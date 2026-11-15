"""MCP server setup: which servers exist and saving their credentials (write-only, never echoed back)."""

from __future__ import annotations

import shutil

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import hi.config as config
from hi.env_file import ENV_PATH, write_env_var
from hi.mcp_install import _CATALOG as MCP_CATALOG
from hi.mcp_install import _bust_mcp_tools_cache
from hi.mcp_tools import get_mcp_tools_by_server
from hi.server.http import json_body

# A person filling in a form and pressing Save is the confirmation, so these writes skip the
# confirm-before-acting gate that applies to an AI-initiated write (hi/action_tiers.py).


async def servers(request: Request) -> JSONResponse:
    result = []
    for name, (env_var, desc) in MCP_CATALOG.items():
        if env_var is None:
            configured = shutil.which("npx") is not None
        elif isinstance(env_var, tuple):
            configured = all(getattr(config, v, None) for v in env_var)
        else:
            configured = bool(getattr(config, env_var, None))
        result.append({"name": name, "description": desc, "configured": configured})
    return JSONResponse(result)


async def configure(request: Request) -> JSONResponse:
    """{name, credential} for the single-credential servers (github, obsidian)."""
    body = await json_body(request)
    name = (body.get("name") or "").strip()
    credential = (body.get("credential") or "").strip()
    if name not in MCP_CATALOG:
        raise HTTPException(400, f"Unknown server '{name}'. Known servers: {', '.join(MCP_CATALOG)}")
    env_var, _desc = MCP_CATALOG[name]
    if env_var is None:
        raise HTTPException(400, f"'{name}' needs no credential.")
    if isinstance(env_var, tuple):
        raise HTTPException(400, f"'{name}' needs multiple values — use POST /mcp/configure/n8n instead.")
    if not credential:
        raise HTTPException(400, "Missing 'credential'.")
    write_env_var(env_var, credential, path=ENV_PATH)
    setattr(config, env_var, credential)
    _bust_mcp_tools_cache()
    return JSONResponse({"configured": name})


async def configure_n8n(request: Request) -> JSONResponse:
    """{url, token}: n8n needs two values."""
    body = await json_body(request)
    url = (body.get("url") or "").strip()
    token = (body.get("token") or "").strip()
    if not url or not token:
        raise HTTPException(400, "Both 'url' and 'token' are required.")
    write_env_var("N8N_MCP_URL", url, path=ENV_PATH)
    write_env_var("N8N_MCP_TOKEN", token, path=ENV_PATH)
    config.N8N_MCP_URL = url
    config.N8N_MCP_TOKEN = token
    _bust_mcp_tools_cache()
    return JSONResponse({"configured": "n8n"})


async def agent_servers(request: Request) -> JSONResponse:
    return JSONResponse({name: len(tools) for name, tools in get_mcp_tools_by_server().items()})


routes = [
    Route("/mcp/servers", servers, methods=["GET"]),
    Route("/mcp/configure", configure, methods=["POST"]),
    Route("/mcp/configure/n8n", configure_n8n, methods=["POST"]),
    Route("/agents/mcp-servers", agent_servers, methods=["GET"]),
]
