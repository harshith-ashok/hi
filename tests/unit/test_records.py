import json

import pytest

from hi.memory import records
from hi.memory.records import TurnRecord, record_turn


@pytest.fixture(autouse=True)
def _no_background_learning(monkeypatch):
    calls = []
    monkeypatch.setattr(records.extraction, "extract_async", lambda *a: calls.append(a))
    return calls


def files(vault, sub):
    return sorted((vault / "hi" / sub).glob("*"))


def test_an_answered_turn_reaches_every_log(tmp_vault, _no_background_learning):
    tools = [{"name": "read_note", "args": "{}", "result": "ok"}]
    record_turn(TurnRecord("term", "sonnet", "what is kaapi", "a project", tools, 1.5))

    (transcript,) = files(tmp_vault, "transcripts")
    entry = json.loads(transcript.read_text())
    assert entry["ask"] == "what is kaapi" and entry["answer"] == "a project" and entry["tools"] == tools
    assert "**Assistant:** a project" in files(tmp_vault, "conversations")[0].read_text()
    assert "Answered" in files(tmp_vault, "journal")[0].read_text()
    assert _no_background_learning == [("what is kaapi", "a project", ["read_note"])]


def test_a_failed_turn_is_in_the_transcript_and_journal_but_not_the_conversation(tmp_vault, _no_background_learning):
    record_turn(TurnRecord("term", "", "hello", error="Ollama is down", detail="ConnectError()"))

    entry = json.loads(files(tmp_vault, "transcripts")[0].read_text())
    assert entry["error"] == "ConnectError()" and entry["answer"] == ""
    assert "Ollama is down" in files(tmp_vault, "journal")[0].read_text()
    assert files(tmp_vault, "conversations") == []
    assert _no_background_learning == []


def test_a_turn_with_no_answer_and_no_error_only_goes_to_the_transcript(tmp_vault):
    record_turn(TurnRecord("term", "sonnet", "hi"))
    assert len(files(tmp_vault, "transcripts")) == 1
    assert files(tmp_vault, "conversations") == [] and files(tmp_vault, "journal") == []


def test_one_failing_sink_does_not_stop_the_others(tmp_vault, monkeypatch):
    def broken(rec):
        raise OSError("disk full")

    monkeypatch.setattr(records, "SINKS", [records._transcript, broken, records._conversation])
    record_turn(TurnRecord("term", "sonnet", "q", "a"))  # must not raise
    assert len(files(tmp_vault, "transcripts")) == 1 and len(files(tmp_vault, "conversations")) == 1
