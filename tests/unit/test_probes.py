from hi import probes
from hi.core import health


def test_run_reports_each_dependency_and_essentials_decide_ok():
    health.reset()

    def down():
        raise OSError("refused")

    report = probes.run({"ollama": lambda: None, "vault": lambda: None, "sandbox": down})
    assert report["ok"] is True  # sandbox is optional
    assert report["deps"]["sandbox"]["ok"] is False and "refused" in report["deps"]["sandbox"]["error"]

    report = probes.run({"ollama": down, "vault": lambda: None})
    assert report["ok"] is False
    health.reset()


def test_vault_probe_checks_it_is_writable(tmp_vault):
    probes._vault()
    assert list(tmp_vault.iterdir()) == []  # leaves nothing behind


def test_a_hanging_probe_is_marked_down_instead_of_blocking(monkeypatch):
    import threading
    import time

    health.reset()
    monkeypatch.setattr(probes, "DEADLINE_S", 0.2)
    release = threading.Event()
    started = time.monotonic()
    report = probes.run({"ollama": lambda: None, "vault": lambda: None, "host_bridge": release.wait})
    release.set()
    assert time.monotonic() - started < 2
    assert report["deps"]["host_bridge"]["ok"] is False
    assert "no answer" in report["deps"]["host_bridge"]["error"]
    assert report["ok"] is True
    health.reset()
