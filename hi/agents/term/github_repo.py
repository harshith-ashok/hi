"""Repo settings the GitHub MCP server has no tool for (visibility)."""

import httpx
from langchain_core.tools import tool

import hi.config as config

API = "https://api.github.com"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.GITHUB_PERSONAL_ACCESS_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _resolve(repo: str) -> str:
    """'owner/name' as-is; a bare name gets the token owner's login."""
    if "/" in repo:
        return repo
    response = httpx.get(f"{API}/user", headers=_headers(), timeout=15)
    response.raise_for_status()
    return f"{response.json()['login']}/{repo}"


@tool
def set_repo_visibility(repo: str, private: bool) -> str:
    """Make a GitHub repository private or public. The GitHub MCP tools
    cannot do this — use this for "make X private" / "make X public".

    Args:
        repo: "owner/name", or just "name" for one of the user's own repos.
        private: True to make it private, False to make it public.
    """
    if not config.GITHUB_PERSONAL_ACCESS_TOKEN:
        return "No GITHUB_PERSONAL_ACCESS_TOKEN configured."
    try:
        full_name = _resolve(repo)
        response = httpx.patch(
            f"{API}/repos/{full_name}", headers=_headers(), json={"private": private}, timeout=15
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"GitHub returned {e.response.status_code}: {e.response.text[:300]}"
    except httpx.HTTPError as e:
        return f"GitHub request failed: {e}"
    return f"{full_name} is now {'private' if response.json()['private'] else 'public'}."
