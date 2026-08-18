from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from hi.agents.term.danger import looks_destructive
from hi.agents.term.dev_flow_tool import open_dev_flow
from hi.agents.term.people import add_person_info, delete_person, get_person_info, list_people
from hi.agents.term.shell_pane import run_in_left_pane
from hi.config import TERM_MODEL
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
    if looks_destructive(command):
        print(f"\nterm wants to run: {command}")
        confirm = input("Run this? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            return f"Command not run — user declined: {command}"

    output, exit_code = run_in_left_pane(command)
    if exit_code is None:
        return (
            f"Command timed out waiting for a result (may still be running):\n{output}"
        )
    return f"Exit code: {exit_code}\nOutput:\n{output}"


PROMPT_PATH = Path(__file__).parent / "term_prompt.md"
TOOLS = [
    run_shell_command,
    open_dev_flow,
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
    note_agent = create_agent(model=model, tools=TOOLS, system_prompt=PROMPT_PATH.read_text())
    grounded_agent = build_memory_graph(note_agent, model)
    return _StatefulAgent(grounded_agent)


model = ChatOllama(
    model=TERM_MODEL,
    temperature=0,
    keep_alive="30m",
)
agent = build_agent(model)
