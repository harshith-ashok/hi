import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive
from hi.agents.term.danger import looks_destructive, looks_long_running
from hi.orchestrator.reviewer import review_shell_command
from hi.agents.term.dev_flow_tool import add_dev_flow, open_dev_flow
from hi.agents.term.files import (
    edit_project_file,
    list_project_files,
    read_project_file,
    search_files,
    write_project_file,
)
from hi.agents.term.people import add_person_info, delete_person, get_person_info, list_people
from hi.agents.term.save_project import save_project_to_vault
from hi.agents.term.resume import resume_context
from hi.agents.term.shell_pane import run_in_left_pane
from hi.agents.term.tmux_control import _add_pane, add_pane
from hi.browser import open_url_in_browser
from hi.chat_model import make_chat_model
from hi.config import TERM_MODEL
from hi.mcp_tools import get_mcp_tools
from hi.memory_graph import build_memory_graph
from hi.orchestrator.graph import latest_run_trace
from hi.perception.browser import observe_current_tab
from hi.perception.screen import read_screen
from hi.perception.vision import ask_about_screen
from hi.suggest.engine import check_suggestions
from hi.synthesis.arbiter import what_next, what_next_smart
from hi.synthesis.longcontext import synthesize_vault
from hi.synthesis.reflection import reflect_on_week
from hi.synthesis.retro import generate_retro, generate_retro_smart
from hi.tracking.applications import add_application, list_applications, update_application_status
from hi.tracking.deadlines import list_deadlines
from hi.tracking.leetcode import leetcode_daily, leetcode_stats, log_leetcode_attempt
from hi.tracking.pipeline import (
    add_pipeline_entry,
    create_pipeline,
    list_pipeline_entries,
    update_pipeline_entry_stage,
)
from hi.tracking.team_ops import (
    assign_task_owner,
    team_deadline_pings,
    team_status_draft,
)
from hi.watchdogs.dev_servers import check_dev_servers
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
        # TODO.md Phase 20: a second, cheap-tier check on the exact
        # command before the human/pending-approval gate ever sees it —
        # concatenated into the same confirmation description rather
        # than a separate prompt, so both the interactive y/N path and
        # the orchestrated pending-approval queue (hi/action_tiers.py's
        # confirm_destructive() already routes to whichever applies)
        # surface it identically, with no extra plumbing per path.
        description = f"run: {command}"
        concern = review_shell_command(command)
        if concern:
            description += f"\n⚠️ reviewer flag: {concern}"
        if not confirm_destructive(description):
            return f"Command not run — user declined: {command}"

    output, exit_code = run_in_left_pane(command)
    if exit_code is None:
        # `output` already explains why (Ctrl-J interrupt vs. genuine
        # timeout are different situations, not both just "timed out").
        return output
    return f"Exit code: {exit_code}\nOutput:\n{output}"


@tool
def show_last_run_trace() -> str:
    """Replay the most recent orchestrated multi-subagent run's own log
    note (TODO.md Phase 19) — its DAG shape, which subagent did what,
    real tool calls made, and the final synthesized answer. Use for
    "show me how you did that" / "what did the last plan actually do"
    style questions, right after an orchestrated run. Returns a message
    saying none exists yet if no orchestrated run has ever completed.
    """
    trace = latest_run_trace()
    if trace is None:
        return "No orchestrated run has completed yet — nothing to trace."
    return trace


PROMPT_PATH = Path(__file__).parent / "term_prompt.md"
LAUNCH_CWD_ENV_VAR = "HI_LAUNCH_CWD"

# run_shell_command/add_pane both ultimately call shell_pane.py's
# _own_pane_id(), which raises a raw RuntimeError if TMUX_PANE isn't set
# — true for every tmux-launched persona (tmux exports it into the
# pane's environment automatically, before the process even starts) but
# NEVER true for hi --voice-daemon, which has no tmux pane at all. That
# used to mean the model could still try calling these tools from the
# voice companion/web frontend and get back a raw, confusing tmux error
# as a "tool result" instead of a clean answer. Excluding them from
# TOOLS entirely when there's no tmux context — evaluated once at import
# time, since a process either has a tmux pane for its whole lifetime or
# never does — means the model never sees them as an option at all in
# that case, and (per term_prompt.md's own updated instructions) reaches
# for read_project_file/search_files instead or says plainly it can't
# run a real shell command right now.
_HAS_TMUX_PANE = bool(os.environ.get("TMUX_PANE"))
_TMUX_ONLY_TOOLS = [run_shell_command, add_pane] if _HAS_TMUX_PANE else []

TOOLS = [
    *_TMUX_ONLY_TOOLS,
    open_dev_flow,
    add_dev_flow,
    read_project_file,
    list_project_files,
    search_files,
    write_project_file,
    edit_project_file,
    save_project_to_vault,
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
    resume_context,
    check_dev_servers,
    list_deadlines,
    leetcode_daily,
    log_leetcode_attempt,
    leetcode_stats,
    add_application,
    update_application_status,
    list_applications,
    what_next,
    what_next_smart,
    generate_retro,
    generate_retro_smart,
    reflect_on_week,
    synthesize_vault,
    show_last_run_trace,
    check_suggestions,
    assign_task_owner,
    team_status_draft,
    team_deadline_pings,
    create_pipeline,
    add_pipeline_entry,
    update_pipeline_entry_stage,
    list_pipeline_entries,
    observe_current_tab,
    open_url_in_browser,
    read_screen,
    ask_about_screen,
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


model = make_chat_model(TERM_MODEL, temperature=0, keep_alive="30m")
agent = build_agent(model)
