"""The run guard: what keeps a background run from doing anything the user has not agreed to.

Every agent has one. In an interactive turn (no policy, or an interactive one) it does nothing. In an unattended
run (hi/core/runpolicy.py) each tool call is checked:

  - over the run's tool-call limit: not run
  - a web tool, when the run may not use the web: not run
  - a screen tool, when the run may not see the screen: not run
  - read-only or explicitly allowed: runs
  - anything else: not run; it is saved as a proposal (hi/memory/proposals.py) and the model is told so

The model gets a normal tool result for every refusal, so it carries on and mentions what it could not do.
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from hi.core import runpolicy
from hi.toolkit import SCREEN_TOOLS, WEB_TOOLS, is_read_only


def _refusal(request, text: str) -> ToolMessage:
    call = request.tool_call
    return ToolMessage(content=text, tool_call_id=call["id"], name=call["name"], status="error")


class RunGuard(AgentMiddleware):
    def _check(self, request) -> ToolMessage | None:
        """A ToolMessage that replaces the call, or None to let it run."""
        state = runpolicy.current()
        if state is None or state.policy.interactive:
            return None
        policy, name = state.policy, request.tool_call["name"]
        state.tool_calls += 1
        if policy.max_tool_calls and state.tool_calls > policy.max_tool_calls:
            return _refusal(request, f"Not run: this background run is limited to {policy.max_tool_calls} tool calls. "
                                     "Finish with what you have.")
        if name in WEB_TOOLS and not policy.allow_web:
            return _refusal(request, "Not run: this background run may not use the web.")
        if name in SCREEN_TOOLS and not policy.allow_screen:
            return _refusal(request, "Not run: the screen is not available to this background run.")
        if name in policy.allowed or is_read_only(name, request.tool):
            return None
        from hi.memory import proposals

        args = request.tool_call.get("args") or {}
        pid = proposals.create(state.origin, state.persona, name, args, reason=f"requested by a {state.origin} run")
        state.proposals.append(pid)
        return _refusal(request, f"Not run: queued for the user's approval as proposal {pid}. "
                                 "Carry on without it and mention it in your answer.")

    def wrap_tool_call(self, request, handler):
        return self._check(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._check(request) or await handler(request)
