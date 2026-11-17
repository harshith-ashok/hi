from fakes import Scripted, tool_call
from langchain_core.messages import AIMessage, HumanMessage

from hi import toolkit
from hi.agents.ask import MAX_QUESTIONS, ask_user
from hi.agents.base import make_agent
from hi.core.runpolicy import UNATTENDED, run_scope


def test_the_tool_tells_the_model_to_stop_and_wait():
    out = ask_user.invoke({"questions": ["Which branch?", "Force push?"]})
    assert "End your turn" in out


def test_no_usable_question_tells_the_model_to_assume():
    assert "sensible default" in ask_user.invoke({"questions": ["  ", ""]})


def test_the_questions_are_in_the_tool_call_arguments_the_ui_reads():
    agent = make_agent(Scripted(messages=iter([tool_call("ask_user", {"questions": ["Which branch?"]}), AIMessage("")])), [ask_user])
    result = agent.invoke({"messages": [HumanMessage("delete the old branches")]})
    call = next(m for m in result["messages"] if getattr(m, "tool_calls", None)).tool_calls[0]
    assert call["name"] == "ask_user" and call["args"] == {"questions": ["Which branch?"]}


def test_a_background_run_may_not_ask_and_it_is_not_made_a_proposal(tmp_vault):
    from hi.memory import proposals

    agent = make_agent(Scripted(messages=iter([tool_call("ask_user", {"questions": ["Which?"]}), AIMessage("assumed")])), [ask_user])
    with run_scope(UNATTENDED, "heartbeat"):
        result = agent.invoke({"messages": [HumanMessage("go")]})
    tool_msg = next(m for m in result["messages"] if m.type == "tool")
    assert "nobody is here" in tool_msg.content and proposals.pending() == []


def test_both_chat_personas_offer_it():
    from hi.agents.butler import butler
    from hi.agents.term import term

    assert "ask_user" in {t.name for t in term.TOOLS} and "ask_user" in {t.name for t in butler.TOOLS}
    group = next(g for g in toolkit.GROUPS if g.name == "ask")
    assert group.name in term.TERM_GROUPS and group.priority == 1
    assert MAX_QUESTIONS == 4
