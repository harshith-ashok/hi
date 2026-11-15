"""Settings changed at runtime (POST /config) must reach modules that read them (MAKE.md, P4)."""

import hi.config as config
from hi.suggest import engine


def test_suggestion_flags_are_read_live_not_copied_at_import(monkeypatch):
    assert not hasattr(engine, "DIFF_WATCH_ENABLED")
    assert not hasattr(engine, "SMART_SUGGESTIONS_ENABLED")

    def must_not_be_reached():
        raise AssertionError("the model-judgment pass ran while the flag was off")

    monkeypatch.setattr(engine, "list_items", must_not_be_reached)
    monkeypatch.setattr(config, "SMART_SUGGESTIONS_ENABLED", False)
    assert engine._smart_suggestions([]) == []
