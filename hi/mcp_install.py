"""Conversational MCP server setup (TODO.md Phase 20): browse the known
catalog of MCP servers this project can wire up, and configure one by
name from inside a normal agent turn — writing the credential into
`~/.hi/.env` (the same file `hi/config.py` already reads) instead of the
user hand-editing it.

Scope, deliberately narrow: `hi/mcp_tools.py`'s `_server_configs()` only
knows how to build THREE specific servers (playwright/github/obsidian)
— there's no generic "any MCP server by arbitrary command/URL" support
to browse, and building one wouldn't be "conversational" anyway (the
user would still have to supply the exact command/args/transport a
brand-new, never-coded server needs). What "browse and add a new MCP
server by name" can safely and honestly mean here: show which of those
three are configured vs. missing what they need, and let the user
supply just the one credential a still-missing one needs. "playwright"
needs no credential at all (just `npx` on PATH) — there's nothing to
configure for it beyond what already works or doesn't.

Real limitation, not hidden: `hi/mcp_tools.py` binds a persona's MCP
tools once, at agent-construction time, and caches them for the whole
process (`get_mcp_tools()`'s `_cached_tools`). Writing a new credential
here takes effect for the NEXT agent built with MCP tools in scope (a
persona/tier combination this session hasn't touched yet, or the next
`hi` process) — it does NOT retroactively add tools to an agent object
already constructed and already sitting in `hi/repl.py`'s `agent_cache`.
`_bust_mcp_tools_cache()` clears `hi/mcp_tools.py`'s own cache so a next
build picks the change up without needing a full restart; an
already-cached agent this session has already talked to stays as it was.
"""

from __future__ import annotations

import shutil

from langchain_core.tools import tool

import hi.config as config
from hi.action_tiers import confirm_destructive
from hi.env_file import ENV_PATH, write_env_var

# name -> (env var(s) this server needs, or None if it needs no credential;
# one-line description of what it unlocks). Most servers need exactly one
# credential (a plain str here); n8n needs two (its own instance URL plus
# a bearer token) — a tuple of env var names for that case, handled
# separately from configure_mcp_server()'s single-credential contract by
# configure_n8n_server() below.
_CATALOG: dict[str, tuple[str | tuple[str, str] | None, str]] = {
    "playwright": (
        None,
        "Browser automation (navigate, click, read page content). "
        "Needs no credential — just `npx` on PATH.",
    ),
    "github": (
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GitHub repos/issues/pull_requests/actions. Needs a GitHub "
        "personal access token, and Docker running.",
    ),
    "obsidian": (
        "OBSIDIAN_REST_API_KEY",
        "Direct access to the Obsidian Local REST API plugin's own "
        "endpoint. Needs that plugin's API key.",
    ),
    "n8n": (
        ("N8N_MCP_URL", "N8N_MCP_TOKEN"),
        "Trigger/inspect n8n workflows on your own instance. Needs that "
        "instance's MCP URL and a bearer token — configure via "
        "configure_n8n_server(), not configure_mcp_server().",
    ),
}


@tool
def list_available_mcp_servers() -> str:
    """List the known catalog of MCP servers this project can wire up,
    and whether each is currently configured or still missing something
    — call this before configure_mcp_server() so both you and the user
    know the real server name and what credential it actually needs."""
    lines = []
    for name, (env_var, desc) in _CATALOG.items():
        if env_var is None:
            status = "available" if shutil.which("npx") else "unavailable (npx not found on PATH)"
        elif isinstance(env_var, tuple):
            missing = [v for v in env_var if not getattr(config, v, None)]
            status = "configured" if not missing else f"needs {', '.join(missing)}"
        else:
            status = "configured" if getattr(config, env_var, None) else f"needs {env_var}"
        lines.append(f"- {name}: {status} — {desc}")
    return "\n".join(lines)


@tool
def configure_mcp_server(name: str, credential: str) -> str:
    """Configure a known MCP server by writing its required credential
    into ~/.hi/.env (created if it doesn't exist yet), instead of the
    user hand-editing that file. Call list_available_mcp_servers() first
    to confirm the real server name and which credential it needs.

    Args:
        name: One of the catalog names from list_available_mcp_servers()
            (e.g. "github", "obsidian"). "playwright" needs no
            credential and can't be configured through this tool.
        credential: The actual token/API key value for that server.
    """
    if name not in _CATALOG:
        return f"Unknown server '{name}'. Known servers: {', '.join(_CATALOG)}."
    env_var, _desc = _CATALOG[name]
    if isinstance(env_var, tuple):
        return f"'{name}' needs {len(env_var)} values, not one credential — use configure_n8n_server() instead."
    if env_var is None:
        return f"'{name}' needs no credential — nothing to configure. It's available if `npx` is on PATH."
    credential = credential.strip()
    if not credential:
        return "No credential provided — nothing written."

    if not confirm_destructive(f"write {env_var} into {ENV_PATH}"):
        return f"Not configured — user declined writing {env_var}."

    write_env_var(env_var, credential, path=ENV_PATH)
    setattr(config, env_var, credential)
    _bust_mcp_tools_cache()
    return (
        f"Wrote {env_var} to {ENV_PATH}. The '{name}' MCP server will be "
        "available the next time an agent that uses MCP tools is built "
        "this session, or on the next `hi` restart — not retroactively "
        "for an agent already in use this turn."
    )


@tool
def configure_n8n_server(url: str, token: str) -> str:
    """Configure the n8n MCP server by writing its instance URL and
    bearer token into ~/.hi/.env — n8n needs two values, not the single
    credential configure_mcp_server() handles, so it gets its own tool.

    Args:
        url: The n8n instance's own MCP endpoint, e.g.
            "http://localhost:5678/mcp-server/http".
        token: The bearer token for that instance.
    """
    url = url.strip()
    token = token.strip()
    if not url or not token:
        return "Both url and token are required — nothing written."

    if not confirm_destructive(f"write N8N_MCP_URL and N8N_MCP_TOKEN into {ENV_PATH}"):
        return "Not configured — user declined writing the n8n credentials."

    write_env_var("N8N_MCP_URL", url, path=ENV_PATH)
    write_env_var("N8N_MCP_TOKEN", token, path=ENV_PATH)
    config.N8N_MCP_URL = url
    config.N8N_MCP_TOKEN = token
    _bust_mcp_tools_cache()
    return (
        f"Wrote N8N_MCP_URL and N8N_MCP_TOKEN to {ENV_PATH}. The 'n8n' MCP server will be "
        "available the next time an agent that uses MCP tools is built "
        "this session, or on the next `hi` restart — not retroactively "
        "for an agent already in use this turn."
    )


def _bust_mcp_tools_cache() -> None:
    import hi.mcp_tools as mcp_tools

    mcp_tools._cached_tools = None
    mcp_tools._cached_tools_by_server = None
