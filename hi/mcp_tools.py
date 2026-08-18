"""Generic MCP (Model Context Protocol) client layer: connects to
configured MCP servers and returns their tools as ordinary, synchronously
-invocable LangChain tools, usable directly in any persona's tool list.
Adding a new server is meant to be a small config entry here, not new
plumbing each time.

The rest of this codebase is entirely synchronous (no asyncio anywhere
else), but MCP tools are async-native — verified directly that a tool
from `MultiServerMCPClient.get_tools()` raises NotImplementedError on a
plain `.invoke()`. Rather than converting the whole agent execution path
to async, every tool gets wrapped to bridge with one `asyncio.run()` call
per invocation — verified this works end-to-end against a real MCP server
(Playwright, navigating to a real page and getting the real page title
back) before relying on it.

Servers are included in the client config *conditionally* — a server only
gets added if what it actually needs is present (a token, a binary on
PATH). A server that's missing its credential is just absent, not a
crash; a server that fails to connect (Docker not running, npx failing to
resolve a package, a bad token) is caught and skipped, logged as a
warning, without taking any other server or the persona down with it.
"""

import asyncio
import logging
import shutil

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from hi.config import GITHUB_PERSONAL_ACCESS_TOKEN, OBSIDIAN_REST_API_KEY

log = logging.getLogger(__name__)

_PER_SERVER_TIMEOUT = 30.0

_cached_tools: list[BaseTool] | None = None


def _sync_wrap(async_tool: BaseTool) -> BaseTool:
    """Wrap an async-only MCP tool so it can be called via .invoke() like
    any other LangChain tool — bridges with one asyncio.run() per call."""

    def sync_func(**kwargs):
        return asyncio.run(async_tool.ainvoke(kwargs))

    return StructuredTool.from_function(
        func=sync_func,
        name=async_tool.name,
        description=async_tool.description,
        args_schema=async_tool.args_schema,
    )


def _insecure_local_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """httpx client factory with cert verification off, for the Obsidian
    Local REST API plugin's self-signed local certificate specifically."""
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, verify=False)


def _server_configs() -> dict:
    servers: dict = {}

    if shutil.which("npx"):
        servers["playwright"] = {
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
            "transport": "stdio",
        }
    else:
        log.warning("npx not found on PATH — skipping the Playwright MCP server.")

    if GITHUB_PERSONAL_ACCESS_TOKEN and shutil.which("docker"):
        servers["github"] = {
            "command": "docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e",
                "GITHUB_TOOLSETS=repos,issues,pull_requests,actions",
                "ghcr.io/github/github-mcp-server",
            ],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": GITHUB_PERSONAL_ACCESS_TOKEN},
            "transport": "stdio",
        }

    if OBSIDIAN_REST_API_KEY:
        # The Local REST API Obsidian plugin's built-in MCP endpoint uses a
        # self-signed certificate by default, which httpx's default async
        # client rejects — verified directly (CERTIFICATE_VERIFY_FAILED)
        # against a real running instance. Disabling verification is a
        # reasonable trade-off specifically here: this is a loopback-only
        # connection (127.0.0.1) that never leaves the machine.
        servers["obsidian"] = {
            "url": "https://127.0.0.1:27124/mcp/",
            "headers": {"Authorization": f"Bearer {OBSIDIAN_REST_API_KEY}"},
            "transport": "streamable_http",
            "httpx_client_factory": _insecure_local_client,
        }

    return servers


async def _fetch_tools() -> list[BaseTool]:
    configs = _server_configs()
    tools: list[BaseTool] = []
    for name, server_config in configs.items():
        try:
            client = MultiServerMCPClient({name: server_config})
            server_tools = await asyncio.wait_for(
                client.get_tools(), timeout=_PER_SERVER_TIMEOUT
            )
            tools.extend(server_tools)
        except Exception as e:
            log.warning(f"Skipping MCP server '{name}': {e}")
    return tools


def get_mcp_tools() -> list[BaseTool]:
    """Return every available MCP tool, from every configured and
    reachable server, sync-wrapped and cached — fetched once per process,
    not once per turn."""
    global _cached_tools
    if _cached_tools is None:
        raw_tools = asyncio.run(_fetch_tools())
        _cached_tools = [_sync_wrap(t) for t in raw_tools]
    return _cached_tools
