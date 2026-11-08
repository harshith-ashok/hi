"""Generic MCP (Model Context Protocol) client layer: connects to
configured MCP servers and returns their tools as ordinary, synchronously
-invocable LangChain tools, usable directly in any persona's tool list.
Adding a new server is meant to be a small config entry here, not new
plumbing each time.

Most of this codebase is synchronous, but MCP tools are async-native —
verified directly that a tool from `MultiServerMCPClient.get_tools()`
raises NotImplementedError on a plain `.invoke()`. Rather than converting
the whole agent execution path to async, every tool gets wrapped to
bridge with one `asyncio.run()` call per invocation — verified this
works end-to-end against a real MCP server (Playwright, navigating to a
real page and getting the real page title back) before relying on it.

`get_mcp_tools()` also runs once, lazily, whenever a persona module is
first imported (`hi/agents/term/term.py`'s own module-level
`build_agent(model)` call) — including from *inside* an already-running
event loop, since `hi/orchestrator/graph.py`'s DAG executor (TODO.md
Phase 16) can trigger that first import of a persona module its own
`asyncio.run()` call is still on the stack for. A bare `asyncio.run()`
here would raise ("cannot be called from a running event loop") in
exactly that case — confirmed live, not hypothetical, the first time the
orchestrator planned a task routed to a persona no synchronous caller
had imported yet this process. `_run_sync()` below handles both cases.

Servers are included in the client config *conditionally* — a server only
gets added if what it actually needs is present (a token, a binary on
PATH). A server that's missing its credential is just absent, not a
crash; a server that fails to connect (Docker not running, npx failing to
resolve a package, a bad token) is caught and skipped, logged as a
warning, without taking any other server or the persona down with it.
"""

import asyncio
import concurrent.futures
import logging
import shutil

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

# `import hi.config as config`, not `from hi.config import X, Y` — a plain
# `from`-import snapshots the value at import time, which would make
# `hi/mcp_install.py`'s `configure_mcp_server()` writing a fresh
# credential into the config module invisible here for the rest of this
# process (this module only ever gets re-imported once). Reading
# `config.GITHUB_PERSONAL_ACCESS_TOKEN` fresh inside `_server_configs()`
# instead means a newly-configured server can actually activate within
# the same session, not just after a restart.
import hi.config as config

log = logging.getLogger(__name__)

_PER_SERVER_TIMEOUT = 30.0
GITHUB_TOOLSETS = "context,repos,issues,pull_requests,actions"  # `context` gives get_me (who am I)

_cached_tools: list[BaseTool] | None = None
# Per-server grouping of the same cached tools (TODO.md Phase 27's "agent
# assigned to an MCP server"): lets a caller scope an agent to just one
# server's tools instead of every configured server's at once. Built
# alongside _cached_tools from the same single fetch, never a second set
# of live connections.
_cached_tools_by_server: dict[str, list[BaseTool]] | None = None


def _sync_wrap(async_tool: BaseTool) -> BaseTool:
    """Wrap an async-only MCP tool so it can be called via .invoke() like
    any other LangChain tool — bridges with one call per invocation,
    same "already-running loop?" handling as get_mcp_tools() itself
    (an orchestrated subagent, TODO.md Phase 16, can invoke this tool
    from inside graph.py's own running event loop, not just a
    synchronous persona's turn)."""

    def sync_func(**kwargs):
        return _run_sync(async_tool.ainvoke(kwargs))

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

    # Read any URL as markdown (the `web` persona's page reader).
    if shutil.which("mcp-server-fetch"):
        servers["fetch"] = {"command": "mcp-server-fetch", "args": [], "transport": "stdio"}
    elif shutil.which("uvx"):
        servers["fetch"] = {"command": "uvx", "args": ["mcp-server-fetch"], "transport": "stdio"}

    if config.GITHUB_PERSONAL_ACCESS_TOKEN and shutil.which("github-mcp-server"):  # the Docker image
        servers["github"] = {
            "command": "github-mcp-server",
            "args": ["stdio", "--toolsets", GITHUB_TOOLSETS],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_PERSONAL_ACCESS_TOKEN},
            "transport": "stdio",
        }
    elif config.GITHUB_PERSONAL_ACCESS_TOKEN and shutil.which("docker"):
        servers["github"] = {
            "command": "docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e",
                f"GITHUB_TOOLSETS={GITHUB_TOOLSETS}",
                "ghcr.io/github/github-mcp-server",
            ],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_PERSONAL_ACCESS_TOKEN},
            "transport": "stdio",
        }

    if config.GOOGLE_OAUTH_CLIENT_ID and config.GOOGLE_OAUTH_CLIENT_SECRET and config.GOOGLE_MCP_URL:
        # The long-running service from docker-compose.yml: its sign-in callback stays up.
        servers["google"] = {"url": config.GOOGLE_MCP_URL, "transport": "streamable_http"}
    elif config.GOOGLE_OAUTH_CLIENT_ID and config.GOOGLE_OAUTH_CLIENT_SECRET and shutil.which("workspace-mcp"):
        # Everything Google: Drive, Docs, Sheets, Slides, Forms, Gmail, Calendar, Tasks, Contacts, Chat.
        # First use returns a sign-in link; the callback lands on the published GOOGLE_MCP_PORT, and the
        # token is kept in ~/.hi/google (the persisted hi-home volume in Docker).
        servers["google"] = {
            "command": "workspace-mcp",
            "args": ["--single-user"],
            "env": {
                "GOOGLE_OAUTH_CLIENT_ID": config.GOOGLE_OAUTH_CLIENT_ID,
                "GOOGLE_OAUTH_CLIENT_SECRET": config.GOOGLE_OAUTH_CLIENT_SECRET,
                "WORKSPACE_MCP_PORT": str(config.GOOGLE_MCP_PORT),
                "WORKSPACE_MCP_BASE_URI": "http://localhost",
                "OAUTHLIB_INSECURE_TRANSPORT": "1",  # the callback is plain http on localhost
                "GOOGLE_MCP_CREDENTIALS_DIR": str(config.ENV_PATH.parent / "google"),
            },
            "transport": "stdio",
        }

    if config.OBSIDIAN_REST_API_KEY:
        # The Local REST API Obsidian plugin's built-in MCP endpoint uses a
        # self-signed certificate by default, which httpx's default async
        # client rejects — verified directly (CERTIFICATE_VERIFY_FAILED)
        # against a real running instance. Disabling verification is a
        # reasonable trade-off specifically here: this is a loopback-only
        # connection (127.0.0.1) that never leaves the machine.
        servers["obsidian"] = {
            "url": "https://127.0.0.1:27124/mcp/",
            "headers": {"Authorization": f"Bearer {config.OBSIDIAN_REST_API_KEY}"},
            "transport": "streamable_http",
            "httpx_client_factory": _insecure_local_client,
        }

    if config.N8N_MCP_URL and config.N8N_MCP_TOKEN:
        # n8n's own config shape uses "type": "http" — the same
        # streamable-HTTP transport Obsidian's entry above already uses,
        # just a different server-side plugin naming it differently.
        servers["n8n"] = {
            "url": config.N8N_MCP_URL,
            "headers": {"Authorization": f"Bearer {config.N8N_MCP_TOKEN}"},
            "transport": "streamable_http",
        }

    return servers


def _run_sync(coro):
    """Runs `coro` to completion and returns its result, whether or not
    an event loop is already running on the calling thread.
    `asyncio.run()` alone only works with no loop running — true for
    every caller this project had until the orchestrator's async DAG
    executor existed. A fresh thread gets a fresh event loop, sidestepping
    the "already running" conflict entirely rather than trying to
    schedule onto the existing loop from the wrong thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # no loop running — the common, unchanged case

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _fetch_tools_by_server() -> dict[str, list[BaseTool]]:
    configs = _server_configs()
    by_server: dict[str, list[BaseTool]] = {}
    for name, server_config in configs.items():
        try:
            client = MultiServerMCPClient({name: server_config})
            server_tools = await asyncio.wait_for(
                client.get_tools(), timeout=_PER_SERVER_TIMEOUT
            )
            by_server[name] = server_tools
        except Exception as e:
            log.warning(f"Skipping MCP server '{name}': {e}")
    return by_server


def _ensure_cached() -> None:
    global _cached_tools, _cached_tools_by_server
    if _cached_tools_by_server is None:
        raw_by_server = _run_sync(_fetch_tools_by_server())
        _cached_tools_by_server = {
            name: [_sync_wrap(t) for t in tools] for name, tools in raw_by_server.items()
        }
        _cached_tools = [t for tools in _cached_tools_by_server.values() for t in tools]


def get_mcp_tools() -> list[BaseTool]:
    """Return every available MCP tool, from every configured and
    reachable server, sync-wrapped and cached — fetched once per process,
    not once per turn."""
    _ensure_cached()
    return _cached_tools


def get_mcp_tools_by_server() -> dict[str, list[BaseTool]]:
    """Same live-fetched, cached tools as get_mcp_tools(), grouped by
    which MCP server each came from — lets hi/agents_ondemand.py scope
    an on-demand agent to just the one MCP server the user assigned it,
    instead of every configured server's tools at once. Only servers
    that actually connected successfully appear as keys."""
    _ensure_cached()
    return _cached_tools_by_server


def tool_servers() -> dict[str, str]:
    """tool name -> the MCP server it came from (see hi/toolkit.py)."""
    return {t.name: server for server, tools in get_mcp_tools_by_server().items() for t in tools}
