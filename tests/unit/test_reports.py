from datetime import datetime

from hi.memory import reports

NOW = datetime(2026, 11, 17, 8, 0)


def test_a_report_is_written_and_read_back(tmp_vault):
    rid, path = reports.write_report("schedule", "3 things today", "## Tasks\n- one", links=["[[a note]]"], now=NOW)
    assert path.parent == tmp_vault / "hi" / "reports" / "2026-11-17" and rid.startswith("20261117-0800-3-things-today")
    got = reports.read_report(rid)
    assert got["headline"] == "3 things today" and got["origin"] == "schedule"
    assert "- one" in got["body"] and "[[a note]]" in got["body"]


def test_reports_are_listed_newest_first(tmp_vault):
    reports.write_report("heartbeat", "older", "x", now=datetime(2026, 11, 16, 9, 0))
    reports.write_report("heartbeat", "newer", "y", now=datetime(2026, 11, 17, 9, 0))
    assert [r["headline"] for r in reports.list_reports()] == ["newer", "older"]
    assert reports.recent_headlines(1) == ["newer"]


def test_two_reports_with_the_same_headline_do_not_overwrite(tmp_vault):
    a, _ = reports.write_report("heartbeat", "same", "first", now=NOW)
    b, _ = reports.write_report("heartbeat", "same", "second", now=NOW)
    assert a != b and "first" in reports.read_report(a)["body"] and "second" in reports.read_report(b)["body"]


def test_secrets_never_reach_a_report(tmp_vault):
    rid, _ = reports.write_report("heartbeat", "deploy", "token is ghp_abcdefghijklmnopqrstuvwxyz0123456789 ok", now=NOW)
    assert "ghp_" not in reports.read_report(rid)["body"]


def test_a_bad_id_cannot_escape_the_reports_folder(tmp_vault):
    assert reports.read_report("../../etc/passwd") is None
    assert reports.read_report("20261117-0800-x/../../../secret") is None


def test_a_headline_that_looks_like_a_list_still_reads_back(tmp_vault):
    rid, _ = reports.write_report("heartbeat", "[urgent] build broke", "x", now=NOW)
    assert reports.read_report(rid)["headline"] == "(urgent] build broke"
