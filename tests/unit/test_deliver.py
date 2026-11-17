import pytest

from hi.automation import deliver as d
from hi.automation.deliver import Delivery, clean_headline, deliver, headline_from
from hi.core import health
from hi.memory import proposals, reports


@pytest.fixture(autouse=True)
def _fresh_health():
    health.reset()


class Poster:
    def __init__(self, status="shown"):
        self.calls, self.status = [], status

    def __call__(self, message, kind, priority, key, payload):
        self.calls.append({"message": message, "kind": kind, "priority": priority, "key": key, "payload": payload})
        return self.status


def test_clean_headline_strips_markdown_urls_and_paths_and_caps_words():
    text = "**Done**: see [the PR](https://github.com/x/y/pull/1) and /Users/me/notes/a.md `now`"
    assert clean_headline(text) == "Done: see the PR and now"
    long = " ".join(str(i) for i in range(40))
    out = clean_headline(long)
    assert len(out.split()) == 25 and out.endswith("…")


def test_headline_from_takes_the_first_heading_or_sentence():
    assert headline_from("# PR 41 has failing CI\n\nDetails here. More.") == "PR 41 has failing CI"
    assert headline_from("\n\nThree things today. Then more text.") == "Three things today."
    assert headline_from("```\ncode\n```\nreal line") == "real line"
    assert headline_from("") == ""


def test_a_body_becomes_a_report_and_the_headline_is_posted_with_a_link_to_it(tmp_vault):
    post = Poster()
    out = deliver(Delivery("3 things today", body="## Tasks\n- a", origin="schedule"), post=post)
    assert out.status == "shown" and out.report_id
    assert reports.read_report(out.report_id)["headline"] == "3 things today"
    assert post.calls[0]["payload"] == {"report_id": out.report_id}


def test_no_body_means_no_report(tmp_vault):
    out = deliver(Delivery("Reminder: stand-up", kind="reminder"), post=Poster())
    assert out.report_id == "" and reports.list_reports() == []


def test_secrets_are_redacted_from_the_headline_and_the_report(tmp_vault):
    post = Poster()
    out = deliver(Delivery("key ghp_abcdefghijklmnopqrstuvwxyz0123456789 leaked", body="ghp_abcdefghijklmnopqrstuvwxyz0123456789"), post=post)
    assert "ghp_" not in post.calls[0]["message"] and "ghp_" not in reports.read_report(out.report_id)["body"]


def test_one_proposal_becomes_an_approval_that_names_the_exact_action(tmp_vault):
    pid = proposals.create("heartbeat", "term", "send_email", {"to": "bob@acme.com", "body": "Hi Bob, following up"})
    post = Poster()
    out = deliver(Delivery("Prepared a follow-up", body="Draft ready.", origin="heartbeat", proposals=(pid,)), post=post)
    call = post.calls[0]
    assert call["kind"] == "approval" and call["priority"] == "urgent" and call["key"] == f"proposal:{pid}"
    assert "send_email" in call["message"] and "bob@acme.com" in call["message"]
    assert call["payload"]["proposal_id"] == pid
    body = reports.read_report(out.report_id)["body"]  # the full arguments are in the report
    assert "Hi Bob, following up" in body and "Actions waiting for your approval" in body


def test_several_proposals_are_counted_not_answerable_inline(tmp_vault):
    ids = tuple(proposals.create("heartbeat", "term", "t", {"i": i}) for i in range(2))
    post = Poster()
    deliver(Delivery("Prepared things", origin="heartbeat", proposals=ids), post=post)
    assert post.calls[0]["kind"] == "info" and "2 actions need your approval" in post.calls[0]["message"]
    assert "proposal_id" not in post.calls[0]["payload"]


def test_a_live_approval_that_is_too_long_is_flagged_so_it_cannot_be_approved_inline(tmp_vault):
    post = Poster()
    deliver(Delivery(" ".join(["word"] * 80), kind="approval", payload={"action_id": "ab"}), post=post)
    assert post.calls[0]["payload"]["truncated"] is True and post.calls[0]["payload"]["action_id"] == "ab"


def test_an_unreachable_mac_loses_the_popup_but_not_the_report(tmp_vault):
    out = deliver(Delivery("hello", body="body"), post=Poster("bridge-down"))
    assert out.status == "bridge-down" and reports.read_report(out.report_id)
    assert not health.snapshot()["host_bridge"]["ok"]


def test_a_failing_post_is_reported_not_raised(tmp_vault):
    def boom(*a):
        raise RuntimeError("island exploded")

    out = deliver(Delivery("hello", body="body"), post=boom)
    assert out.status == "error" and out.report_id


def test_a_closed_island_is_visible_in_health(tmp_vault):
    deliver(Delivery("hello"), post=Poster("notified"))
    assert not health.snapshot()["island"]["ok"]
