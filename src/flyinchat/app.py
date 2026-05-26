import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Input, Markdown, Static

from .compact import CompactionEngine, CompactionPolicy, TokenEstimator
from .logging_config import configure_logging
from .message_utils import message_to_api_format, message_to_display
from .models import LLMChannel, LLMModel
from .paths import AppPaths
from .query_engine import QueryEngine, QueryEngineConfig, TurnEvent
from .storage import (
    PROVIDER_PRESETS,
    add_message,
    create_channel_with_models,
    create_conversation,
    create_preset_channel,
    get_conversation,
    get_primary_llm_model,
    initialize_storage,
    list_active_messages,
    list_conversations,
    list_llm_channels,
    list_llm_models,
    list_messages,
    set_model_context_window,
    set_model_reasoning_effort,
    set_model_thinking,
    set_primary_llm_model,
)
from .tools import (
    BashTool,
    FileReadTool,
    FileWriteTool,
    PermissionContext,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
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
    SelectionItem("/thinking", "/thinking", "Toggle reasoning thinking mode on/off"),
    SelectionItem("/reasoning", "/reasoning", "Set reasoning effort level (low/medium/high)"),
    SelectionItem("/1M", "/1M", "Toggle 1M context window mode (125K ↔ 1M)"),
    SelectionItem("/sessions", "/sessions", "Open project session history"),
    SelectionItem("/clear", "/clear", "Start a new session"),
    SelectionItem("/compact", "/compact", "Compact conversation history"),
)

_REASONING_LEVELS = (
    SelectionItem("low", "low", "Fast, minimal reasoning"),
    SelectionItem("medium", "medium", "Balanced reasoning"),
    SelectionItem("high", "high", "Deep, thorough reasoning"),
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
        self._suppress_menu_update = False
        self._last_usage: dict = {}
        self._total_output_tokens = 0
        self._last_input_tokens = 0
        self._tool_registry: ToolRegistry | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_context: ToolContext | None = None
        self._query_engine: QueryEngine | None = None
        self._compacting = False
        self._pending_permission_request_id: str | None = None
        self._streaming_assistant_text = ""
        self._last_stream_render_at = 0.0
        self._stream_render_interval = 0.05
        self._prompt_history: tuple[str, ...] = ()
        self._prompt_history_index: int | None = None
        self._prompt_history_draft = ""

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
        height: auto;
        overflow-y: hidden;
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

    #status-bar {
        height: 1;
        padding: 0 2;
        margin-top: 1;
        color: #6b7d99;
    }

    Footer {
        background: #0f1724;
        color: #8b9bb4;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        self.paths = initialize_storage(self.paths)
        self._init_tools()

        yield Header()
        with Container(id="chat-area"):
            with Vertical(id="empty-state"):
                yield Static(_EMPTY_LOGO, id="empty-logo")
                yield Static("Start a project-local conversation from the prompt below.", id="empty-hint")
            yield Markdown("", id="message-view")
        with Vertical(id="composer"):
            yield Static("", id="command-menu")
            yield Static("Message", id="input-label")
            yield Input(placeholder="Ask FlyinChat anything, or type / for commands", id="prompt-input")
            yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()
        self._render_status_bar()

    def _init_tools(self) -> None:
        workspace = self.paths.project_dir.parent if self.paths is not None else Path.cwd()
        permission = PermissionContext(
            allowed_tools={"file_read"},
            ask_tools={"file_write", "bash"},
            denied_tools=set(),
            allowed_read_roots=[workspace],
            allowed_write_roots=[workspace],
        )
        self._tool_context = ToolContext(
            session_id="flyinchat",
            user_id="user",
            workspace_root=workspace,
            permission=permission,
        )
        self._tool_registry = ToolRegistry()
        self._tool_registry.register(FileReadTool())
        self._tool_registry.register(FileWriteTool())
        self._tool_registry.register(BashTool())
        self._tool_executor = ToolExecutor(self._tool_registry)
        if self._query_engine is not None:
            self._query_engine.configure_tools(
                self._tool_registry, self._tool_executor, self._tool_context
            )

    def _ensure_query_engine(self) -> QueryEngine:
        if self._query_engine is None and self.paths is not None and self.active_conversation_id is not None:
            config = QueryEngineConfig(
                paths=self.paths,
                conversation_id=self.active_conversation_id,
            )
            self._query_engine = QueryEngine(config)
            if self._tool_registry is not None and self._tool_executor is not None and self._tool_context is not None:
                self._query_engine.configure_tools(
                    self._tool_registry, self._tool_executor, self._tool_context
                )
        if self._query_engine is None:
            raise RuntimeError("QueryEngine not initialized")
        return self._query_engine

    async def _handle_turn_event(self, event: TurnEvent) -> None:
        match event.event_type:
            case "turn_start":
                self._streaming_assistant_text = ""
                self._last_stream_render_at = 0.0
                self.query_one("#empty-state", Vertical).display = False
            case "thinking":
                pass
            case "text":
                self._streaming_assistant_text += event.data.get("content", "")
                self._render_streaming_assistant()
            case "tool_use":
                pass
            case "tool_result":
                pass
            case "compact_start":
                self._compacting = True
                self._render_status_bar()
            case "compact_end":
                self._compacting = False
                self._render_status_bar()
            case "turn_end":
                self._last_input_tokens = event.data.get("input_tokens", 0)
                self._total_output_tokens += event.data.get("output_tokens", 0)
                self._streaming_assistant_text = ""
                self._last_stream_render_at = 0.0
                self._render_history()
                self._render_status_bar()
            case "error":
                pass
            case "permission_required":
                self._show_permission_request(event.data)

    @work
    async def _submit_via_engine(self, prompt: str) -> None:
        if self.paths is None:
            return
        engine = self._ensure_query_engine()
        result = await engine.submit_message(
            prompt, on_event=self._handle_turn_event, user_message_persisted=True
        )
        if result.status == "error" and result.error:
            conv = get_conversation(self.paths.chat_db, conversation_id=self.active_conversation_id)
            if conv is not None:
                self._last_input_tokens = conv.last_input_tokens
                self._total_output_tokens = conv.total_output_tokens
            history = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
            history_display = "\n\n---\n\n".join(
                f"**{'You' if msg.role == 'user' else 'Assistant'}**\n\n{self._message_to_display(msg)}"
                for msg in history
            )
            prefix = (history_display + "\n\n---\n\n") if history_display else ""
            self.query_one("#message-view", Markdown).update(
                f"{prefix}**Assistant**\n\n*[Error: {result.error}]*"
            )
            self._render_status_bar()
            return
        self._render_history()
        self._render_status_bar()

    @staticmethod
    def _message_to_api_format(msg) -> dict | None:
        return message_to_api_format(msg)

    @staticmethod
    def _message_to_display(msg) -> str:
        return message_to_display(msg)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            now = time.monotonic()
            if now - self._last_escape_time < 0.5:
                self._last_escape_time = 0.0
                if self._pending_permission_request_id:
                    self._resolve_pending_permission("deny")
                self._clear_input()
                self._reset_selection()
                return
            self._last_escape_time = now
            return

        if self._pending_permission_request_id:
            if event.key == "y":
                event.prevent_default()
                self._resolve_pending_permission("approve")
                return
            if event.key == "n" or event.key == "escape":
                event.prevent_default()
                self._resolve_pending_permission("deny")
                return

        if not self.selection_items:
            if event.key == "up":
                event.prevent_default()
                self._navigate_prompt_history(-1)
                return
            if event.key == "down":
                event.prevent_default()
                self._navigate_prompt_history(1)
                return
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

        if event.key == "tab":
            if self.selection_items:
                event.prevent_default()
                prompt_input = self.query_one("#prompt-input", Input)
                self._suppress_menu_update = True
                prompt_input.value = self.selection_items[self.selected_index].key
                prompt_input.action_end()
                self.selected_index = (self.selected_index + 1) % len(self.selection_items)
                self._render_selection()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._suppress_menu_update:
            self._suppress_menu_update = False
            return

        if self.form_state is not None:
            return

        if self._pending_permission_request_id:
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

        if self._pending_permission_request_id:
            event.input.value = ""
            self._activate_selection()
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
            self._last_usage = {}
            self._total_output_tokens = 0
            self._last_input_tokens = 0
            self._query_engine = None
            self._render_status_bar()

        self._clear_selection()
        if self.paths is not None and self.active_conversation_id is not None:
            add_message(
                self.paths.chat_db,
                conversation_id=self.active_conversation_id,
                role="user",
                content=prompt,
            )
            self._record_prompt_history(prompt)
            self._render_history()
        event.input.value = ""
        self._submit_via_engine(prompt)

    def _record_prompt_history(self, prompt: str) -> None:
        self._prompt_history = (*self._prompt_history, prompt)
        self._prompt_history_index = None
        self._prompt_history_draft = ""

    def _load_prompt_history(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            self._prompt_history = ()
        else:
            messages = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
            self._prompt_history = tuple(
                message.content
                for message in messages
                if message.role == "user" and message.subtype == "normal"
            )
        self._prompt_history_index = None
        self._prompt_history_draft = ""

    def _navigate_prompt_history(self, direction: int) -> None:
        if not self._prompt_history:
            return

        prompt_input = self.query_one("#prompt-input", Input)
        if self._prompt_history_index is None:
            if direction > 0:
                return
            self._prompt_history_draft = prompt_input.value
            next_index = len(self._prompt_history) - 1
        else:
            next_index = self._prompt_history_index + direction

        if next_index < 0:
            next_index = 0
        if next_index >= len(self._prompt_history):
            self._prompt_history_index = None
            prompt_input.value = self._prompt_history_draft
            prompt_input.action_end()
            return

        self._prompt_history_index = next_index
        prompt_input.value = self._prompt_history[next_index]
        prompt_input.action_end()

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
            case "/thinking":
                self._show_thinking_settings()
            case "/reasoning":
                self._show_reasoning_settings()
            case "/1M":
                self._toggle_context_mode()
            case "/sessions":
                self._show_sessions()
            case "/clear":
                self._start_new_session()
            case "/compact":
                self._run_compact()
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
            footer="Use ↑/↓ to select, Tab to autocomplete, Enter to open.",
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
            case "thinking_toggle":
                self._toggle_thinking(item.key)
            case "reasoning_select":
                self._set_reasoning_effort(item.key)
            case "session_select":
                self.active_conversation_id = item.key
                conv = get_conversation(self.paths.chat_db, conversation_id=item.key)
                if conv is not None:
                    self._total_output_tokens = conv.total_output_tokens
                    self._last_input_tokens = conv.last_input_tokens
                else:
                    self._total_output_tokens = 0
                    self._last_input_tokens = 0
                self._last_usage = {}
                self._query_engine = None
                self._load_prompt_history()
                self._clear_selection()
                self._render_history()
                self._render_status_bar()
            case "permission_request":
                self._resolve_pending_permission(item.key)

    def _show_permission_request(self, data: dict) -> None:
        tool_name = data.get("tool_name", "unknown")
        risk_level = data.get("risk_level", "medium")
        args_preview = data.get("args_preview", "")
        reason = data.get("reason", "")
        request_id = data.get("request_id", "")

        self._pending_permission_request_id = request_id

        risk_badge = {"low": "⚠️ LOW", "medium": "⚠️ MEDIUM", "high": "❗ HIGH"}.get(
            risk_level, risk_level.upper()
        )
        panel_body = (
            f"## Permission Required\n\n"
            f"**Tool:** {tool_name}\n\n"
            f"**Risk:** {risk_badge}\n\n"
            f"**Args:** `{args_preview}`\n\n"
            f"**Reason:** {reason}\n\n"
            f"---\n"
            f"Press **Enter** to approve, or **n** to deny"
        )
        self.query_one("#message-view", Markdown).update(panel_body)
        self.query_one("#empty-state", Vertical).display = False
        self._set_input_prompt("Permission required", "Press Enter to approve, n to deny")

        items = (
            SelectionItem("approve", "Approve - allow this tool to execute", ""),
            SelectionItem("deny", "Deny - block this tool call", ""),
        )
        self._set_selection(
            context="permission_request",
            title="⚖️ Action required",
            items=items,
            footer="↑/↓ select  |  Enter confirm  |  y=approve  n=deny  esc=deny",
            target_menu=True,
        )

    def _resolve_pending_permission(self, resolution: str) -> None:
        engine = self._query_engine
        if engine is not None and self._pending_permission_request_id:
            engine.resolve_permission(self._pending_permission_request_id, resolution)
        self._pending_permission_request_id = None
        self._clear_selection()
        self.query_one("#command-menu", Static).display = False
        self._set_input_prompt("Message", "Ask FlyinChat anything, or type / for commands")

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
        self._last_usage = {}
        self._total_output_tokens = 0
        self._last_input_tokens = 0
        self._query_engine = None
        self._load_prompt_history()
        self._clear_selection()
        self.query_one("#empty-state", Vertical).display = True
        self._show_panel("New session", "Ready for a new project-local conversation.")
        self._render_status_bar()

    @work
    async def _run_compact(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            self._show_panel("Compact", "No active conversation to compact.")
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._show_panel("Compact", "No model configured. Add one with `/api`, then `/model`.")
            return

        channel, model = primary
        all_messages = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
        active_messages = list_active_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
        already_compacted = len(active_messages) < len(all_messages)

        policy = CompactionPolicy.from_model(model)
        estimator = TokenEstimator()
        estimated = estimator.estimate_messages(active_messages)

        if already_compacted and estimated <= policy.soft_limit:
            self._clear_selection()
            self._show_panel(
                "Compact",
                f"Already compacted — {estimated // 1000}K tokens is within budget "
                f"({policy.soft_limit // 1000}K limit).",
            )
            return

        api_messages = [
            formatted for msg in active_messages
            if (formatted := self._message_to_api_format(msg)) is not None
        ]

        engine = CompactionEngine(
            self.paths.chat_db,
            self.active_conversation_id,
        )
        self._compacting = True
        self._render_status_bar()
        result = await engine.compact_if_needed_async(
            active_messages, api_messages, policy, force=True, model=model, channel=channel
        )
        self._compacting = False

        if result.applied:
            before_k = result.tokens_before // 1000
            after_k = result.tokens_after // 1000
            self._clear_selection()
            self._show_panel(
                "Conversation compacted",
                f"Strategy: {result.strategy}\nTokens: {before_k}K → {after_k}K",
            )
            self._render_history()
            self._render_status_bar()
        else:
            self._show_panel(
                "Compact",
                "Compaction not needed — conversation is within token budget.",
            )
            self._render_status_bar()

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
        self._last_usage = {}
        hint = f"> Primary model set to **{channel.name} / {model.name}**"
        self._render_history_with_hint(
            hint,
            fallback_title="Primary model selected",
            fallback_body=f"{channel.name}\n{model.name}",
        )
        self._render_status_bar()

    def _show_thinking_settings(self) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._clear_selection()
            self._show_panel("Thinking mode", "No primary model configured. Set one with /model.")
            return

        channel, model = primary
        status = "enabled" if model.thinking_enabled else "disabled"
        options = (
            SelectionItem("on", "Enable thinking", "Turn reasoning thinking on"),
            SelectionItem("off", "Disable thinking", "Turn reasoning thinking off"),
        )
        self._set_selection(
            context="thinking_toggle",
            title="Thinking mode",
            items=options,
            header=f"{channel.name} / {model.name}\nThinking is currently {status}",
            footer="Use ↑/↓ to choose, Enter to toggle.",
        )

    def _toggle_thinking(self, action: str) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._clear_selection()
            return

        model = primary[1]
        enabled = action == "on"
        updated = set_model_thinking(self.paths.config_db, model_id=model.id, enabled=enabled)
        self._clear_selection()
        status = "enabled" if updated.thinking_enabled else "disabled"
        hint = f"> Thinking is now **{status}** for {primary[0].name} / {updated.name}"
        self._render_history_with_hint(hint, fallback_title="Thinking mode", fallback_body=hint.lstrip("> "))
        self._render_status_bar()

    def _show_reasoning_settings(self) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._clear_selection()
            self._show_panel("Reasoning effort", "No primary model configured. Set one with /model.")
            return

        channel, model = primary
        self._set_selection(
            context="reasoning_select",
            title="Reasoning effort",
            items=_REASONING_LEVELS,
            header=f"{channel.name} / {model.name}\nCurrent level: {model.reasoning_effort}",
            footer="Use ↑/↓ to choose, Enter to set.",
        )

    def _set_reasoning_effort(self, level: str) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._clear_selection()
            return

        model = primary[1]
        updated = set_model_reasoning_effort(self.paths.config_db, model_id=model.id, effort=level)
        self._clear_selection()
        hint = f"> Reasoning effort set to **{updated.reasoning_effort}** for {primary[0].name} / {updated.name}"
        self._render_history_with_hint(
            hint,
            fallback_title="Reasoning effort",
            fallback_body=f"Level set to **{updated.reasoning_effort}** for {primary[0].name} / {updated.name}",
        )
        self._render_status_bar()

    def _toggle_context_mode(self) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self._clear_selection()
            self._show_panel("Context window", "No primary model configured. Set one with /model.")
            return

        channel, model = primary
        new_size = 125_000 if model.context_window >= 1_000_000 else 1_000_000
        updated = set_model_context_window(self.paths.config_db, model_id=model.id, context_window=new_size)
        self._clear_selection()
        label = "1M" if new_size == 1_000_000 else "125K"
        hint = f"> Context window set to **{label}** for {channel.name} / {updated.name}"
        self._render_history_with_hint(
            hint,
            fallback_title="Context window",
            fallback_body=f"Context window set to **{label}** for {channel.name} / {updated.name}",
        )
        self._render_status_bar()

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
        self.query_one("#message-view", Markdown).update(f"## {title}\n\n{body}")

    def _render_history_with_hint(self, hint: str, *, fallback_title: str = "", fallback_body: str = "") -> bool:
        """Re-render conversation history with a transient hint appended. Falls back to _show_panel if no history."""
        if self.paths is not None and self.active_conversation_id is not None:
            history = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
            if history:
                lines: list[str] = []
                for msg in history:
                    if msg.role == "tool":
                        lines.append(f"**Tool**\n\n{self._message_to_display(msg)}")
                    elif msg.role == "system":
                        lines.append(f"**System**\n\n{self._message_to_display(msg)}")
                    else:
                        role_label = "**You**" if msg.role == "user" else "**Assistant**"
                        lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")
                lines.append(hint)
                self.query_one("#empty-state", Vertical).display = False
                self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
                self.query_one("#chat-area", Container).scroll_end(animate=False)
                return True
        self._show_panel(fallback_title, fallback_body)
        return False

    def _render_streaming_assistant(self) -> None:
        if not self._streaming_assistant_text:
            return
        if self.paths is None or self.active_conversation_id is None:
            return

        now = time.monotonic()
        if self._last_stream_render_at and now - self._last_stream_render_at < self._stream_render_interval:
            return
        self._last_stream_render_at = now

        history = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
        lines: list[str] = []
        for msg in history:
            if msg.role == "tool":
                lines.append(f"**Tool**\n\n{self._message_to_display(msg)}")
            elif msg.role == "system":
                lines.append(f"**System**\n\n{self._message_to_display(msg)}")
            else:
                role_label = "**You**" if msg.role == "user" else "**Assistant**"
                lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")

        lines.append(f"**Assistant**\n\n{self._streaming_assistant_text}")
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
        self.query_one("#chat-area", Container).scroll_end(animate=False)

    def _render_status_bar(self) -> None:
        if self.paths is None:
            return

        if self._compacting:
            self.query_one("#status-bar", Static).update("⏳ Compacting conversation history...")
            return

        primary = get_primary_llm_model(self.paths.config_db)
        if primary is None:
            self.query_one("#status-bar", Static).update("No model configured — use /api then /model")
            return

        channel, model = primary
        parts = [f"{channel.name} / {model.name}"]

        think_label = "ON" if model.thinking_enabled else "OFF"
        parts.append(f"Think: {think_label}")
        parts.append(f"Effort: {model.reasoning_effort}")
        ctx_label = "1M" if model.context_window >= 1_000_000 else f"{model.context_window // 1000}K"
        parts.append(f"Ctx: {ctx_label}")

        if self.active_conversation_id is not None:
            msgs = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
            parts.append(f"{len(msgs)} msgs")

            inp = self._last_input_tokens
            if inp or self._total_output_tokens:
                ctx = model.context_window
                if ctx and inp:
                    pct = (inp / ctx) * 100
                    parts.append(f"↑{inp} ↓{self._total_output_tokens} ({pct:.1f}%)")
                else:
                    parts.append(f"↑{inp} ↓{self._total_output_tokens}")
        else:
            parts.append("No conversation")

        self.query_one("#status-bar", Static).update("  |  ".join(parts))

    def _render_history(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            return

        history = list_messages(self.paths.chat_db, conversation_id=self.active_conversation_id)
        self.query_one("#empty-state", Vertical).display = False

        if not history:
            self.query_one("#message-view", Markdown).update("_No messages_")
            return

        lines: list[str] = []
        for msg in history:
            if msg.role == "tool":
                lines.append(f"**Tool**\n\n{self._message_to_display(msg)}")
            elif msg.role == "system":
                lines.append(f"**System**\n\n{self._message_to_display(msg)}")
            else:
                role_label = "**You**" if msg.role == "user" else "**Assistant**"
                lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")

        self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
        self.query_one("#chat-area", Container).scroll_end(animate=False)

    def _mask_api_key(self, api_key: str) -> str:
        if len(api_key) <= 6:
            return "configured"
        return f"{api_key[:3]}...{api_key[-2:]}"

def run() -> None:
    configure_logging()
    FlyinChatApp().run()
