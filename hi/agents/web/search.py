"""`web_search`: ask the private SearXNG instance (the `searxng` compose service) and return numbered results.

It is the model's way to look at the web for anything current or outside the vault. Queries stay on your own
machine until SearXNG fans them out to public engines, so a query is refused outright if it contains a secret.
When SearXNG is down the dependency is marked down (hi/core/health.py) and the tool is hidden from the model.
"""

from __future__ import annotations

import time

import httpx
from langchain_core.tools import tool

import hi.config as config
from hi.core import health
from hi.core.redact import contains_secret

TIMEOUT_S = 8.0
CACHE_TTL_S = 600.0
MAX_RESULTS = 10
SNIPPET_CHARS = 280
CATEGORIES = ("general", "news", "it", "science", "files", "social media")
TIME_RANGES = ("", "day", "week", "month", "year")

_cache: dict[tuple, tuple[float, str]] = {}


def _fetch(params: dict) -> dict:
    """The one network call. Raises httpx.HTTPError on any failure."""
    response = httpx.get(f"{config.SEARXNG_URL.rstrip('/')}/search", params=params, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def format_results(data: dict, limit: int) -> str:
    results = data.get("results") or []
    if not results:
        return "No results."
    lines = []
    for n, r in enumerate(results[:limit], start=1):
        snippet = " ".join((r.get("content") or "").split())[:SNIPPET_CHARS]
        engines = ", ".join(r.get("engines") or [r.get("engine", "")]).strip(", ")
        lines.append(f"[{n}] {r.get('title', '').strip() or r.get('url', '')} — {r.get('url', '')}"
                     + (f"\n    {snippet}" if snippet else "") + (f" ({engines})" if engines else ""))
    return "\n".join(lines)


def search(query: str, limit: int = 5, time_range: str = "", category: str = "general", now: float | None = None) -> str:
    """The text `web_search` returns. `now` is for tests."""
    query = " ".join(query.split())
    if not query:
        return "Not searched: the query is empty."
    if contains_secret(query, config.secret_values()):
        return "Not searched: the query contains something that looks like a secret. Search for the public part only."
    limit = max(1, min(int(limit), MAX_RESULTS))
    time_range = time_range if time_range in TIME_RANGES else ""
    category = category if category in CATEGORIES else "general"
    key = (query.lower(), limit, time_range, category)
    now = time.time() if now is None else now
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    params = {"q": query, "format": "json", "categories": category}
    if time_range:
        params["time_range"] = time_range
    try:
        text = format_results(_fetch(params), limit)
    except (httpx.HTTPError, ValueError) as e:
        health.mark_down("searxng", e)
        return f"Web search is unavailable right now ({type(e).__name__}). Answer from what you know and say that you could not check."
    health.mark_ok("searxng")
    try:
        from hi.memory import journal

        journal.record_event("search", query)
    except OSError:
        pass  # the journal is a record, never a reason to lose the results
    _cache[key] = (now, text)
    return text


@tool
def web_search(query: str, limit: int = 5, time_range: str = "", category: str = "general") -> str:
    """Search the web (a private SearXNG) and get numbered results with titles, URLs and snippets. Use it for
    anything current, or that is outside the user's notes. Read the best one or two results with `fetch` before
    you answer, and cite them as [n]. Search for the public part only (an error message, a library name), never
    for the user's private text.

    Args:
        query: What to search for.
        limit: How many results, 1 to 10.
        time_range: Only results from the last "day", "week", "month" or "year". Empty for any time.
        category: general, news, it, science, files or social media.
    """
    return search(query, limit, time_range, category)
