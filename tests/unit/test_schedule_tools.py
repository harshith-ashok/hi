import pytest

from hi.agents.term import schedule_tools as tools
from hi.memory import schedules


def call(tool, **args):
    return tool.invoke(args)


def test_scheduling_saves_a_note_and_says_the_next_three_times_in_words(tmp_vault):
    out = call(tools.schedule_task, task="Brief me for today", when="0 8 * * 1-5")
    assert out.startswith("Scheduled 'brief-me-for-today'. Next: ") and "08:00" in out and "Tell the user the first one" in out
    s = schedules.load("brief-me-for-today")
    assert s.when == "0 8 * * 1-5" and s.kind == "task" and s.context == ("vault",) and s.enabled


def test_an_unparseable_time_is_rejected_with_an_example_and_nothing_is_saved(tmp_vault):
    out = call(tools.schedule_task, task="x", when="every morning")
    assert out.startswith("Not scheduled:") and "0 8 * * 1-5" in out
    assert schedules.load_all() == []


def test_a_time_that_has_already_passed_says_it_will_never_run(tmp_vault):
    out = call(tools.schedule_task, task="old", when="once 2020-01-01T09:00")
    assert "never" in out


def test_bad_options_are_rejected(tmp_vault):
    assert "kind" in call(tools.schedule_task, task="x", when="0 8 * * *", kind="shout")
    assert "deliver" in call(tools.schedule_task, task="x", when="0 8 * * *", deliver="loudly")
    assert "unknown context" in call(tools.schedule_task, task="x", when="0 8 * * *", context="vault,camera")
    assert schedules.load_all() == []


def test_giving_a_task_a_risky_tool_needs_the_users_confirmation_now(tmp_vault, monkeypatch):
    asked = []
    monkeypatch.setattr(tools, "confirm_destructive", lambda d: asked.append(d) or False)
    out = call(tools.schedule_task, task="file things", when="0 9 * * *", allow="create_note")
    assert "declined" in out and "create_note" in asked[0] and schedules.load_all() == []
    monkeypatch.setattr(tools, "confirm_destructive", lambda d: True)
    call(tools.schedule_task, task="file things", when="0 9 * * *", allow="create_note")
    assert schedules.load("file-things").allow == ("create_note",)


def test_read_only_tools_need_no_confirmation(tmp_vault, monkeypatch):
    monkeypatch.setattr(tools, "confirm_destructive", lambda d: pytest.fail("asked"))
    call(tools.schedule_task, task="look", when="0 9 * * *", allow="read_note, web_search")


def test_two_schedules_with_the_same_words_get_different_ids(tmp_vault):
    call(tools.schedule_task, task="Weekly review", when="0 18 * * 0")
    call(tools.schedule_task, task="Weekly review", when="0 19 * * 0")
    assert sorted(s.id for s in schedules.load_all()) == ["weekly-review", "weekly-review-2"]


def test_list_pause_resume_and_delete(tmp_vault, monkeypatch):
    call(tools.schedule_task, task="Standup", when="55 9 * * 1-5", kind="reminder")
    assert "standup [on] 55 9 * * 1-5" in call(tools.list_schedules)
    assert call(tools.pause_schedule, schedule_id="standup") == "Paused 'standup'."
    assert "[paused]" in call(tools.list_schedules)
    assert call(tools.pause_schedule, schedule_id="standup", paused=False) == "Resumed 'standup'."
    assert "No schedule" in call(tools.pause_schedule, schedule_id="nope")
    monkeypatch.setattr(tools, "confirm_destructive", lambda d: False)
    assert call(tools.delete_schedule, schedule_id="standup") == "Not deleted." and schedules.load("standup")
    monkeypatch.setattr(tools, "confirm_destructive", lambda d: True)
    assert call(tools.delete_schedule, schedule_id="standup") == "Deleted 'standup'." and schedules.load("standup") is None


def test_the_list_shows_notes_that_do_not_parse(tmp_vault):
    (tmp_vault / "hi" / "schedules").mkdir(parents=True)
    (tmp_vault / "hi" / "schedules" / "bad.md").write_text("---\nwhen: soon\n---\n\nx\n")
    assert "! bad.md" in call(tools.list_schedules)


def test_run_now_without_a_started_runner_says_so(tmp_vault, monkeypatch):
    from hi.automation import scheduler

    monkeypatch.setattr(scheduler, "_run_turn", None)
    call(tools.schedule_task, task="Brief", when="0 8 * * *")
    assert "not started" in call(tools.run_schedule_now, schedule_id="brief")


def test_the_tools_are_offered_to_term_and_butler_and_hidden_nowhere():
    from hi import toolkit
    from hi.agents.butler import butler
    from hi.agents.term import term

    names = {t.name for t in tools.SCHEDULE_TOOLS}
    assert names <= {t.name for t in term.TOOLS} and names <= {t.name for t in butler.TOOLS}
    group = next(g for g in toolkit.GROUPS if g.name == "schedule")
    assert set(group.tools) == names and group.name in term.TERM_GROUPS
