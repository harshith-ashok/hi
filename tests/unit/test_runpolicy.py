import threading

from hi.core import runpolicy
from hi.core.runpolicy import INTERACTIVE, UNATTENDED, run_scope


def test_no_scope_means_interactive():
    assert runpolicy.current() is None and not runpolicy.is_unattended()


def test_a_scope_is_current_inside_and_gone_after():
    with run_scope(UNATTENDED, "schedule") as state:
        assert runpolicy.current() is state and runpolicy.is_unattended() and state.origin == "schedule"
    assert runpolicy.current() is None


def test_an_interactive_policy_is_not_unattended():
    with run_scope(INTERACTIVE, "ui"):
        assert not runpolicy.is_unattended()


def test_with_allowed_adds_to_the_policy_without_changing_the_preset():
    wider = UNATTENDED.with_allowed(["create_note"])
    assert "create_note" in wider.allowed and "write_report" in wider.allowed
    assert "create_note" not in UNATTENDED.allowed


def test_another_thread_does_not_see_this_threads_scope():
    seen = []
    with run_scope(UNATTENDED):
        t = threading.Thread(target=lambda: seen.append(runpolicy.is_unattended()))
        t.start()
        t.join()
    assert seen == [False]


def test_confirm_destructive_denies_when_unattended_and_allows_when_pre_approved(monkeypatch):
    from hi import action_tiers

    monkeypatch.setattr(action_tiers, "_confirm_handler", lambda description: (_ for _ in ()).throw(AssertionError("asked")))
    with run_scope(UNATTENDED):
        assert action_tiers.confirm_destructive("delete a note") is False
    with runpolicy.pre_approved():
        assert action_tiers.confirm_destructive("delete a note") is True
