"""Run an approved proposal: look up the tool it names and call it once with the arguments the user approved.

The order matters. `begin_execution` moves the proposal out of `created` before the tool runs, under a lock, so
an approval clicked twice runs the tool once; a crash in the middle leaves it `executing`, which startup turns into
`failed` and never runs again (a tool that failed may have half-done something, so it is never retried).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from hi.core import runpolicy
from hi.memory import journal, proposals

log = logging.getLogger(__name__)

TOOL_LISTS = ("term", "butler", "web", "docs")
RESULT_CHARS = 2000


class NotWaiting(Exception):
    """The proposal does not exist or is not waiting for an answer (already answered, expired)."""


def _tools(persona: str) -> list[BaseTool]:
    from hi.mcp_tools import get_mcp_tools

    if persona == "term":
        from hi.agents.term import term

        return [*term.TOOLS, *get_mcp_tools()]
    if persona == "butler":
        from hi.agents.butler import butler

        return list(butler.TOOLS)
    if persona == "web":
        from hi.agents.web import web

        return list(web.TOOLS)
    return []


def find_tool(name: str, persona: str = "") -> BaseTool | None:
    """The tool called `name`, looking in `persona`'s tools first and then in every persona's."""
    for p in dict.fromkeys([persona, *TOOL_LISTS]):
        if p and (tool := next((t for t in _tools(p) if t.name == name), None)):
            return tool
    return None


def run(proposal_id: str) -> dict:
    """Approve and execute. Raises NotWaiting if it is not waiting. Returns {"status", "result"}."""
    proposal = proposals.begin_execution(proposal_id)
    if proposal is None:
        raise NotWaiting(proposal_id)
    journal.record_event("approved", f"{proposal['id']}: {proposals.describe(proposal)}")
    tool = find_tool(proposal["tool"], proposal.get("persona", ""))
    if tool is None:
        proposals.mark(proposal_id, proposals.FAILED, f"tool {proposal['tool']!r} is not available")
        return {"status": proposals.FAILED, "result": f"tool {proposal['tool']!r} is not available"}
    try:
        with runpolicy.pre_approved():
            result = str(tool.invoke(proposal.get("args") or {}))[:RESULT_CHARS]
    except Exception as e:  # boundary: a tool failing is the outcome to record, not a crash
        log.exception("approved proposal %s failed", proposal_id)
        proposals.mark(proposal_id, proposals.FAILED, str(e) or type(e).__name__)
        return {"status": proposals.FAILED, "result": str(e) or type(e).__name__}
    proposals.mark(proposal_id, proposals.EXECUTED, result)
    return {"status": proposals.EXECUTED, "result": result}


def deny(proposal_id: str) -> None:
    """Raises NotWaiting if it is not waiting."""
    if not proposals.deny(proposal_id):
        raise NotWaiting(proposal_id)
    journal.record_event("denied", proposal_id)
