from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from hi import toolkit
from hi.core import health


class FakeChat(GenericFakeChatModel):
    """A chat model that always answers "ok" and accepts tool binding."""

    def bind_tools(self, tools, **kwargs):
        return self


def fake_model():
    return FakeChat(messages=iter([AIMessage("ok")] * 20))


def answer(agent) -> str:
    result = agent.invoke({"messages": [HumanMessage("hi")]})
    return result["messages"][-1].content


def test_butler_builds_and_answers():
    from hi.agents.butler.butler import build_agent

    assert answer(build_agent(fake_model())) == "ok"


def test_web_builds_and_answers(monkeypatch):
    from hi.agents.web import web

    monkeypatch.setattr(web, "get_mcp_tools_by_server", lambda: {})
    assert answer(web.build_agent(fake_model())) == "ok"


def test_term_builds_and_answers(monkeypatch):
    from hi.agents.term import term

    monkeypatch.setattr(term, "get_mcp_tools", lambda: [])
    monkeypatch.setattr(term, "tool_servers", lambda: {})
    monkeypatch.setattr(term, "build_context", lambda message: "")
    monkeypatch.setattr(term, "screen_context", lambda: "")
    agent = term.build_agent(fake_model())
    result = agent.invoke({"messages": [HumanMessage("hi")]})
    assert result["messages"][-1].content == "ok"


def test_importing_agent_modules_builds_no_model():
    import importlib

    for name in ("hi.agents.term.term", "hi.agents.butler.butler", "hi.agents.docs.docs", "hi.agents.web.web"):
        module = importlib.import_module(name)
        assert not hasattr(module, "agent") and not hasattr(module, "model"), name


@pytest.fixture
def clean_health():
    health.reset()
    yield
    health.reset()


def test_tools_needing_a_down_dependency_are_hidden(clean_health):
    assert toolkit.required_dependency("mute") == "host_bridge"
    assert toolkit.required_dependency("run_python") == "sandbox"
    assert toolkit.required_dependency("read_note") is None

    health.mark_down("host_bridge", "refused")
    assert not toolkit.dependency_is_up("mute") and toolkit.dependency_is_up("read_note")
    assert toolkit.dependency_is_up("run_python")


def test_the_selector_does_not_offer_tools_whose_dependency_is_down(clean_health):
    @tool
    def read_note(path: str) -> str:
        """read"""
        return ""

    @tool
    def mute() -> str:
        """mute"""
        return ""

    selector = toolkit.ToolSelector([read_note, mute])
    request = SimpleNamespace(tools=[read_note, mute], messages=[HumanMessage("mute it")])
    request.override = lambda **kw: SimpleNamespace(**{**vars(request), **kw})
    offered = lambda: sorted(t.name for t in selector.wrap_model_call(request, lambda r: r).tools)

    assert "mute" in offered()
    health.mark_down("host_bridge", "refused")
    assert "mute" not in offered() and "read_note" in offered()
