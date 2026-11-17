import json

import pytest
from starlette.testclient import TestClient

from hi import toolkit, ui_spec
from hi.server.app import create_app
from hi.ui_spec import UiError, normalize, show_ui

DEPLOY = {"title": "Deploy", "type": "form", "action": "deploy", "submit": "Deploy now", "children": [
    {"type": "radio", "name": "env", "label": "Environment", "options": ["staging", {"value": "prod", "label": "Production", "description": "live"}], "required": True, "default": "staging"},
    {"type": "checkboxes", "name": "notify", "label": "Tell", "options": ["Team", "Customers"], "default": ["Team", "Nobody"]},
    {"type": "switch", "name": "dry", "label": "Dry run", "default": True},
    {"type": "slider", "name": "pct", "label": "Rollout", "min": 0, "max": 100, "step": 10, "default": 50},
]}


def problems(spec):
    with pytest.raises(UiError) as e:
        normalize(spec)
    return e.value.problems


def test_a_form_is_normalised_with_defaults_checked_against_the_options():
    out = normalize(DEPLOY)
    assert out["interactive"] and out["title"] == "Deploy"
    form = out["ui"]
    radio, boxes, switch, slider = form["children"]
    assert radio["options"][1] == {"value": "prod", "label": "Production", "description": "live"} and radio["default"] == "staging" and radio["required"]
    assert boxes["default"] == ["Team"]  # "Nobody" is not an option
    assert switch["default"] is True and slider["step"] == 10 and slider["default"] == 50
    assert form["submit"] == "Deploy now" and form["action"] == "deploy"


def test_a_list_of_components_becomes_a_stack_and_json_text_is_accepted():
    out = normalize([{"type": "heading", "text": "Hi"}, {"type": "text", "text": "There"}])
    assert out["ui"]["type"] == "stack" and len(out["ui"]["children"]) == 2 and not out["interactive"]
    assert normalize(json.dumps({"type": "badge", "text": "ok", "tone": "success"}))["ui"]["tone"] == "success"


def test_display_components_are_cleaned():
    out = normalize({"type": "stack", "children": [
        {"type": "table", "columns": ["a", "b"], "rows": [["1", "2", "extra"], ["3"]]},
        {"type": "stat", "label": "Users", "value": 1200, "delta": "+4%"},
        {"type": "chart", "kind": "bar", "data": [{"label": "Mon", "value": 3}, {"label": "Tue", "value": 5}]},
        {"type": "steps", "items": [{"title": "Build", "state": "done"}, "Test"]},
        {"type": "progress", "value": 150},
        {"type": "image", "src": "/plots/a.png", "alt": "x"},
        {"type": "mermaid", "code": "flowchart TD\n A-->B"},
        {"type": "scene3d", "scene": {"objects": [{"type": "box"}]}},
    ]})
    table, stat, chart, steps, progress, image, mermaid, scene = out["ui"]["children"]
    assert table["rows"] == [["1", "2"], ["3"]] and stat["value"] == "1200"
    assert [p["value"] for p in chart["data"]] == [3.0, 5.0] and steps["items"][1] == {"title": "Test", "state": "pending"}
    assert progress["value"] == 100 and image["src"] == "/plots/a.png" and mermaid["code"].startswith("flowchart")
    assert scene["scene"]["objects"][0]["type"] == "box"


def test_every_problem_is_listed():
    found = problems({"type": "stack", "children": [
        {"type": "carousel"}, {"type": "radio", "label": "x", "options": ["a"]}, {"type": "select", "name": "s", "options": []},
        {"type": "image", "src": "javascript:alert(1)"}, {"type": "mermaid", "code": "not a diagram"}, "x",
    ]})
    text = " ".join(found)
    assert len(found) == 6 and "carousel" in text and "needs a name" in text and "options" in text and "http(s)" in text and "Mermaid" in text


@pytest.mark.parametrize("bad", [
    {}, [], 5, "nope", {"type": "stack", "children": "x"}, {"type": "text", "text": ["a"]}, {"type": "chart", "kind": "radar", "data": [{"label": "a", "value": 1}]},
    {"type": "chart", "data": []}, {"type": "table", "columns": [], "rows": []}, {"type": "alert", "tone": "purple"},
    {"type": "button", "label": "x", "action": "<script>"}, {"type": "wizard", "steps": []}, {"type": "tabs", "tabs": []},
    {"type": "slider", "name": "s", "min": 5, "max": 1},
])
def test_malformed_specs_are_refused(bad):
    assert problems(bad)


def test_text_is_display_and_input_is_the_one_line_field():
    assert not normalize({"type": "text", "text": "hello **there**"})["interactive"]
    field = normalize({"type": "input", "name": "who", "label": "Name", "placeholder": "Ada"})
    assert field["interactive"] and field["ui"]["placeholder"] == "Ada"


def test_input_names_must_be_unique_and_safe():
    two = {"type": "stack", "children": [{"type": "input", "name": "a"}, {"type": "input", "name": "a"}]}
    assert "used twice" in " ".join(problems(two))
    for name in ("", "1abc", "has space", "x" * 50, "__proto__ x"):
        assert problems({"type": "input", "name": name})


def test_limits_on_size_depth_and_text():
    assert "components" in " ".join(problems({"type": "stack", "children": [{"type": "divider"}] * (ui_spec.MAX_NODES + 1)}))
    deep = {"type": "divider"}
    for _ in range(ui_spec.MAX_DEPTH + 2):
        deep = {"type": "stack", "children": [deep]}
    assert "nested" in " ".join(problems(deep))
    long = normalize({"type": "text", "text": "x" * 20_000})
    assert len(long["ui"]["text"]) == ui_spec.MAX_TEXT


def test_unknown_props_never_reach_the_chat():
    out = normalize({"type": "button", "label": "Go", "onclick": "alert(1)", "html": "<b>x</b>", "style": "x"})["ui"]
    assert set(out) == {"type", "label", "variant", "action"}


def test_images_may_only_come_from_http_or_our_own_paths():
    ok = ["https://example.com/a.png", "/plots/pic-1.png", "/files/run1/chart.svg"]
    for src in ok:
        assert normalize({"type": "image", "src": src})["ui"]["src"] == src
    for src in ("javascript:alert(1)", "data:text/html,<script>", "file:///etc/passwd", "//evil.test/x.png", "/etc/passwd", "/plots/../x.png"):
        assert problems({"type": "image", "src": src})


def test_dialog_confirm_and_wizard_carry_their_actions():
    out = normalize({"type": "stack", "children": [
        {"type": "dialog", "trigger": "Review", "title": "Changes", "children": [{"type": "text", "text": "x"}], "actions": [{"label": "Ship it", "action": "ship", "variant": "default"}, {"label": "Cancel"}]},
        {"type": "confirm", "trigger": "Delete", "title": "Sure?", "confirm": "Delete", "destructive": True, "action": "delete"},
        {"type": "wizard", "action": "setup", "steps": [{"title": "One", "children": [{"type": "input", "name": "a"}]}, {"title": "Two", "children": []}]},
    ]})
    dialog, confirm, wizard = out["ui"]["children"]
    assert dialog["actions"][0] == {"label": "Ship it", "variant": "default", "action": "ship"} and "action" not in dialog["actions"][1]
    assert confirm["destructive"] is True and confirm["action"] == "delete" and len(wizard["steps"]) == 2 and out["interactive"]


# --- the tool ------------------------------------------------------------------------------------------------------

def test_an_interactive_ui_tells_the_model_to_wait(tmp_vault):
    out = show_ui.invoke({"ui": DEPLOY})
    assert "End your turn now" in out and "/ui/deploy-" in out
    path = out.split(": ")[1].split(".json")[0] + ".json"
    assert json.loads((tmp_vault / "hi" / "ui" / path.split("/")[-1]).read_text())["ui"]["type"] == "form"


def test_a_display_only_ui_lets_the_model_carry_on(tmp_vault):
    out = show_ui.invoke({"ui": {"type": "stat", "label": "Users", "value": 5}, "title": "Numbers"})
    assert "End your turn" not in out and "already displayed" in out and "/ui/numbers-" in out


def test_a_bad_ui_says_what_to_fix_and_saves_nothing(tmp_vault):
    out = show_ui.invoke({"ui": {"type": "carousel"}})
    assert out.startswith("Not shown") and "carousel" in out and not (tmp_vault / "hi" / "ui").exists()


def test_a_ui_is_served_only_by_a_safe_name(tmp_vault):
    client = TestClient(create_app())
    path = show_ui.invoke({"ui": {"type": "badge", "text": "x"}}).split(": ")[1].split(".json")[0] + ".json"
    r = client.get(path)
    assert r.status_code == 200 and r.json()["ui"]["type"] == "badge" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/ui/nope.json").status_code == 404 and client.get("/ui/..%2Fsecret.json").status_code == 404 and client.get("/ui/x.html").status_code == 404


def test_a_background_run_may_not_show_ui(tmp_vault):
    from fakes import Scripted, tool_call
    from langchain_core.messages import AIMessage, HumanMessage

    from hi.agents.base import make_agent
    from hi.core.runpolicy import UNATTENDED, run_scope
    from hi.memory import proposals

    agent = make_agent(Scripted(messages=iter([tool_call("show_ui", {"ui": {"type": "badge", "text": "x"}}), AIMessage("assumed")])), [show_ui])
    with run_scope(UNATTENDED, "heartbeat"):
        result = agent.invoke({"messages": [HumanMessage("go")]})
    assert "nobody is here" in next(m for m in result["messages"] if m.type == "tool").content
    assert proposals.pending() == [] and not (tmp_vault / "hi" / "ui").exists()


def test_both_chat_agents_offer_it_always():
    from hi.agents.butler import butler
    from hi.agents.term import term

    assert "show_ui" in {t.name for t in term.TOOLS} and "show_ui" in {t.name for t in butler.TOOLS}
    group = next(g for g in toolkit.GROUPS if g.name == "show_ui")
    assert group.priority == 1 and "show_ui" in term.TERM_GROUPS
