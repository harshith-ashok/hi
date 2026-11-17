import json
import sys

import pytest

import hi.config as config
from hi.context import inbox, now


@pytest.fixture(autouse=True)
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(now, "DIR", tmp_path)
    monkeypatch.setattr(inbox, "INBOX", tmp_path / "inbox.jsonl")
    monkeypatch.setattr(inbox, "LOG", tmp_path / "inbox_log.jsonl")
    monkeypatch.setattr(inbox, "BUDGET", tmp_path / "notify_times.json")
    monkeypatch.setattr(inbox, "DEDUPE", tmp_path / "dedupe.json")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(config, "MAX_NOTIFICATIONS_PER_HOUR", 3)
    notified = []
    monkeypatch.setattr(inbox, "_system_notification", notified.append)
    monkeypatch.setattr("hi.menubar.lock.lock_is_free", lambda: False)  # the island is running
    return notified


def shown():
    try:
        return [json.loads(line) for line in inbox.INBOX.read_text().splitlines()]
    except OSError:
        return []


def test_a_message_is_shown_with_its_kind_and_payload():
    assert inbox.post("hello", kind="digest", payload={"report_id": "r1"}) == "shown"
    (item,) = shown()
    assert item["message"] == "hello" and item["kind"] == "digest" and item["payload"] == {"report_id": "r1"}


def test_the_same_dedupe_key_is_shown_once_a_day():
    assert inbox.post("a", dedupe_key="k") == "shown"
    assert inbox.post("a again", dedupe_key="k") == "deduped"
    assert inbox.post("other", dedupe_key="k2") == "shown"
    assert len(shown()) == 2


def test_the_hourly_budget_is_shared_and_ordinary_messages_stop_at_it():
    assert [inbox.post(f"m{i}") for i in range(4)] == ["shown", "shown", "shown", "budget"]


def test_approvals_reminders_failures_and_urgent_skip_the_budget_but_not_dedupe():
    for i in range(3):
        inbox.post(f"m{i}")
    assert inbox.post("approve?", kind="approval", dedupe_key="a") == "shown"
    assert inbox.post("remind", kind="reminder") == "shown"
    assert inbox.post("broke", kind="failure") == "shown"
    assert inbox.post("now!", priority="urgent") == "shown"
    assert inbox.post("approve?", kind="approval", dedupe_key="a") == "deduped"


def test_exempt_messages_do_not_use_up_the_budget():
    for _ in range(5):
        inbox.post("x", kind="reminder")
    assert inbox.budget_left() == 3


def test_ignored_messages_make_ordinary_ones_quiet_but_not_approvals():
    for i in range(3):
        inbox.log_outcome({"id": str(i), "message": "m"}, "ignored")
    assert inbox.post("nudge") == "quiet"
    assert inbox.post("approve?", kind="approval") == "shown"


def test_a_closed_island_falls_back_to_a_system_notification(monkeypatch, gate):
    monkeypatch.setattr("hi.menubar.lock.lock_is_free", lambda: True)
    assert inbox.post("hello") == "notified" and gate == ["hello"] and shown() == []


def test_off_a_mac_nothing_is_shown(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert inbox.post("hello") == "unsupported"


def test_the_hint_tells_you_what_you_can_answer():
    assert "yes" in inbox.hint_for({"kind": "approval", "payload": {"proposal_id": "P-1"}})
    assert "Inbox" in inbox.hint_for({"kind": "digest", "payload": {"report_id": "r1"}})
    assert "tinyui" in inbox.hint_for({"kind": "approval", "payload": {"action_id": "a", "truncated": True}})


def test_yes_and_no_answer_an_approval_and_anything_else_is_an_ordinary_reply():
    sent = []
    item = {"kind": "approval", "payload": {"proposal_id": "P-1"}}
    assert inbox.answer_approval(item, "Yes!", sent.append) == "Approved. Running it now."
    assert inbox.answer_approval(item, "no", sent.append) == "Denied. Nothing was run."
    assert inbox.answer_approval(item, "what does it say?", sent.append) is None
    assert sent == [f"{inbox.BACKEND}/proposals/P-1/approve", f"{inbox.BACKEND}/proposals/P-1/deny"]


def test_a_live_approval_goes_to_the_pending_route():
    sent = []
    inbox.answer_approval({"payload": {"action_id": "ab12"}}, "y", sent.append)
    assert sent == [f"{inbox.BACKEND}/pending/ab12/approve"]


def test_a_truncated_approval_cannot_be_approved_inline_but_can_be_denied():
    sent = []
    item = {"payload": {"action_id": "ab12", "truncated": True}}
    assert "tinyui" in inbox.answer_approval(item, "yes", sent.append) and sent == []
    inbox.answer_approval(item, "no", sent.append)
    assert sent == [f"{inbox.BACKEND}/pending/ab12/deny"]


def test_answering_twice_reports_already_answered():
    import urllib.error

    def conflict(url):
        raise urllib.error.HTTPError(url, 409, "conflict", {}, None)

    item = {"payload": {"proposal_id": "P-1"}}
    assert inbox.answer_approval(item, "yes", conflict) == "That was already answered."
