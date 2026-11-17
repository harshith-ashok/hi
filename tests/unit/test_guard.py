from fakes import Scripted
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from hi.agents.base import make_agent
from hi.core.runpolicy import INTERACTIVE, UNATTENDED, run_scope
from hi.memory import proposals


def call(name, args=None, id="c1"):
    return AIMessage("", tool_calls=[{"name": name, "args": args or {}, "id": id}])


def run(tools, script, policy=None, origin="heartbeat"):
    """Run an agent over `script`; returns (final answer, run state or None)."""
    agent = make_agent(Scripted(messages=iter(script)), tools)
    if policy is None:
        return agent.invoke({"messages": [HumanMessage("go")]})["messages"][-1].content, None
    with run_scope(policy, origin) as state:
        return agent.invoke({"messages": [HumanMessage("go")]})["messages"][-1].content, state


def make_tools():
    ran = []

    @tool
    def send_email(to: str) -> str:
        """Send an email."""
        ran.append(("send_email", to))
        return "sent"

    @tool
    def read_note(path: str) -> str:
        """Read a note."""
        ran.append(("read_note", path))
        return "contents"

    return ran, send_email, read_note


def test_an_interactive_turn_runs_every_tool_unchanged(tmp_vault):
    ran, send_email, _ = make_tools()
    answer, _ = run([send_email], [call("send_email", {"to": "a"}), AIMessage("done")])
    assert ran == [("send_email", "a")] and answer == "done"
    assert proposals.pending() == []


def test_an_interactive_policy_is_not_guarded(tmp_vault):
    ran, send_email, _ = make_tools()
    run([send_email], [call("send_email", {"to": "a"}), AIMessage("done")], policy=INTERACTIVE, origin="ui")
    assert ran == [("send_email", "a")]


def test_an_unattended_run_turns_a_risky_tool_into_a_proposal(tmp_vault):
    ran, send_email, _ = make_tools()
    answer, state = run([send_email], [call("send_email", {"to": "bob@acme.com"}), AIMessage("queued it")], UNATTENDED)
    assert ran == []  # the tool never ran
    assert answer == "queued it"
    (p,) = proposals.pending()
    assert p["tool"] == "send_email" and p["args"] == {"to": "bob@acme.com"} and p["origin"] == "heartbeat"
    assert state.proposals == [p["id"]]


def test_an_unattended_run_may_use_read_only_tools(tmp_vault):
    ran, _, read_note = make_tools()
    run([read_note], [call("read_note", {"path": "a.md"}), AIMessage("ok")], UNATTENDED)
    assert ran == [("read_note", "a.md")] and proposals.pending() == []


def test_a_tool_the_policy_allows_explicitly_runs(tmp_vault):
    ran, send_email, _ = make_tools()
    run([send_email], [call("send_email", {"to": "a"}), AIMessage("ok")], UNATTENDED.with_allowed(["send_email"]))
    assert ran == [("send_email", "a")] and proposals.pending() == []


def test_the_tool_call_limit_stops_a_runaway_run(tmp_vault):
    ran, _, read_note = make_tools()
    script = [call("read_note", {"path": str(i)}, id=f"c{i}") for i in range(5)] + [AIMessage("stopped")]
    answer, state = run([read_note], script, UNATTENDED.__class__(**{**UNATTENDED.__dict__, "max_tool_calls": 2}))
    assert len(ran) == 2 and answer == "stopped"


def test_web_and_screen_tools_are_refused_when_the_run_may_not_use_them(tmp_vault):
    ran = []

    @tool
    def web_search(query: str) -> str:
        """Search."""
        ran.append(query)
        return "results"

    @tool
    def read_screen() -> str:
        """Screen."""
        ran.append("screen")
        return "text"

    no_web = UNATTENDED.__class__(**{**UNATTENDED.__dict__, "allow_web": False})
    run([web_search, read_screen], [call("web_search", {"query": "x"}), call("read_screen", id="c2"), AIMessage("ok")], no_web)
    assert ran == []  # neither ran, and neither became a proposal
    assert proposals.pending() == []


def test_an_mcp_tool_marked_read_only_may_run(tmp_vault):
    ran = []

    @tool
    def lookup_thing(q: str) -> str:
        """A read-only MCP tool."""
        ran.append(q)
        return "found"

    lookup_thing.metadata = {"readOnlyHint": True}  # how langchain-mcp-adapters carries a server's annotations
    run([lookup_thing], [call("lookup_thing", {"q": "a"}), AIMessage("ok")], UNATTENDED)
    assert ran == ["a"]
