import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from hi.agents.term.danger import looks_destructive, looks_long_running
from hi.agents.term.dev_flow_tool import add_dev_flow, open_dev_flow
from hi.agents.term.people import add_person_info, delete_person, get_person_info, list_people
from hi.agents.term.shell_pane import run_in_left_pane
from hi.agents.term.tmux_control import _add_pane, add_pane
from hi.config import TERM_MODEL
from hi.mcp_tools import get_mcp_tools
from hi.memory_graph import build_memory_graph
from hi.vault import (
    append_note,
    create_note,
    list_conversations,
    list_notes,
    read_conversation,
    read_note,
)


@tool
def run_shell_command(command: str) -> str:
    """Run a shell command in the user's own (left-pane) shell and return
    its output and exit code.

    Args:
        command: The literal shell command to run, e.g. "ls -l".
    """
    if looks_long_running(command):
        # A dev server or watch-mode command will never print the
        # completion marker — waiting on it just burns the timeout (or
        # needs a manual Ctrl-J). Redirect it to its own pane instead of
        # relying on the model to remember to do that itself.
        result = _add_pane(command, "horizontal")
        return f"This looks like a long-running process, so it was started in its own pane instead of waiting on it. {result}"

    if looks_destructive(command):
        print(f"\nterm wants to run: {command}")
        confirm = input("Run this? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            return f"Command not run — user declined: {command}"

    output, exit_code = run_in_left_pane(command)
    if exit_code is None:
        # `output` already explains why (Ctrl-J interrupt vs. genuine
        # timeout are different situations, not both just "timed out").
        return output
    return f"Exit code: {exit_code}\nOutput:\n{output}"


PROMPT_PATH = Path(__file__).parent / "term_prompt.md"
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"
TOOLS = [
    run_shell_command,
    add_pane,
    open_dev_flow,
    add_dev_flow,
    create_note,
    append_note,
    read_note,
    list_notes,
    list_conversations,
    read_conversation,
    add_person_info,
    get_person_info,
    delete_person,
    list_people,
]


class _StatefulAgent:
    """Wraps a create_agent() ReAct agent (or, here, the grounding graph
    wrapped around it) to remember the conversation across turns, so term
    can answer follow-up questions from a previous command's output — or
    from a note loaded earlier in the session — without re-running or
    re-searching anything. Every other persona's agent is stateless per
    turn (hi/repl.py sends only the latest message each time) — this stays
    local to term rather than changing that shared behavior."""

    def __init__(self, agent, max_history: int = 20):
        self._agent = agent
        self._messages: list = []
        self._max_history = max_history

    def invoke(self, input: dict, *args, **kwargs) -> dict:
        self._messages.extend(input["messages"])
        result = self._agent.invoke({"messages": self._messages}, *args, **kwargs)
        self._messages = result["messages"][-self._max_history :]
        return result

    def stream(self, input: dict, *args, **kwargs):
        """Forwards every streamed item unchanged (so hi/streaming.py's
        generic loop works the same as on a real CompiledStateGraph), while
        updating our own message history from each "values"-mode payload as
        it goes — the last one seen by the time the caller finishes
        consuming the stream is the final state, same as .invoke() would
        have returned, with no redundant second call."""
        self._messages.extend(input["messages"])
        for item in self._agent.stream({"messages": self._messages}, *args, **kwargs):
            _ns, mode, payload = item
            if mode == "values":
                self._messages = payload["messages"][-self._max_history :]
            yield item


def build_agent(model: BaseChatModel):
    """Build a fresh, independently-stateful term agent bound to `model` —
    used directly below for the default TERM_MODEL instance, and by
    hi/router.py to build one on a router-selected tier instead (each gets
    its own session memory, since they're different underlying agents).

    Wrapped in build_memory_graph the same way `code` used to be (before
    its functionality was merged into term): every turn, relevant
    hi/knowledge/ notes and hi/conversations/ logs are auto-selected and
    loaded as context before the ReAct agent (with its shell/notes/people/
    dev-flow tools) runs — then the whole thing is wrapped in
    _StatefulAgent so that context persists across turns too."""
    system_prompt = PROMPT_PATH.read_text()
    launch_cwd = os.environ.get(LAUNCH_CWD_ENV_VAR)
    if launch_cwd:
        # Shell commands already run there for free (the left pane's real
        # shell starts in that directory) — this is purely for the
        # model's own reasoning/dev-flow awareness, so "commit and push"
        # or "what does this project do" don't require the user to name
        # the directory explicitly.
        system_prompt += f"\n\nYou were launched from: {launch_cwd}\nTreat this as the active project's directory unless told otherwise."
    # get_mcp_tools() is cached (hi/mcp_tools.py) — only the first call in
    # the process actually connects to any MCP servers; a slow/misbehaving
    # server is bounded by its own per-server timeout rather than hanging
    # agent construction indefinitely.
    all_tools = TOOLS + get_mcp_tools()
    note_agent = create_agent(model=model, tools=all_tools, system_prompt=system_prompt)
    grounded_agent = build_memory_graph(note_agent, model)
    return _StatefulAgent(grounded_agent)


model = ChatOllama(
    model=TERM_MODEL,
    temperature=0,
    keep_alive="30m",
)
agent = build_agent(model)
