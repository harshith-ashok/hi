"""Interactive UI the assistant can show in the chat: forms, choices, confirmations, wizards, tables, stats, charts.

`show_ui` takes a component tree as JSON, checks it against the whitelist below (a type it does not know, a value out of
range, too many nodes: refused, with every problem listed so the model can fix it), saves it under <vault>/hi/ui/ and
returns /ui/<name>.json, which the chat draws with its own components. A spec is data, never HTML or code: the chat builds
only these components, so nothing here can inject markup or run a script.

When the user presses a button or submits, the chat sends their choices back as their next message, so the conversation
carries on from what they picked. Components that collect input have a `name`; a button, form, dialog, confirm or wizard
action carries every named value of the spec.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

import hi.config as config
from hi import scene3d, visuals

URL_PREFIX = "/ui/"
WAIT_MARKER = "End your turn now"  # in a tool result that is waiting for the user; hi/server/turn.py ends the turn there
MAX_NODES = 300
MAX_DEPTH = 8
MAX_TEXT = 4000
MAX_OPTIONS = 60
MAX_ROWS, MAX_COLUMNS, MAX_POINTS = 200, 20, 200
MAX_BYTES = 300_000
MAX_ERRORS = 10

LAYOUT = {"stack", "row", "grid", "card", "tabs", "accordion", "divider"}
DISPLAY = {"heading", "text", "badge", "alert", "list", "table", "stat", "progress", "code", "image", "chart", "mermaid", "scene3d", "timeline", "steps"}
INPUT = {"input", "number", "textarea", "select", "radio", "checkbox", "checkboxes", "switch", "slider", "date", "rating"}
ACTION = {"button", "form", "dialog", "confirm", "wizard"}
TYPES = LAYOUT | DISPLAY | INPUT | ACTION
TONES = ("neutral", "info", "success", "warning", "danger")
VARIANTS = ("default", "secondary", "outline", "destructive", "ghost")
CHARTS = ("bar", "line", "area", "pie")
_NAME = re.compile(r"[A-Za-z][\w-]{0,40}")
_ACTION = re.compile(r"[A-Za-z][\w .:-]{0,60}")
_IMAGE_OK = re.compile(r"(https?://[^\s\"'<>]+|/plots/[\w-]+\.(png|jpg|jpeg|webp|svg)|/files/[\w.-]+/[\w.-]+)", re.IGNORECASE)


class UiError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems[:MAX_ERRORS]
        super().__init__("; ".join(self.problems))


class _Ctx:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.nodes = 0
        self.names: set[str] = set()
        self.interactive = False

    def bad(self, where: str, why: str) -> None:
        if len(self.problems) < MAX_ERRORS:
            self.problems.append(f"{where}: {why}")

    def text(self, v: Any, where: str, default: str = "", limit: int = MAX_TEXT) -> str:
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            self.bad(where, f"expected text, got {type(v).__name__}")
            return default
        return str(v)[:limit]

    def num(self, v: Any, where: str, low: float, high: float, default: float | None = None) -> float | None:
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
            self.bad(where, f"expected a number, got {v!r}")
            return default
        return float(min(max(v, low), high))

    def choice(self, v: Any, where: str, allowed: tuple[str, ...], default: str) -> str:
        if v is None:
            return default
        if v not in allowed:
            self.bad(where, f"must be one of {', '.join(allowed)}")
            return default
        return v

    def options(self, v: Any, where: str) -> list[dict]:
        if not isinstance(v, list) or not v:
            self.bad(where, "expected a non-empty list of options")
            return []
        out = []
        for i, o in enumerate(v[:MAX_OPTIONS]):
            if isinstance(o, dict):
                value = self.text(o.get("value", o.get("label")), f"{where}[{i}].value", limit=200)
                item = {"value": value, "label": self.text(o.get("label", value), f"{where}[{i}].label", limit=200)}
                if o.get("description"):
                    item["description"] = self.text(o["description"], f"{where}[{i}].description", limit=300)
                if o.get("disabled"):
                    item["disabled"] = True
            else:
                text = self.text(o, f"{where}[{i}]", limit=200)
                item = {"value": text, "label": text}
            out.append(item)
        if len(v) > MAX_OPTIONS:
            self.bad(where, f"more than {MAX_OPTIONS} options")
        return out


def _children(raw: Any, ctx: _Ctx, where: str, depth: int) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        ctx.bad(where, "expected a list of components")
        return []
    return [n for i, c in enumerate(raw) if (n := _node(c, ctx, f"{where}[{i}]", depth + 1))]


def _node(raw: Any, ctx: _Ctx, where: str, depth: int) -> dict | None:
    ctx.nodes += 1
    if ctx.nodes > MAX_NODES:
        ctx.bad("ui", f"more than {MAX_NODES} components")
        return None
    if depth > MAX_DEPTH:
        ctx.bad(where, f"nested more than {MAX_DEPTH} deep")
        return None
    if not isinstance(raw, dict):
        ctx.bad(where, "each component must be an object with a \"type\"")
        return None
    kind = raw.get("type")
    if kind not in TYPES:
        ctx.bad(f"{where}.type", f"unknown component {kind!r}; use one of: {', '.join(sorted(TYPES))}")
        return None
    out: dict[str, Any] = {"type": kind}
    t = lambda key, default="", limit=MAX_TEXT: ctx.text(raw.get(key), f"{where}.{key}", default, limit)  # noqa: E731

    if kind in INPUT:
        ctx.interactive = True
        name = raw.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            ctx.bad(f"{where}.name", "an input needs a name: letters, digits, - and _, starting with a letter")
        elif name in ctx.names:
            ctx.bad(f"{where}.name", f"{name!r} is used twice")
        else:
            ctx.names.add(name)
            out["name"] = name
        out["label"] = t("label", limit=200)
        if raw.get("description"):
            out["description"] = t("description", limit=300)
        if raw.get("required"):
            out["required"] = True
        if kind in ("select", "radio", "checkboxes"):
            out["options"] = ctx.options(raw.get("options"), f"{where}.options")
            values = {o["value"] for o in out["options"]}
            if kind == "checkboxes":
                chosen = raw.get("default") if isinstance(raw.get("default"), list) else []
                out["default"] = [c for c in chosen if isinstance(c, str) and c in values]
            elif isinstance(raw.get("default"), str) and raw["default"] in values:
                out["default"] = raw["default"]
        elif kind in ("checkbox", "switch"):
            out["default"] = bool(raw.get("default"))
        elif kind in ("number", "slider", "rating"):
            low, high = {"rating": (1, 10), "number": (-1e12, 1e12), "slider": (-1e12, 1e12)}[kind]
            out["min"] = ctx.num(raw.get("min"), f"{where}.min", low, high, 1 if kind == "rating" else 0)
            out["max"] = ctx.num(raw.get("max"), f"{where}.max", low, high, {"rating": 5, "slider": 100}.get(kind, 1e12))
            if out["max"] < out["min"]:
                ctx.bad(f"{where}.max", "must not be below min")
            out["step"] = ctx.num(raw.get("step"), f"{where}.step", 1e-9, 1e12, 1)
            if raw.get("default") is not None:
                out["default"] = ctx.num(raw.get("default"), f"{where}.default", out["min"], out["max"], out["min"])
        else:  # input, textarea, date
            out["default"] = t("default", limit=2000)
            out["placeholder"] = t("placeholder", limit=200)
        return out

    if kind == "heading":
        out["text"] = t("text", limit=300)
        out["level"] = int(ctx.num(raw.get("level"), f"{where}.level", 1, 4, 2) or 2)
    elif kind == "text":
        out["text"] = t("text")
    elif kind == "badge":
        out["text"] = t("text", limit=100)
        out["tone"] = ctx.choice(raw.get("tone"), f"{where}.tone", TONES, "neutral")
    elif kind == "alert":
        out["title"], out["text"] = t("title", limit=200), t("text")
        out["tone"] = ctx.choice(raw.get("tone"), f"{where}.tone", TONES, "info")
    elif kind == "divider":
        pass
    elif kind == "list":
        items = raw.get("items")
        if not isinstance(items, list):
            ctx.bad(f"{where}.items", "expected a list of strings")
            items = []
        out["items"] = [ctx.text(x, f"{where}.items[{i}]", limit=500) for i, x in enumerate(items[:MAX_ROWS])]
        out["ordered"] = bool(raw.get("ordered"))
    elif kind == "table":
        cols, rows = raw.get("columns"), raw.get("rows")
        if not isinstance(cols, list) or not cols or len(cols) > MAX_COLUMNS:
            ctx.bad(f"{where}.columns", f"expected 1 to {MAX_COLUMNS} column names")
            cols = []
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            ctx.bad(f"{where}.rows", f"expected a list of at most {MAX_ROWS} rows")
            rows = []
        out["columns"] = [ctx.text(c, f"{where}.columns", limit=100) for c in cols]
        out["rows"] = [[ctx.text(c, f"{where}.rows[{i}]", limit=300) for c in (r if isinstance(r, list) else [])][:len(cols)] for i, r in enumerate(rows)]
        if raw.get("caption"):
            out["caption"] = t("caption", limit=200)
    elif kind == "stat":
        out["label"], out["value"] = t("label", limit=100), t("value", limit=100)
        if raw.get("delta"):
            out["delta"] = t("delta", limit=60)
        out["tone"] = ctx.choice(raw.get("tone"), f"{where}.tone", TONES, "neutral")
    elif kind == "progress":
        out["value"] = ctx.num(raw.get("value"), f"{where}.value", 0, 100, 0)
        out["label"] = t("label", limit=200)
    elif kind == "code":
        out["text"], out["lang"] = t("text", limit=20_000), t("lang", limit=20)
    elif kind == "image":
        src = t("src", limit=1000)
        if not _IMAGE_OK.fullmatch(src):
            ctx.bad(f"{where}.src", "must be an http(s) URL or a /plots/ or /files/ path")
            src = ""
        out["src"], out["alt"] = src, t("alt", limit=300)
    elif kind == "chart":
        out["kind"] = ctx.choice(raw.get("kind"), f"{where}.kind", CHARTS, "bar")
        data = raw.get("data")
        if not isinstance(data, list) or not data or len(data) > MAX_POINTS:
            ctx.bad(f"{where}.data", f"expected 1 to {MAX_POINTS} points like {{\"label\": \"Mon\", \"value\": 3}}")
            data = []
        out["data"] = [{"label": ctx.text(p.get("label") if isinstance(p, dict) else None, f"{where}.data[{i}].label", limit=60),
                        "value": ctx.num(p.get("value") if isinstance(p, dict) else None, f"{where}.data[{i}].value", -1e12, 1e12, 0)}
                       for i, p in enumerate(data)]
        out["title"] = t("title", limit=200)
    elif kind == "mermaid":
        code = visuals.clean_mermaid(t("code"))
        if code is None:
            ctx.bad(f"{where}.code", "expected Mermaid code starting with a diagram type like flowchart TD")
        out["code"] = code or ""
    elif kind == "scene3d":
        try:
            out["scene"] = scene3d.normalize(raw.get("scene"))
        except scene3d.SceneError as e:
            for problem in e.problems[:3]:
                ctx.bad(f"{where}.scene", problem)
    elif kind in ("timeline", "steps"):
        items = raw.get("items")
        if not isinstance(items, list) or not items:
            ctx.bad(f"{where}.items", "expected a non-empty list")
            items = []
        norm = []
        for i, it in enumerate(items[:MAX_ROWS]):
            it = it if isinstance(it, dict) else {"title": it}
            row = {"title": ctx.text(it.get("title", it.get("label")), f"{where}.items[{i}].title", limit=200)}
            for key in ("text", "time"):
                if it.get(key):
                    row[key] = ctx.text(it[key], f"{where}.items[{i}].{key}", limit=500)
            row["state"] = ctx.choice(it.get("state"), f"{where}.items[{i}].state", ("done", "active", "pending", "failed"), "pending")
            norm.append(row)
        out["items"] = norm
    elif kind in ("stack", "row", "grid", "card"):
        out["children"] = _children(raw.get("children"), ctx, f"{where}.children", depth)
        if kind == "grid":
            out["columns"] = int(ctx.num(raw.get("columns"), f"{where}.columns", 1, 4, 2) or 2)
        if kind == "card":
            out["title"], out["description"] = t("title", limit=200), t("description", limit=500)
    elif kind in ("tabs", "accordion"):
        key = "tabs" if kind == "tabs" else "items"
        sections = raw.get(key)
        if not isinstance(sections, list) or not sections:
            ctx.bad(f"{where}.{key}", "expected a non-empty list of {label, children}")
            sections = []
        out[key] = [{"label": ctx.text(sec.get("label") if isinstance(sec, dict) else None, f"{where}.{key}[{i}].label", limit=100),
                     "children": _children(sec.get("children") if isinstance(sec, dict) else None, ctx, f"{where}.{key}[{i}].children", depth)}
                    for i, sec in enumerate(sections[:20])]
    elif kind in ("button", "form", "dialog", "confirm", "wizard"):
        ctx.interactive = True
        action = raw.get("action", raw.get("label", "submit"))
        if not isinstance(action, str) or not _ACTION.fullmatch(action):
            ctx.bad(f"{where}.action", "a short name like approve or submit")
            action = "submit"
        if kind != "dialog":
            out["action"] = action
        if kind == "button":
            out["label"] = t("label", "OK", 100)
            out["variant"] = ctx.choice(raw.get("variant"), f"{where}.variant", VARIANTS, "default")
        elif kind == "form":
            out["children"] = _children(raw.get("children"), ctx, f"{where}.children", depth)
            out["submit"] = t("submit", "Submit", 100)
            if raw.get("title"):
                out["title"] = t("title", limit=200)
        elif kind == "dialog":
            out["trigger"], out["title"], out["description"] = t("trigger", "Open", 100), t("title", limit=200), t("description", limit=500)
            out["children"] = _children(raw.get("children"), ctx, f"{where}.children", depth)
            buttons = raw.get("actions") if isinstance(raw.get("actions"), list) else [{"label": "Close"}]
            out["actions"] = []
            for i, b in enumerate(buttons[:4]):
                b = b if isinstance(b, dict) else {}
                label = ctx.text(b.get("label"), f"{where}.actions[{i}].label", "OK", 100)
                act = b.get("action")
                out["actions"].append({"label": label, "variant": ctx.choice(b.get("variant"), f"{where}.actions[{i}].variant", VARIANTS, "default"),
                                       **({"action": act} if isinstance(act, str) and _ACTION.fullmatch(act) else {})})
        elif kind == "confirm":
            out["trigger"], out["title"], out["description"] = t("trigger", "Continue", 100), t("title", "Are you sure?", 200), t("description", limit=500)
            out["confirm"], out["cancel"] = t("confirm", "Confirm", 60), t("cancel", "Cancel", 60)
            out["destructive"] = bool(raw.get("destructive"))
        else:  # wizard
            steps = raw.get("steps")
            if not isinstance(steps, list) or not steps:
                ctx.bad(f"{where}.steps", "expected a non-empty list of {title, children}")
                steps = []
            out["steps"] = [{"title": ctx.text(s.get("title") if isinstance(s, dict) else None, f"{where}.steps[{i}].title", limit=100),
                             "description": ctx.text(s.get("description") if isinstance(s, dict) else None, f"{where}.steps[{i}].description", limit=300),
                             "children": _children(s.get("children") if isinstance(s, dict) else None, ctx, f"{where}.steps[{i}].children", depth)}
                            for i, s in enumerate(steps[:12])]
            out["submit"] = t("submit", "Finish", 100)
    return out


def normalize(spec: Any) -> dict:
    """The spec checked and cleaned: {"title", "ui", "interactive"}, or UiError listing every problem."""
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as e:
            raise UiError([f"ui: not valid JSON ({e.msg} at position {e.pos})"]) from None
    if isinstance(spec, list):
        if not spec:
            raise UiError(["ui: nothing to show: the list is empty"])
        spec = {"type": "stack", "children": spec}
    if not isinstance(spec, dict):
        raise UiError(["ui: expected a component object like {\"type\": \"form\", ...}"])
    ctx = _Ctx()
    root = _node(spec, ctx, "ui", 1)
    if ctx.problems or root is None:
        raise UiError(ctx.problems or ["ui: nothing to show"])
    out = {"title": ctx.text(spec.get("title"), "title", "", 120), "ui": root, "interactive": ctx.interactive}
    if len(json.dumps(out)) > MAX_BYTES:
        raise UiError([f"ui: larger than {MAX_BYTES // 1000} KB"])
    return out


def ui_dir():
    return config.VAULT_PATH / "hi" / "ui"


def save(spec: dict) -> str:
    slug = re.sub(r"[^\w-]+", "-", (spec["title"] or spec["ui"]["type"]).lower()).strip("-")[:40] or "ui"
    name = f"{slug}-{datetime.now():%H%M%S}.json"
    ui_dir().mkdir(parents=True, exist_ok=True)
    (ui_dir() / name).write_text(json.dumps(spec))
    return URL_PREFIX + name


@tool
def show_ui(ui: dict | str, title: str = "") -> str:
    """Show interactive UI in the chat instead of listing options in text: use it when the user must choose, confirm or
    fill something in, and for results that read better as a table, stats, steps, a chart or tabs. The user's answers come
    back as their next message. Do not use it for ordinary answers.

    `ui` is JSON: one component {"type": ..., ...} or a list of them. Components (all props optional unless marked):
    Layout: stack, row, grid{columns}, card{title, description, children}, tabs{tabs:[{label, children}]},
    accordion{items:[{label, children}]}, divider.
    Display: heading{text, level}, text{text (markdown)}, badge{text, tone}, alert{title, text, tone: info|success|
    warning|danger}, list{items, ordered}, table{columns, rows}, stat{label, value, delta}, progress{value 0-100},
    code{text, lang}, image{src}, chart{kind: bar|line|area|pie, data:[{label, value}]}, mermaid{code},
    scene3d{scene}, timeline{items:[{title, text, time, state}]}, steps{items:[{title, state: done|active|pending}]}.
    Input (each needs a unique `name`; also label, description, required, default, placeholder): input (one line of
    text), textarea, number, date,
    select{options}, radio{options}, checkbox, checkboxes{options}, switch, slider{min, max, step}, rating{max}.
    Options are strings or {value, label, description}.
    Actions: button{label, action, variant}, form{children, submit, action}, dialog{trigger, title, description, children,
    actions:[{label, action}]}, confirm{trigger, title, description, confirm, destructive, action},
    wizard{steps:[{title, description, children}], submit, action}. An action sends every named value.

    Example: {"title": "Deploy", "type": "form", "action": "deploy", "submit": "Deploy", "children": [
    {"type": "radio", "name": "env", "label": "Environment", "options": ["staging", "production"], "required": true},
    {"type": "checkboxes", "name": "notify", "label": "Tell", "options": ["Team", "Customers"]}]}

    Args:
        ui: The component, or a list of components.
        title: Heading for the block, also named in the user's reply.
    """
    try:
        data = {**ui, "title": ui.get("title") or title} if isinstance(ui, dict) and title else ui
        spec = normalize(data)
    except UiError as e:
        return "Not shown. Fix these and call show_ui again:\n- " + "\n- ".join(e.problems)
    path = save(spec)
    if spec["interactive"]:
        return (f"The UI is now shown to the user: {path}. It waits for their input. {WAIT_MARKER} without adding "
                "anything: their response arrives as their next message, and then you carry on.")
    return f"The UI is already displayed to the user (do not repeat it in text): {path}"
