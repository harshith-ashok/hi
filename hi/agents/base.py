"""The one place an agent is assembled: tools, optional tool selection, and the shared retry policy.

Each persona module supplies its tools and prompt and calls `make_agent`, so a policy change (for
example a new middleware every agent should have) is made here once.
"""

from __future__ import annotations

from typing import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from hi.llm.resilience import retry_middleware
from hi.toolkit import ToolSelector


def make_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
    selector: ToolSelector | None = None,
    middleware: Sequence[AgentMiddleware] = (),
):
    """A ReAct agent on `model`. With a `selector`, the model only sees the tools it picks for each
    turn (plus its `more_tools` escape hatch). `middleware` runs before the selector, and the retry
    policy always runs last."""
    all_tools = list(tools)
    stack = list(middleware)
    if selector is not None:
        all_tools.append(selector.more_tools)
        stack.append(selector)
    stack.append(retry_middleware())
    return create_agent(model=model, tools=all_tools, system_prompt=system_prompt, middleware=stack)
