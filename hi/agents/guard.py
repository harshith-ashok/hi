"""The run guard: what keeps a background run from doing anything the user has not agreed to.

Every agent has one. In an interactive turn (no policy, or an interactive one) it does nothing. In an unattended
run (hi/core/runpolicy.py) each tool call is checked:

  - over the run's tool-call limit: not run
  - a web tool, when the run may not use the web: not run
  - a screen tool, when the run may not see the screen: not run
  - read-only or explicitly allowed: runs
  - anything else: not run; it is saved as a proposal (hi/memory/proposals.py) and the model is told so

The model gets a normal tool result for every refusal, so it carries on and mentions what it could not do.

Two checks guard what leaves your machine, and they are why this middleware also watches the model call:

  - A `fetch` whose URL contains one of your credentials is refused in every run (and, in an unattended run, one
    that merely looks like a token is refused too).
  - An unattended run that talks to a hosted (cloud) model has every message, the system prompt included, redacted
    first: a background run is assembled from your vault and nobody is there to notice what went into it.
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

import hi.config as config
from hi import llm
from hi.core import runpolicy
from hi.core.redact import contains_secret, redact
from hi.toolkit import SCREEN_TOOLS, WEB_TOOLS, is_read_only


def _refusal(request, text: str) -> ToolMessage:
    call = request.tool_call
    return ToolMessage(content=text, tool_call_id=call["id"], name=call["name"], status="error")


def _is_hosted(model) -> bool:
    try:
        return "cloud" in str(llm.model_name(model))
    except AttributeError:
        return False


def _redact_message(message: BaseMessage, known: list[str]) -> BaseMessage:
    if isinstance(message.content, str):
        return message.model_copy(update={"content": redact(message.content, known)})
    if isinstance(message.content, list):  # text parts only; images and other parts pass through
        parts = [{**p, "text": redact(p["text"], known)} if isinstance(p, dict) and isinstance(p.get("text"), str) else p
                 for p in message.content]
        return message.model_copy(update={"content": parts})
    return message


def _secret_in_url(request, unattended: bool) -> bool:
    """A `fetch` URL that carries a credential. Interactive: only the exact values of your own settings. Unattended:
    anything shaped like a token too."""
    url = str((request.tool_call.get("args") or {}).get("url", ""))
    known = config.secret_values()
    return contains_secret(url, known) if unattended else any(v in url for v in known)


class RunGuard(AgentMiddleware):
    def _check(self, request) -> ToolMessage | None:
        """A ToolMessage that replaces the call, or None to let it run."""
        state = runpolicy.current()
        unattended = state is not None and not state.policy.interactive
        if request.tool_call["name"] == "fetch" and _secret_in_url(request, unattended):
            return _refusal(request, "Not fetched: the URL contains something that looks like a secret.")
        if not unattended:
            return None
        policy, name = state.policy, request.tool_call["name"]
        state.tool_calls += 1
        if policy.max_tool_calls and state.tool_calls > policy.max_tool_calls:
            return _refusal(request, f"Not run: this background run is limited to {policy.max_tool_calls} tool calls. "
                                     "Finish with what you have.")
        if name == "ask_user":
            return _refusal(request, "Not asked: nobody is here to answer a background run. Make a reasonable "
                                     "assumption, say what you assumed, and carry on.")
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

    def _for_model(self, request):
        """`request`, with every message redacted when an unattended run is about to call a hosted model."""
        state = runpolicy.current()
        if state is None or state.policy.interactive or not _is_hosted(request.model):
            return request
        known = config.secret_values()
        system = request.system_message
        return request.override(
            messages=[_redact_message(m, known) for m in request.messages],
            system_message=_redact_message(system, known) if isinstance(system, SystemMessage) else system,
        )

    def wrap_model_call(self, request, handler):
        return handler(self._for_model(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._for_model(request))

    def wrap_tool_call(self, request, handler):
        return self._check(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._check(request) or await handler(request)
