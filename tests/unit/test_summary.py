import pytest

from hi.core import health
from hi.memory import records, sessions, summary, transcript
from hi.memory.records import TurnRecord, record_turn


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    health.reset()
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)


def chat(turns):
    s = sessions.create().id
    for i in range(turns):
        record_turn(TurnRecord("term", "sonnet", f"question {i}", f"answer {i}", session=s))
    return s


def test_the_summary_is_stored_in_the_session_note_and_read_back(tmp_vault):
    s = chat(4)
    head = sessions.head_of(s)
    assert summary.summarise(s, head, 2, fold=lambda prev, turns: "they discussed 0 and 1")
    saved = sessions.get(s)
    assert saved.summary == "they discussed 0 and 1"
    assert saved.summary_through == transcript.counted_turns(s)[1]["id"]
    assert "they discussed 0 and 1" in sessions._path(s).read_text()
    messages = summary.messages(saved.summary)
    assert messages[0]["role"] == "user" and "they discussed" in messages[0]["content"] and messages[1]["role"] == "assistant"


def test_it_only_folds_in_turns_the_summary_does_not_cover_yet(tmp_vault):
    s = chat(5)
    head = sessions.head_of(s)
    calls = []

    def fold(previous, turns):
        calls.append((previous, [t["ask"] for t in turns]))
        return f"summary of {len(turns)}"

    summary.summarise(s, head, 2, fold)
    assert not summary.summarise(s, head, 2, fold)  # nothing new
    summary.summarise(s, head, 4, fold)
    assert calls == [("", ["question 0", "question 1"]), ("summary of 2", ["question 2", "question 3"])]


def test_a_failing_summary_model_does_not_break_the_chat_and_backs_off(tmp_vault):
    s = chat(3)

    def down(previous, turns):
        raise RuntimeError("ollama is down")

    assert not summary.summarise(s, sessions.head_of(s), 2, down)
    assert sessions.get(s).summary == "" and not health.is_up(summary.DEP)
    assert not summary.summarise(s, sessions.head_of(s), 2, lambda *a: "never called while backing off")


def test_a_summary_of_another_branch_is_not_continued(tmp_vault):
    s = chat(3)
    sessions.set_summary(s, "from a branch that is gone", "no-such-turn")
    seen = []
    summary.summarise(s, sessions.head_of(s), 2, lambda prev, turns: seen.append(prev) or "fresh")
    assert seen == [""] and sessions.get(s).summary == "fresh"
