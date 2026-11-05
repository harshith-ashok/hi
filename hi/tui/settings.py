"""Settings screen: Ollama host + model names, editable and applied live.

Saving writes ~/.hi/.env and updates `hi.config` in-process (see
`config.set_value`), so the next turn uses the new host/models with no
restart. Ctrl+R fetches the model list from whatever host is typed in the
host field; pick a model from the list to fill the last-focused field.
"""

from __future__ import annotations

import threading

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Input, Label, OptionList, Static

import hi.config as config

MODE_FIELD = "AI_MODE"
SECRET_FIELD = "OPENROUTER_API_KEY"
ENDPOINT_FIELDS = {"local": "OLLAMA_HOST", "tailscale": "TAILSCALE_OLLAMA_URL"}
MODEL_FIELDS = (
    "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL",
    "TERM_MODEL", "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "VISION_MODEL",
)
OTHER_FIELDS = ("VAULT_PATH",)
FIELDS = (MODE_FIELD, *ENDPOINT_FIELDS.values(), SECRET_FIELD, *MODEL_FIELDS, *OTHER_FIELDS)


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "close"),
        Binding("ctrl+s", "save", "save"),
        Binding("ctrl+r", "refresh_models", "refresh models"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._models: list[str] = []
        self._last_model_input: Input | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-body"):
            with VerticalScroll(id="fields"):
                for key in FIELDS:
                    yield Label(key + ("  (local | tailscale | openrouter)" if key == MODE_FIELD else ""))
                    secret = key == SECRET_FIELD  # never shown; leave blank to keep the saved key
                    yield Input("" if secret else str(getattr(config, key)), id=f"f-{key}", password=secret)
            with VerticalScroll(id="models"):
                yield Label("models on host")
                yield OptionList(id="model-list")
        yield Static("ctrl+s save · ctrl+r refresh models · esc close", id="settings-status")

    def on_mount(self) -> None:
        self.action_refresh_models()

    def _field(self, key: str) -> Input:
        return self.query_one(f"#f-{key}", Input)

    def _status(self, text: str) -> None:
        self.query_one("#settings-status", Static).update(text)

    def action_refresh_models(self) -> None:
        mode = self._field(MODE_FIELD).value.strip() or config.AI_MODE
        field = ENDPOINT_FIELDS.get(mode)
        host = self._field(field).value.strip() if field else None
        self._status(f"fetching models ({mode}) …")

        def fetch() -> None:
            from hi.models import available_models

            try:
                models, message = available_models(host=host, mode=mode), ""
            except (OSError, ValueError) as e:
                models, message = [], f"can't reach {host or mode}: {e}"
            self.app.call_from_thread(self._show_models, models, message)

        threading.Thread(target=fetch, daemon=True).start()

    def _show_models(self, models: list[str], error: str) -> None:
        self._models = models
        option_list = self.query_one("#model-list", OptionList)
        option_list.clear_options()
        option_list.add_options(models)
        suggester = SuggestFromList(models, case_sensitive=False)
        for key in MODEL_FIELDS:
            self._field(key).suggester = suggester
        self._status(error or f"{len(models)} models on host · pick one to fill the focused field")

    @on(Input.Blurred)
    def _remember_model_input(self, event: Input.Blurred) -> None:
        if (event.input.id or "").removeprefix("f-") in MODEL_FIELDS:
            self._last_model_input = event.input

    @on(OptionList.OptionSelected)
    def _pick_model(self, event: OptionList.OptionSelected) -> None:
        target = self._last_model_input
        if target is not None:
            target.value = self._models[event.option_index]
            target.focus()

    def action_save(self) -> None:
        changed = []
        mode = self._field(MODE_FIELD).value.strip()
        if mode not in config.MODES:
            self._status(f"AI_MODE must be one of: {', '.join(config.MODES)}")
            return
        # AI_MODE first: model names are stored per mode.
        for key in sorted(FIELDS, key=lambda k: k != MODE_FIELD):
            value = self._field(key).value.strip()
            if value and value != str(getattr(config, key)):
                config.set_value(key, value)
                changed.append(key)
        self._status(f"saved: {', '.join(changed)} (live)" if changed else "nothing changed")
        if changed:
            self.action_refresh_models()
