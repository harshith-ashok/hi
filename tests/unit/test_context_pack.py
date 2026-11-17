from datetime import datetime

import pytest

from hi.automation import context_pack
from hi.capture.schema import Task
from hi.capture.store import save
from hi.memory import reports

NOW = datetime(2026, 11, 17, 9, 0)


@pytest.fixture
def vault(tmp_vault, monkeypatch):
    save(Task(text="Send the Acme proposal", due="2026-11-17"))
    save(Task(text="Renew passport", due="2026-12-30"))  # not soon: left out
    save(Task(text="File last week's expenses", due="2026-11-10"))  # overdue
    reports.write_report("heartbeat", "Prepared the PR 41 summary", "x", now=NOW)
    monkeypatch.setattr(context_pack.registry, "is_local", lambda tier: True)
    return tmp_vault


def test_the_vault_part_lists_what_is_due_and_what_was_already_prepared(vault):
    pack = context_pack.build({"vault"}, "", "sonnet", NOW)
    assert "Tuesday 17 November 2026, 09:00" in pack.text
    assert "Send the Acme proposal" in pack.text and "OVERDUE 2026-11-10: File last week's expenses" in pack.text
    assert "Renew passport" not in pack.text
    assert "do not prepare these again" in pack.text and "Prepared the PR 41 summary" in pack.text
    assert pack.sources == ["vault"] and not pack.screen_included


def test_nothing_is_added_when_no_part_is_requested(vault):
    assert "Tuesday" in context_pack.build(set(), "", "sonnet", NOW).text


def test_the_screen_goes_in_only_for_a_local_model(vault, monkeypatch):
    from hi.context import now as live

    monkeypatch.setattr(live, "describe", lambda include_screen=True: "Frontmost: iTerm — KeyError: 'tier'")
    monkeypatch.setattr(live, "recent_activity", lambda minutes=30: "- iTerm, 22 min")
    pack = context_pack.build({"vault", "screen"}, "", "sonnet", NOW)
    assert pack.screen_included and "KeyError: 'tier'" in pack.text and "22 min" in pack.text

    monkeypatch.setattr(context_pack.registry, "is_local", lambda tier: False)
    hosted = context_pack.build({"vault", "screen"}, "", "sonnet", NOW)
    assert not hosted.screen_included and "KeyError" not in hosted.text
    assert "not a local model" in hosted.notes[0]


def test_a_paused_screen_is_left_out_with_a_note(vault, monkeypatch):
    from hi.context import now as live

    monkeypatch.setattr(live, "describe", lambda include_screen=True: "Screen context is paused or hidden right now (private app)")
    pack = context_pack.build({"screen"}, "", "sonnet", NOW)
    assert not pack.screen_included and "paused" in pack.notes[0]


def test_secrets_in_the_context_are_masked(vault, monkeypatch):
    save(Task(text="Rotate ghp_abcdefghijklmnopqrstuvwxyz0123456789 today", due="2026-11-17"))
    assert "ghp_" not in context_pack.build({"vault"}, "", "sonnet", NOW).text


def test_a_long_section_is_clipped(vault, monkeypatch):
    monkeypatch.setattr(context_pack, "_due_tasks", lambda now: "x" * 10000)
    assert len(context_pack.build({"vault"}, "", "sonnet", NOW).text) < 4000
