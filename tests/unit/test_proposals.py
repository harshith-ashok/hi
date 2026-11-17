import json

from hi.memory import proposals


def make(tool="send_email", **args):
    return proposals.create("heartbeat", "term", tool, args or {"to": "bob@acme.com"}, "follow up")


def test_a_new_proposal_is_pending_with_its_arguments(tmp_vault):
    pid = make()
    assert pid.startswith("P-")
    (p,) = proposals.pending()
    assert p["id"] == pid and p["tool"] == "send_email" and p["args"] == {"to": "bob@acme.com"} and p["status"] == "created"


def test_begin_execution_claims_a_proposal_exactly_once(tmp_vault):
    pid = make()
    assert proposals.begin_execution(pid)["id"] == pid
    assert proposals.begin_execution(pid) is None  # a second approval does not run it again
    assert proposals.get(pid)["status"] == "executing"
    assert proposals.pending() == []


def test_deny_works_once_and_blocks_execution(tmp_vault):
    pid = make()
    assert proposals.deny(pid) is True
    assert proposals.deny(pid) is False
    assert proposals.begin_execution(pid) is None and proposals.get(pid)["status"] == "denied"


def test_mark_records_the_outcome(tmp_vault):
    pid = make()
    proposals.begin_execution(pid)
    proposals.mark(pid, proposals.EXECUTED, "sent")
    assert proposals.get(pid)["status"] == "executed" and proposals.get(pid)["result"] == "sent"


def test_a_restart_fails_a_proposal_stuck_executing_and_never_reruns_it(tmp_vault):
    pid = make()
    proposals.begin_execution(pid)
    assert proposals.recover_interrupted() == 1
    p = proposals.get(pid)
    assert p["status"] == "failed" and "interrupted" in p["result"]
    assert proposals.begin_execution(pid) is None


def test_old_proposals_expire(tmp_vault):
    pid = make()
    created = proposals.get(pid)["created_at"]
    assert proposals.expire_old(ttl_days=7, now=created + 6 * 86400) == 0
    assert proposals.expire_old(ttl_days=7, now=created + 8 * 86400) == 1
    assert proposals.get(pid)["status"] == "expired" and proposals.pending() == []


def test_a_torn_line_does_not_hide_the_rest(tmp_vault):
    pid = make()
    with proposals.path().open("a") as f:
        f.write('{"event": "appr')  # a crash mid-write
    assert proposals.get(pid)["status"] == "created"


def test_describe_says_exactly_what_would_run(tmp_vault):
    pid = make("send_email", to="bob@acme.com", subject="Follow-up", body="x" * 500)
    text = proposals.describe(proposals.get(pid))
    assert text.startswith("send_email(to='bob@acme.com'") and len(text) <= 140
