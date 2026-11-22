import hi.config as config
from hi.memory import records, sessions, transcript
from hi.memory.records import TurnRecord, record_turn
import pytest


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: None)
    monkeypatch.setattr(sessions, "retitle_async", lambda *a, **k: None)


def chat(turns, answer_chars=900):
    s = sessions.create().id
    for i in range(turns):
        record_turn(TurnRecord("term", "sonnet", f"question {i}", f"{i} " + "x" * answer_chars, session=s))
    return s


def test_a_short_chat_is_sent_whole(tmp_vault):
    s = chat(3)
    messages, dropped = transcript.history_within(100_000, s)
    assert dropped == 0 and [m["content"] for m in messages if m["role"] == "user"] == ["question 0", "question 1", "question 2"]


def test_a_long_chat_drops_the_oldest_turns_first(tmp_vault):
    s = chat(10)  # each exchange is about 300 tokens
    messages, dropped = transcript.history_within(1000, s)
    asks = [m["content"] for m in messages if m["role"] == "user"]
    assert dropped == 10 - len(asks) and 0 < len(asks) < 10
    assert asks == [f"question {i}" for i in range(10 - len(asks), 10)]  # the newest, in order


def test_one_huge_answer_is_clipped_not_dropped(tmp_vault):
    s = chat(1, answer_chars=100_000)
    messages, dropped = transcript.history_within(400, s)
    assert dropped == 0 and len(messages) == 2 and messages[1]["content"].endswith("…[clipped]") and len(messages[1]["content"]) < 5000


def test_the_newest_exchange_is_kept_even_with_no_budget(tmp_vault):
    s = chat(3)
    messages, dropped = transcript.history_within(-50, s)
    assert dropped == 2 and messages[0]["content"] == "question 2"


def test_the_budget_pays_for_the_prompt_the_message_and_the_reply(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_TOKENS", 16384)
    expected = 16384 - transcript.ANSWER_RESERVE_TOKENS - transcript.PROMPT_OVERHEAD_TOKENS - transcript.estimate_tokens("hello")
    assert transcript.history_budget("hello") == expected
    assert transcript.history_budget("x" * 3000) < transcript.history_budget("hello")
