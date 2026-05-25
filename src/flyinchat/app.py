import shlex
import time
from dataclasses import dataclass

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Input, Static

from .api_client import stream_chat_completion
from .models import LLMChannel, LLMModel
from .paths import AppPaths
from .storage import (
    PROVIDER_PRESETS,
    add_message,
    create_channel_with_models,
    create_conversation,
    create_preset_channel,
    get_primary_llm_model,
    initialize_storage,
    list_conversations,
    list_llm_channels,
    list_llm_models,
    list_messages,
    set_primary_llm_model,
)

_EMPTY_LOGO = """
███████╗██╗  ██╗   ██╗██╗███╗   ██╗ ██████╗██╗  ██╗ █████╗ ████████╗
██╔════╝██║  ╚██╗ ██╔╝██║████╗  ██║██╔════╝██║  ██║██╔══██╗╚══██╔══╝
█████╗  ██║   ╚████╔╝ ██║██╔██╗ ██║██║     ███████║███████║   ██║
██╔══╝  ██║    ╚██╔╝  ██║██║╚██╗██║██║     ██╔══██║██╔══██║   ██║
██║     ███████╗██║   ██║██║ ╚████║╚██████╗██║  ██║██║  ██║   ██║
╚═╝     ╚══════╝╚═╝   ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
""".strip()


@dataclass(frozen=True)
class SelectionItem:
    key: str
    title: str
    description: str


@dataclass(frozen=True)
class FormState:
    kind: str
    step: int
    values: tuple[str, ...]


_COMMANDS = (
    SelectionItem("/api", "/api", "LLM API provider settings"),
    SelectionItem("/model", "/model", "Choose the primary model"),
    SelectionItem("/sessions", "/sessions", "Open project session history"),
    SelectionItem("/clear", "/clear", "Start a new session"),
)

_API_ACTIONS = (
    SelectionItem("deepseek", "Add DeepSeek preset", "Only asks for an API key"),
    SelectionItem("openai", "Add OpenAI-compatible channel", "Name, base URL, API key, models"),
    SelectionItem("anthropic", "Add Anthropic channel", "Name, API key, models"),
)


class FlyinChatApp(App[None]):
    TITLE = "FlyinChat"

    def __init__(self, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.paths = paths
        self.active_conversation_id: str | None = None
        self.selection_context: str | None = None
        self.selection_title = ""
        self.selection_header = ""
        self.selection_footer = ""
        self.selection_items: tuple[SelectionItem, ...] = ()
        self.selected_index = 0
        self.form_state: FormState | None = None
        self._last_escape_time = 0.0

    CSS = """
    Screen {
        background: #0a0e17;
        color: #d7dde8;
        layout: vertical;
    }

    Header {
        background: #0f1724;
        color: #edf2f7;
    }

    #chat-area {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }

    #empty-state {
        width: 100%;
        align: center middle;
    }

    #empty-logo {
        color: #7dd3fc;
        text-align: center;
        text-style: bold;
    }

    #empty-hint {
        margin-top: 1;
        color: #8b9bb4;
        text-align: center;
    }

    #message-view {
        width: 100%;
        color: #edf2f7;
    }

    #composer {
        height: auto;
        padding: 1 2;
        background: #0a0e17;
        border-top: solid #1f2a3d;
    }

    #command-menu {
        display: none;
        margin-bottom: 1;
        padding: 1 2;
        background: #101827;
        color: #d7dde8;
        border: round #334155;
    }

    #input-label {
        color: #8b9bb4;
        margin-bottom: 1;
    }

    #prompt-input {
        background: #101827;
        color: #edf2f7;
        border: round #334155;
    }

    #prompt-input:focus {
        border: round #7dd3fc;
    }

    Footer {
        background: #0f1724;
        color: #8b9bb4;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        self.paths = initialize_storage(self.paths)

        yield Header()
        with Container(id="chat-area"):
            with Vertical(id="empty-state"):
                yield Static(_EMPTY_LOGO, id="empty-logo")
                yield Static("Start a project-local conversation from the prompt below.", id="empty-hint")
            yield Static("", id="message-view")
        with Vertical(id="composer"):
            yield Static("", id="command-menu")
            yield Static("Message", id="input-label")
            yield Input(placeholder="Ask FlyinChat anything, or type / for commands", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            now = time.monotonic()
            if now - self._last_escape_time < 0.5:
                self._last_escape_time = 0.0
                self._clear_input()
                self._reset_selection()
                return
            self._last_escape_time = now
            return

        if not self.selection_items:
            return

        if event.key == "up":
            event.prevent_default()
            self.selected_index = (self.selected_index - 1) % len(self.selection_items)
            self._render_selection()
            return

        if event.key == "down":
            event.prevent_default()
            self.selected_index = (self.selected_index + 1) % len(self.selection_items)
            self._render_selection()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.form_state is not None:
            return

        value = event.value.strip()
        if value.startswith("/"):
            self._show_command_menu(value)
            return

        self.query_one("#command-menu", Static).display = False
        if self.selection_context == "main":
            self._clear_selection()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if self.paths is None:
            return

        if self.form_state is not None:
            self._submit_form_value(prompt, event.input)
            return

        if prompt.startswith("/api add ") or prompt.startswith("/model use "):
            self._run_command(prompt)
            event.input.value = ""
            self.query_one("#command-menu", Static).display = False
            return

        if self.selection_items and (not prompt or prompt.startswith("/")):
            self._activate_selection()
            event.input.value = ""
            self.query_one("#command-menu", Static).display = False
            return

        if not prompt:
            return

        if prompt.startswith("/"):
            self._run_command(prompt)
            event.input.value = ""
            self.query_one("#command-menu", Static).display = False
            return

        if self.active_conversation_id is None:
            conversation = create_conversation(self.paths.chat_db, title=prompt[:80])
            self.active_conversation_id = conversation.id

        add_message(
            self.paths.chat_db,
            conversation_id=self.active_conversation_id,
            role="user",
            content=prompt,
        )
        self._clear_selection()
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Static).update(f"You\n{prompt}")
        event.input.value = ""
        self._stream_response()

    def _run_command(self, command: str) -> None:
        if command == "/api":
            self._show_api_settings()
            return
        if command.startswith("/api add "):
            self._add_api_channel(command)
            return
        if command == "/model":
            self._show_model_settings()
            return
        if command.startswith("/model use "):
            self._select_primary_model(command)
            return

        match command:
            case "/sessions":
                self._show_sessions()
            case "/clear":
                self._start_new_session()
            case _:
                self._show_panel("Unknown command", f"No command named {command}. Type / to see available commands.")

    def _show_command_menu(self, query: str) -> None:
        command_menu = self.query_one("#command-menu", Static)
        matches = tuple(command for command in _COMMANDS if command.key.startswith(query))
        if not matches:
            self._clear_selection()
            command_menu.update("No matching commands\nType /api, /model, /sessions, or /clear")
            command_menu.display = True
            return

        self._set_selection(
            context="main",
            title="Commands",
            items=matches,
            footer="Use ↑/↓ to select, Enter to open.",
            target_menu=True,
        )

    def _activate_selection(self) -> None:
        if not self.selection_items:
            return

        item = self.selection_items[self.selected_index]
        match self.selection_context:
            case "main":
                self._run_command(item.key)
            case "api_actions":
                self._start_api_form(item.key)
            case "model_select":
                self._set_primary_model_by_id(item.key)
            case "session_select":
                self.active_conversation_id = item.key
                self._clear_selection()
                self._show_panel("Session selected", item.title)

    def _add_api_channel(self, command: str) -> None:
        if self.paths is None:
            return

        try:
            parts = shlex.split(command)
            if len(parts) < 4:
                raise ValueError("Missing API channel arguments")

            channel_type = parts[2]
            if channel_type == "deepseek":
                if len(parts) != 4:
                    raise ValueError("Usage: /api add deepseek <api-key>")
                channel, models = create_preset_channel(
                    self.paths.config_db,
                    preset_id="deepseek",
                    api_key=parts[3],
                )
            elif channel_type == "openai":
                if len(parts) != 7:
                    raise ValueError("Usage: /api add openai <name> <base-url> <api-key> <model1,model2>")
                channel, models = create_channel_with_models(
                    self.paths.config_db,
                    name=parts[3],
                    provider_type="openai_compatible",
                    base_url=parts[4],
                    api_key=parts[5],
                    model_names=parts[6].split(","),
                )
            elif channel_type == "anthropic":
                if len(parts) != 6:
                    raise ValueError("Usage: /api add anthropic <name> <api-key> <model1,model2>")
                channel, models = create_channel_with_models(
                    self.paths.config_db,
                    name=parts[3],
                    provider_type="anthropic",
                    api_key=parts[4],
                    model_names=parts[5].split(","),
                )
            else:
                raise ValueError("Supported channel types: deepseek, openai, anthropic")
        except ValueError as error:
            self._clear_selection()
            self._show_panel("API setup error", str(error))
            return

        self._clear_selection()
        self._show_channel_added(channel, models)

    def _show_api_settings(self) -> None:
        if self.paths is None:
            return

        channels = list_llm_channels(self.paths.config_db)
        header = "\n".join(("Configured channels", self._format_channels(channels), "", "Presets", *self._format_presets(), ""))
        self._set_selection(
            context="api_actions",
            title="LLM API providers",
            items=_API_ACTIONS,
            header=header,
            footer="Use ↑/↓ to choose an action, Enter to continue.",
        )

    def _show_model_settings(self) -> None:
        if self.paths is None:
            return

        channels = list_llm_channels(self.paths.config_db)
        if not channels:
            self._clear_selection()
            self._show_panel("Primary model", "No API providers configured yet. Add one with /api.")
            return

        primary = get_primary_llm_model(self.paths.config_db)
        rows = ["Configured provider models"]
        items: list[SelectionItem] = []
        for channel_index, channel in enumerate(channels, start=1):
            models = list_llm_models(self.paths.config_db, channel_id=channel.id)
            rows.append(f"{channel_index}. {channel.name} · {channel.provider_type}")
            for model_index, model in enumerate(models, start=1):
                rows.append(self._format_model_row(channel_index, model_index, model, primary))
                items.append(SelectionItem(model.id, f"{channel.name} / {model.name}", "Set as primary model"))

        self._set_selection(
            context="model_select",
            title="Primary model",
            items=tuple(items),
            header="\n".join(rows),
            footer="Use ↑/↓ to choose a model, Enter to set primary.",
        )

    def _select_primary_model(self, command: str) -> None:
        if self.paths is None:
            return

        try:
            parts = shlex.split(command)
            if len(parts) != 4:
                raise ValueError("Usage: /model use <channel> <model>")
            channel_index = int(parts[2]) - 1
            model_index = int(parts[3]) - 1
            channels = list_llm_channels(self.paths.config_db)
            channel = channels[channel_index]
            models = list_llm_models(self.paths.config_db, channel_id=channel.id)
            model = models[model_index]
            selected_channel, selected_model = set_primary_llm_model(self.paths.config_db, model_id=model.id)
        except (IndexError, ValueError):
            self._clear_selection()
            self._show_panel("Model selection error", "Usage: /model use <channel> <model>")
            return

        self._clear_selection()
        self._show_primary_model_selected(selected_channel, selected_model)

    def _show_sessions(self) -> None:
        if self.paths is None:
            return

        conversations = list_conversations(self.paths.chat_db)
        if not conversations:
            self._clear_selection()
            self._show_panel("Session history", "No project-local sessions yet. Send a message to create one.")
            return

        items = tuple(
            SelectionItem(conversation.id, conversation.title, conversation.updated_at)
            for conversation in conversations
        )
        self._set_selection(
            context="session_select",
            title="Session history",
            items=items,
            footer="Use ↑/↓ to choose a session, Enter to select.",
        )

    def _start_new_session(self) -> None:
        self.active_conversation_id = None
        self._clear_selection()
        self.query_one("#empty-state", Vertical).display = True
        self._show_panel("New session", "Ready for a new project-local conversation.")

    def _start_api_form(self, kind: str) -> None:
        self._clear_selection()
        self.form_state = FormState(kind=kind, step=0, values=())
        self._render_form_prompt()

    def _submit_form_value(self, value: str, input_widget: Input) -> None:
        if self.form_state is None or self.paths is None:
            return
        if not value:
            self._show_panel("Input required", "Please enter a value to continue.")
            self._render_form_prompt()
            return

        values = (*self.form_state.values, value)
        fields = self._api_form_fields(self.form_state.kind)
        if len(values) < len(fields):
            self.form_state = FormState(kind=self.form_state.kind, step=self.form_state.step + 1, values=values)
            input_widget.value = ""
            self._render_form_prompt()
            return

        try:
            if self.form_state.kind == "deepseek":
                channel, models = create_preset_channel(self.paths.config_db, preset_id="deepseek", api_key=values[0])
            elif self.form_state.kind == "openai":
                channel, models = create_channel_with_models(
                    self.paths.config_db,
                    name=values[0],
                    provider_type="openai_compatible",
                    base_url=values[1],
                    api_key=values[2],
                    model_names=values[3].split(","),
                )
            elif self.form_state.kind == "anthropic":
                channel, models = create_channel_with_models(
                    self.paths.config_db,
                    name=values[0],
                    provider_type="anthropic",
                    api_key=values[1],
                    model_names=values[2].split(","),
                )
            else:
                raise ValueError("Unsupported API setup form")
        except ValueError as error:
            self.form_state = None
            input_widget.value = ""
            self._set_input_prompt("Message", "Ask FlyinChat anything, or type / for commands")
            self._show_panel("API setup error", str(error))
            return

        self.form_state = None
        input_widget.value = ""
        self._set_input_prompt("Message", "Ask FlyinChat anything, or type / for commands")
        self._show_channel_added(channel, models)

    def _render_form_prompt(self) -> None:
        if self.form_state is None:
            return

        fields = self._api_form_fields(self.form_state.kind)
        field = fields[self.form_state.step]
        self._set_input_prompt(field, field)
        self._show_panel(
            "Add API channel",
            f"{self._api_form_title(self.form_state.kind)}\nStep {self.form_state.step + 1}/{len(fields)}: {field}",
        )

    def _api_form_fields(self, kind: str) -> tuple[str, ...]:
        match kind:
            case "deepseek":
                return ("DeepSeek API key",)
            case "openai":
                return ("Channel name", "Base URL", "API key", "Models, comma separated")
            case "anthropic":
                return ("Channel name", "API key", "Models, comma separated")
            case _:
                return ()

    def _api_form_title(self, kind: str) -> str:
        match kind:
            case "deepseek":
                return "DeepSeek preset"
            case "openai":
                return "OpenAI-compatible channel"
            case "anthropic":
                return "Anthropic channel"
            case _:
                return "API channel"

    def _set_primary_model_by_id(self, model_id: str) -> None:
        if self.paths is None:
            return

        selected_channel, selected_model = set_primary_llm_model(self.paths.config_db, model_id=model_id)
        self._clear_selection()
        self._show_primary_model_selected(selected_channel, selected_model)

    def _show_channel_added(self, channel: LLMChannel, models: list[LLMModel]) -> None:
        model_names = ", ".join(model.name for model in models)
        self._show_panel(
            "API channel added",
            f"{channel.name}\n{channel.provider_type}\n{channel.base_url or 'default endpoint'}\nmodels: {model_names}",
        )

    def _show_primary_model_selected(self, channel: LLMChannel, model: LLMModel) -> None:
        self._show_panel(
            "Primary model selected",
            f"{channel.name}\n{model.name}",
        )

    def _format_channels(self, channels: list[LLMChannel]) -> str:
        if self.paths is None:
            return "No providers configured yet."
        if not channels:
            return "No providers configured yet. Select a preset below to add one."

        rows: list[str] = []
        for index, channel in enumerate(channels, start=1):
            models = list_llm_models(self.paths.config_db, channel_id=channel.id)
            model_names = ", ".join(model.name for model in models) or "No models"
            endpoint = channel.base_url or "default endpoint"
            rows.append(
                f"{index}. {channel.name} · {channel.provider_type} · {endpoint} · key {self._mask_api_key(channel.api_key)}\n"
                f"   models: {model_names}"
            )
        return "\n".join(rows)

    def _format_model_row(
        self,
        channel_index: int,
        model_index: int,
        model: LLMModel,
        primary: tuple[LLMChannel, LLMModel] | None,
    ) -> str:
        marker = " [primary]" if primary is not None and primary[1].id == model.id else ""
        return f"   {channel_index}.{model_index} {model.name}{marker}"

    def _format_presets(self) -> list[str]:
        rows: list[str] = []
        for preset in PROVIDER_PRESETS.values():
            rows.append(
                f"{preset.id}: {preset.name} · {preset.provider_type} · {preset.base_url}\n"
                f"   models: {', '.join(preset.model_names)}"
            )
        return rows

    def _set_selection(
        self,
        *,
        context: str,
        title: str,
        items: tuple[SelectionItem, ...],
        header: str = "",
        footer: str = "",
        target_menu: bool = False,
    ) -> None:
        self.selection_context = context
        self.selection_title = title
        self.selection_header = header
        self.selection_footer = footer
        self.selection_items = items
        self.selected_index = 0
        self._render_selection(target_menu=target_menu)

    def _render_selection(self, target_menu: bool = False) -> None:
        rows: list[str] = []
        if self.selection_header:
            rows.append(self.selection_header)
        if self.selection_items:
            rows.append(self.selection_title)
            for index, item in enumerate(self.selection_items):
                pointer = ">" if index == self.selected_index else " "
                rows.append(f"{pointer} {index + 1}. {item.title}\n    {item.description}")
        if self.selection_footer:
            rows.append(self.selection_footer)

        content = "\n".join(rows)
        if target_menu or self.selection_context == "main":
            command_menu = self.query_one("#command-menu", Static)
            command_menu.update(content)
            command_menu.display = True
            return

        self._show_panel(self.selection_title, content)

    def _clear_selection(self) -> None:
        self.selection_context = None
        self.selection_title = ""
        self.selection_header = ""
        self.selection_footer = ""
        self.selection_items = ()
        self.selected_index = 0
        self.query_one("#command-menu", Static).display = False

    def _clear_input(self) -> None:
        self.query_one("#prompt-input", Input).clear()

    def _reset_selection(self) -> None:
        self._clear_selection()
        self._set_input_prompt("Message", "Ask FlyinChat anything, or type / for commands")

    def _set_input_prompt(self, label: str, placeholder: str) -> None:
        self.query_one("#input-label", Static).update(label)
        self.query_one("#prompt-input", Input).placeholder = placeholder

    def _show_panel(self, title: str, body: str) -> None:
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Static).update(f"{title}\n\n{body}")

    def _mask_api_key(self, api_key: str) -> str:
        if len(api_key) <= 6:
            return "configured"
        return f"{api_key[:3]}...{api_key[-2:]}"

    @work
    async def _stream_response(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            message_view = self.query_one("#message-view", Static)
            current = message_view.content or ""
            message_view.update(
                f"{current}\n\nAssistant\n[No model configured. Add one with /api, then /model.]"
            )
            return

        channel, model = primary
        api_messages: list[dict[str, str]] = []
        history = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
        for msg in history:
            api_messages.append({"role": msg.role, "content": msg.content})

        message_view = self.query_one("#message-view", Static)
        prefix = (message_view.content or "") + "\n\nAssistant\n"

        full_response = ""
        try:
            async for token in stream_chat_completion(channel, model, api_messages):
                full_response += token
                message_view.update(f"{prefix}{full_response}")
        except Exception as error:
            message_view.update(f"{prefix}[Error: {error}]")
            return

        if full_response:
            add_message(
                self.paths.chat_db,
                conversation_id=self.active_conversation_id,
                role="assistant",
                content=full_response,
            )


def run() -> None:
    FlyinChatApp().run()
