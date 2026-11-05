"""`hi --tui`: a plain monospaced chat over the same agent stack as the
other frontends. One process, no server — AG-UI events from
`hi.ipc.server.stream_query_as_agui` are rendered directly.
"""

from __future__ import annotations

import re
import threading
import time

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

import hi.config as config
from hi import llm
from hi.personas import PERSONAS
from hi.tui.settings import SettingsScreen

ACCENT = "cyan"  # Rich style names; CSS below uses the ansi_ equivalents
ERROR = "red"
TOOL_RESULT_CHARS = 240

HELP = """\
/persona auto|term|butler|docs|web   pick who answers (default auto)
/settings                            ollama host + models
/set KEY VALUE                       set any ~/.hi/.env variable
/models                              models on the configured host
/history [date]                      past conversations
/tasks [id|stop id]                  background tasks and on-demand agents
/agent <prompt>                      start an on-demand agent
/answer <id> a | b                   answer an agent's questions
/status                              system and vault stats
/briefing   /clear   /quit
esc cancels a running reply · ctrl+c quits"""


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "yes"),
        Binding("n,escape", "answer(False)", "no"),
    ]

    def __init__(self, description: str) -> None:
        super().__init__()
        self._description = description

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(("confirm  ", f"bold {ERROR}"), self._description, ("\n\n[y] yes   [n] no", "dim")), id="confirm")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class HiApp(App):
    ansi_color = True
    CSS = f"""
    Screen {{ background: ansi_default; color: ansi_default; }}
    #log {{ padding: 0 1; background: ansi_default; scrollbar-size-vertical: 1; }}
    #log Static {{ background: ansi_default; margin-bottom: 1; }}
    #status {{ height: 1; padding: 0 1; color: ansi_default 50%; background: ansi_default; }}
    Input {{ border: none; border-top: solid ansi_default 40%; background: ansi_default; padding: 0 1; }}
    Input:focus {{ border: none; border-top: solid ansi_{ACCENT}; }}
    ConfirmScreen, SettingsScreen {{ align: center middle; background: ansi_default 60%; }}
    #confirm {{ width: 70; height: auto; border: solid ansi_{ERROR}; padding: 1 2; background: ansi_default; }}
    #settings-body {{ width: 100%; height: 1fr; padding: 1 2; background: ansi_default; }}
    #fields {{ width: 3fr; }}
    #models {{ width: 2fr; margin-left: 2; }}
    #settings-status {{ height: 1; padding: 0 2; color: ansi_default 50%; background: ansi_default; }}
    SettingsScreen Input {{ border: tall ansi_default 40%; padding: 0 1; }}
    SettingsScreen Input:focus {{ border: tall ansi_{ACCENT}; }}
    SettingsScreen Label {{ color: ansi_default 50%; background: ansi_default; }}
    OptionList {{ border: none; background: ansi_default; }}
    """
    BINDINGS = [
        Binding("escape", "cancel", "cancel reply", show=False),
        Binding("ctrl+c", "quit", "quit", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.persona = "auto"
        self.state = "loading"
        self._cancel = threading.Event()
        self._suggested_action: str | None = None
        self._history: list[str] = []
        self._history_pos = 0

    # --- layout -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="log")
        yield Static(id="status")
        yield Input(placeholder="message, or /help", id="prompt")

    def on_mount(self) -> None:
        self.query_one("#log").anchor()
        self.query_one("#prompt").focus()
        self._refresh_status()
        self.set_interval(1, self._refresh_status)
        self._preload()
        self._show_briefing()
        self._note("/help for commands")

    def _refresh_status(self) -> None:
        text = f"{self.state} · persona {self.persona} · {llm.describe()} · {config.SONNET_MODEL}"
        self.query_one("#status", Static).update(Text(text))

    # --- transcript helpers (main thread) --------------------------------------
    def _add(self, text: str | Text = "", style: str = "") -> Static:
        widget = Static(text if isinstance(text, Text) else Text(text, style=style))
        self.query_one("#log").mount(widget)
        return widget

    def _note(self, text: str) -> None:
        self._add(text, "dim")

    def _error(self, text: str) -> None:
        self._add(text, ERROR)

    # --- startup ----------------------------------------------------------------
    @work(thread=True)
    def _preload(self) -> None:
        """Import the agent stack and build the default agent off the UI thread."""
        try:
            from hi.action_tiers import set_confirm_handler
            from hi.ipc.server import _get_agent
            from hi.models import get_tier_model_fast

            set_confirm_handler(self._confirm_from_thread)
            get_tier_model_fast("haiku")
            _get_agent("term", "sonnet")
            self.call_from_thread(self._set_state, "ready")
        except Exception as e:
            self.call_from_thread(self._set_state, "ready")
            self.call_from_thread(self._error, f"startup: {e}  (fix with /settings)")

    @work(thread=True)
    def _show_briefing(self) -> None:
        try:
            from hi.briefing import build_briefing

            briefing = build_briefing()
        except Exception:
            return
        if briefing:
            context, suggestion, action = briefing
            self._suggested_action = action
            self.call_from_thread(self._note, f"{context}\n\n{suggestion}" if suggestion else context)

    def _set_state(self, state: str) -> None:
        self.state = state
        self._refresh_status()

    # --- confirmation (any thread) ---------------------------------------------
    def _confirm_from_thread(self, description: str) -> bool:
        done, answer = threading.Event(), []

        def resolve(value: bool | None) -> None:
            answer.append(bool(value))
            done.set()

        self.call_from_thread(self.push_screen, ConfirmScreen(description), resolve)
        done.wait()
        return answer[0]

    # --- input --------------------------------------------------------------------
    @on(Input.Submitted, "#prompt")
    def _submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._history.append(text)
        self._history_pos = len(self._history)
        if text.startswith("/"):
            self._command(text)
        elif self.state == "working":
            self._note("still replying — esc to cancel")
        else:
            if self._suggested_action and text.lower() in {"y", "yes", "yeah", "ok", "okay", "sure"}:
                text = self._suggested_action
            self._suggested_action = None
            self._ask(text)

    def on_key(self, event) -> None:
        if event.key in ("up", "down") and self.query_one("#prompt").has_focus and self._history:
            step = -1 if event.key == "up" else 1
            self._history_pos = max(0, min(len(self._history), self._history_pos + step))
            prompt = self.query_one("#prompt", Input)
            prompt.value = self._history[self._history_pos] if self._history_pos < len(self._history) else ""
            prompt.cursor_position = len(prompt.value)
            event.stop()

    def action_cancel(self) -> None:
        if self.state == "working":
            self._cancel.set()

    # --- chat ---------------------------------------------------------------------
    def _ask(self, text: str) -> None:
        self._add(Text.assemble(("> ", ACCENT), text))
        self._set_state("working")
        self._cancel.clear()
        self._stream_reply(text, None if self.persona == "auto" else self.persona)

    @work(thread=True)
    def _stream_reply(self, text: str, persona: str | None) -> None:
        call = self.call_from_thread
        view = _TurnView(self, call)
        started = time.monotonic()
        try:
            from hi.ipc.server import stream_query_as_agui

            for event in stream_query_as_agui(text, forced_persona=persona):
                if self._cancel.is_set():
                    call(self._note, "(cancelled)")
                    break
                view.handle(event)
        except Exception as e:
            call(self._error, f"error: {e}")
        finally:
            call(self._set_state, "ready")
            call(self._note, f"{time.monotonic() - started:.1f}s")

    # --- slash commands -------------------------------------------------------
    def _command(self, line: str) -> None:
        name, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        handler = {
            "help": lambda: self._note(HELP),
            "clear": lambda: self.query_one("#log").remove_children(),
            "quit": self.exit,
            "exit": self.exit,
            "settings": lambda: self.push_screen(SettingsScreen()),
            "persona": lambda: self._set_persona(arg),
            "set": lambda: self._set_var(arg),
            "models": self._list_models,
            "history": lambda: self._history_cmd(arg),
            "tasks": lambda: self._tasks(arg),
            "agent": lambda: self._start_agent(arg),
            "answer": lambda: self._answer_agent(arg),
            "status": self._status_cmd,
            "briefing": self._show_briefing,
        }.get(name)
        if handler is None:
            self._error(f"unknown command /{name} — /help")
        else:
            handler()

    def _set_persona(self, name: str) -> None:
        if name not in ("auto", *PERSONAS):
            self._error(f"persona must be one of: auto, {', '.join(PERSONAS)}")
            return
        self.persona = name
        self._refresh_status()

    def _set_var(self, arg: str) -> None:
        key, _, value = arg.partition(" ")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value.strip():
            self._error("usage: /set KEY VALUE   (KEY in UPPER_SNAKE_CASE)")
            return
        config.set_value(key, value.strip())
        self._note(f"{key} saved to ~/.hi/.env and applied")
        self._refresh_status()

    @work(thread=True)
    def _list_models(self) -> None:
        from hi.models import available_models

        try:
            names = available_models()
            self.call_from_thread(self._note, "\n".join(names) or "(no models on host)")
        except (OSError, ValueError) as e:
            self.call_from_thread(self._error, f"can't reach {llm.describe()}: {e}")

    @work(thread=True)
    def _history_cmd(self, date: str) -> None:
        from hi.vault import list_conversations, read_conversation

        text = read_conversation.invoke({"date": date}) if date else list_conversations.invoke({})
        self.call_from_thread(self._note, text)

    def _tasks(self, arg: str) -> None:
        from hi.agents.term.background_tasks import get_process, list_processes, stop_process
        from hi.agents_ondemand import get_run, list_runs

        words = arg.split()
        if words[:1] == ["stop"] and len(words) == 2:
            self._note("stopped" if stop_process(words[1]) else f"can't stop {words[1]}")
            return
        if words:
            process, run = get_process(words[0]), get_run(words[0])
            if process:
                d = process.to_dict()
                self._note(f"{d['command']} — {d['status']}\n{d['output_tail'][-1500:]}")
            elif run:
                self._note(f"{run.prompt} — {run.status}\n{run.result or run.error or ''}")
            else:
                self._error(f"no task {words[0]}")
            return
        lines = [f"{p.id}  {p.to_dict()['status']:8} {p.command}" for p in list_processes()]
        lines += [f"{r.id}  {r.status:8} agent: {r.prompt[:60]}" for r in list_runs()]
        self._note("\n".join(lines) or "no tasks")

    def _start_agent(self, prompt: str) -> None:
        if not prompt:
            self._error("usage: /agent <prompt>")
            return
        self._agent_call(prompt, None)

    def _answer_agent(self, arg: str) -> None:
        run_id, _, answers = arg.partition(" ")
        if not run_id or not answers:
            self._error("usage: /answer <id> first answer | second answer")
            return
        self._agent_call(run_id, [a.strip() for a in answers.split("|")])

    @work(thread=True)
    def _agent_call(self, prompt_or_id: str, answers: list[str] | None) -> None:
        from hi.agents_ondemand import answer_questions, create_run

        run = answer_questions(prompt_or_id, answers) if answers else create_run(prompt_or_id)
        if run is None:
            self.call_from_thread(self._error, "no such agent run")
            return
        text = f"agent {run.id}: {run.status}"
        if run.questions:
            text += "\n" + "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(run.questions))
            text += f"\nreply: /answer {run.id} a1 | a2 …"
        else:
            text += f" — follow with /tasks {run.id}"
        self.call_from_thread(self._note, text)

    @work(thread=True)
    def _status_cmd(self) -> None:
        from hi.dashboard import get_today_stats, get_vault_stats, get_vitals

        lines = []
        for title, data in (
            ("system", get_vitals(active_model=config.SONNET_MODEL)),
            ("vault", get_vault_stats()),
            ("today", get_today_stats()),
        ):
            lines.append(title + "  " + "  ".join(f"{k}={v}" for k, v in data.items()))
        self.call_from_thread(self._note, "\n".join(lines))


class _TurnView:
    """Renders one assistant turn's AG-UI events as transcript blocks."""

    def __init__(self, app: HiApp, call) -> None:
        self.app, self.call = app, call
        self.thinking = Text(style="dim italic")
        self.thinking_widget: Static | None = None
        self.text = Text()
        self.text_widget: Static | None = None
        self.tools: dict[str, tuple[str, str]] = {}  # id -> (name, args)

    def handle(self, event) -> None:
        from ag_ui.core import events as ag

        if isinstance(event, ag.CustomEvent):
            if event.name == "persona_selected":
                v = event.value
                plan = " · plan" if v.get("plan") else ""
                self.call(self.app._note, f"{v['name']}/{v['tier']}{plan}")
            elif event.name == "subagent_retrying":
                self.call(self.app._note, f"retrying {event.value['task_id']}: {event.value['reason']}")
        elif isinstance(event, ag.ThinkingTextMessageContentEvent):
            self.thinking.append(event.delta)
            self.call(self._show, "thinking_widget", self.thinking)
        elif isinstance(event, ag.ToolCallStartEvent):
            self.tools[event.tool_call_id] = (event.tool_call_name, "")
        elif isinstance(event, ag.ToolCallArgsEvent):
            name, args = self.tools.get(event.tool_call_id, ("?", ""))
            self.tools[event.tool_call_id] = (name, args + event.delta)
        elif isinstance(event, ag.ToolCallResultEvent):
            name, args = self.tools.get(event.tool_call_id, ("tool", ""))
            result = " ".join(event.content.split())
            if len(result) > TOOL_RESULT_CHARS:
                result = result[:TOOL_RESULT_CHARS] + "…"
            # text/thinking after a tool call start fresh blocks
            self.text_widget, self.text = None, Text()
            self.thinking_widget, self.thinking = None, Text(style="dim italic")
            self.call(self.app._add, Text.assemble((f"▸ {name}", ACCENT), (f" {args}\n  {result}", "dim")))
        elif isinstance(event, ag.TextMessageContentEvent):
            self.text.append(event.delta)
            self.call(self._show, "text_widget", self.text)
        elif isinstance(event, ag.SubagentStartedEvent):
            self.call(self.app._note, f"[{event.subagent_run_id}: {event.name}] started")
        elif isinstance(event, ag.SubagentFinishedEvent):
            self.call(self.app._note, f"[{event.subagent_run_id}] done")
        elif isinstance(event, ag.SubagentErrorEvent):
            self.call(self.app._error, f"[{event.subagent_run_id}] {event.message}")
        elif isinstance(event, ag.RunErrorEvent):
            self.call(self.app._error, f"error: {event.message}")

    def _show(self, attr: str, text: Text) -> None:
        widget = getattr(self, attr)
        if widget is None:
            widget = self.app._add(text)
            setattr(self, attr, widget)
        else:
            widget.update(text)


def run() -> None:
    HiApp().run()
