from hi.server import suggest


def test_clean_completion_keeps_only_the_continuation():
    assert suggest.clean_completion("what changed in the", "what changed in the hi repo") == " hi repo"
    assert suggest.clean_completion("what changed in the ", "hi repo") == "hi repo"
    assert suggest.clean_completion("plot a graph", ", then save it") == ", then save it"
    assert suggest.clean_completion("plot a", '"graph"\nmore lines') == " graph"
    assert suggest.clean_completion("plot a", "   ") == ""


def test_too_short_multiline_and_slash_get_no_model_call(monkeypatch):
    def boom(_tier):
        raise AssertionError("model must not be called")
    monkeypatch.setattr(suggest, "get_tier_model_fast", boom)
    assert suggest.suggest("hi", []) == ""
    assert suggest.suggest("two\nlines here", []) == ""
    assert suggest.suggest("/pdf merge these", []) == ""


def test_model_failure_gives_no_suggestion(monkeypatch):
    class Down:
        def invoke(self, _m):
            raise RuntimeError("ollama is down")
    monkeypatch.setattr(suggest, "get_tier_model_fast", lambda _t: Down())
    assert suggest.suggest("what did I note about", ["a"]) == ""


def test_suggestion_from_model(monkeypatch):
    class Fake:
        def invoke(self, _m):
            return type("R", (), {"content": "binary search trees?"})()
    monkeypatch.setattr(suggest, "get_tier_model_fast", lambda _t: Fake())
    assert suggest.suggest("what did I note about ", []) == "binary search trees?"
