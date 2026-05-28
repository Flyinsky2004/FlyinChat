import asyncio
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header, Input, Markdown, Static

from .compact import CompactionEngine, CompactionPolicy, TokenEstimator
from .file_mentions import MentionSpan, find_active_mention, workspace_path_suggestions
from .i18n import I18nStore, Language, TKey
from .logging_config import configure_logging
from .message_utils import message_to_api_format, message_to_display
from .models import LLMChannel, LLMModel
from .paths import AppPaths
from .prompt_assembler import mode_int_to_str
from .query_engine import QueryEngine, QueryEngineConfig, TurnEvent
from .skills import SkillRegistry
from .storage import (
    PROVIDER_PRESETS,
    add_message,
    create_channel_with_models,
    create_conversation,
    create_preset_channel,
    get_app_setting,
    get_conversation,
    get_primary_llm_model,
    initialize_storage,
    list_active_messages,
    list_conversations,
    list_llm_channels,
    list_llm_models,
    list_messages,
    load_mcp_config,
    set_app_setting,
    set_model_context_window,
    set_model_reasoning_effort,
    set_model_thinking,
    set_primary_llm_model,
)
from .mcp import MCPManager
from .tools import (
    AskUserQuestionTool,
    BashTool,
    EnterPlanModeTool,
    ExitPlanModeTool,
    FileEditTool,
    FileReadTool,
    FileWriteTool,
    GlobTool,
    GrepTool,
    PermissionContext,
    TodoWriteTool,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
    WebFetchTool,
    WebSearchTool,
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


class FlyinChatApp(App[None]):
    TITLE = "FlyinChat"
    SPINNER_FRAMES = ("|", "/", "—", "\\")

    def __init__(self, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.i18n = I18nStore()
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
        self._is_streaming = False
        self._spinner_frame = 0
        self._spinner_timer: object = None
        self._streaming_output_tokens = 0
        self._pending_permission_request_id: str | None = None
        self._pending_permission_tool_input: dict = {}
        self._pending_permission_tool_name: str = ""
        self._pending_user_input_request_id: str | None = None
        self._pending_user_input_questions: list[dict] = []
        self._pending_user_input_current_q: int = 0
        self._pending_user_input_answers: dict[int, str | list[str]] = {}
        self._pending_prompt: str | None = None
        self._streaming_assistant_text = ""
        self._last_stream_render_at = 0.0
        self._stream_render_interval = 0.05
        self._prompt_history: tuple[str, ...] = ()
        self._prompt_history_index: int | None = None
        self._prompt_history_draft = ""
        self._active_mention_span: MentionSpan | None = None
        self._mode: int = 0  # 0=normal, 1=auto_edit, 2=yolo, 3=plan
        self._mcp_manager: MCPManager | None = None
        self._skill_registry: SkillRegistry | None = None
        self._pending_mcp_action_server: str | None = None
        self._todos: list[dict] = []

    def _get_commands(self) -> tuple[SelectionItem, ...]:
        t = self.i18n.t
        return (
            SelectionItem("/api", t(TKey.CMD_API), t(TKey.CMD_API_DESC)),
            SelectionItem("/model", t(TKey.CMD_MODEL), t(TKey.CMD_MODEL_DESC)),
            SelectionItem("/thinking", t(TKey.CMD_THINKING), t(TKey.CMD_THINKING_DESC)),
            SelectionItem("/reasoning", t(TKey.CMD_REASONING), t(TKey.CMD_REASONING_DESC)),
            SelectionItem("/effort", t(TKey.CMD_EFFORT), t(TKey.CMD_EFFORT_DESC)),
            SelectionItem("/1M", t(TKey.CMD_1M), t(TKey.CMD_1M_DESC)),
            SelectionItem("/sessions", t(TKey.CMD_SESSIONS), t(TKey.CMD_SESSIONS_DESC)),
            SelectionItem("/clear", t(TKey.CMD_CLEAR), t(TKey.CMD_CLEAR_DESC)),
            SelectionItem("/compact", t(TKey.CMD_COMPACT), t(TKey.CMD_COMPACT_DESC)),
            SelectionItem("/language", t(TKey.CMD_LANGUAGE), t(TKey.CMD_LANGUAGE_DESC)),
            SelectionItem("/mcp", t(TKey.CMD_MCP), t(TKey.CMD_MCP_DESC)),
            SelectionItem("/skills", t(TKey.CMD_SKILLS), t(TKey.CMD_SKILLS_DESC)),
            SelectionItem("/init", t(TKey.CMD_INIT), t(TKey.CMD_INIT_DESC)),
        )

    def _get_reasoning_levels(self) -> tuple[SelectionItem, ...]:
        t = self.i18n.t
        return (
            SelectionItem("low", "low", t(TKey.REASONING_LOW)),
            SelectionItem("medium", "medium", t(TKey.REASONING_MED)),
            SelectionItem("high", "high", t(TKey.REASONING_HIGH)),
        )

    def _get_effort_levels(self) -> tuple[SelectionItem, ...]:
        t = self.i18n.t
        return (
            SelectionItem("low", "low", t(TKey.EFFORT_LOW)),
            SelectionItem("medium", "medium", t(TKey.EFFORT_MED)),
            SelectionItem("high", "high", t(TKey.EFFORT_HIGH)),
            SelectionItem("xhigh", "xhigh", t(TKey.EFFORT_XHIGH)),
        )

    def _get_api_actions(self) -> tuple[SelectionItem, ...]:
        t = self.i18n.t
        return (
            SelectionItem("deepseek", t(TKey.API_DEEPSEEK_TITLE), t(TKey.API_DEEPSEEK_DESC)),
            SelectionItem("openai", t(TKey.API_OPENAI_TITLE), t(TKey.API_OPENAI_DESC)),
            SelectionItem("anthropic", t(TKey.API_ANTHROPIC_TITLE), t(TKey.API_ANTHROPIC_DESC)),
        )

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

    #todo-panel {
        height: auto;
        max-height: 10;
        margin-bottom: 1;
        padding: 1 2;
        background: #101827;
        color: #d7dde8;
        border: round #2d4a3e;
        display: none;
    }

    #todo-panel .todo-title {
        color: #4ade80;
        text-style: bold;
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
        self._load_language()
        self._init_tools()

        t = self.i18n.t
        yield Header()
        with Container(id="chat-area"):
            with Vertical(id="empty-state"):
                yield Static(_EMPTY_LOGO, id="empty-logo")
                yield Static(t(TKey.EMPTY_HINT), id="empty-hint")
            yield Markdown("", id="message-view")
        with Vertical(id="composer"):
            yield Static("", id="todo-panel")
            yield Static("", id="command-menu")
            yield Static(t(TKey.LABEL_MESSAGE), id="input-label")
            yield Input(placeholder=t(TKey.PLACEHOLDER_INPUT), id="prompt-input")
            yield Static("", id="status-bar")
        yield Footer()

    def _load_language(self) -> None:
        if self.paths is None:
            return
        stored = get_app_setting(self.paths.config_path, "language")
        if stored is not None:
            try:
                self.i18n.set_language(Language(stored))
            except ValueError:
                pass

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()
        self._render_status_bar()
        self._init_mcp_servers()

    async def action_quit(self) -> None:
        if hasattr(self, "_mcp_shutdown_event") and self._mcp_shutdown_event is not None:
            self._mcp_shutdown_event.set()
        if self._mcp_manager is not None:
            await self._mcp_manager.shutdown()
        await super().action_quit()

    def _init_tools(self) -> None:
        workspace = self.paths.project_dir.parent if self.paths is not None else Path.cwd()
        permission = PermissionContext(
            allowed_tools={"file_read", "glob", "grep", "todo_write", "ask_user_question"},
            ask_tools={
                "file_write", "file_edit", "bash",
                "web_fetch", "web_search",
                "enter_plan_mode", "exit_plan_mode",
            },
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
        self._skill_registry = SkillRegistry(workspace)
        self._skill_registry.refresh()
        self._tool_registry = ToolRegistry()
        self._tool_registry.register(FileReadTool())
        self._tool_registry.register(FileWriteTool())
        self._tool_registry.register(FileEditTool())
        self._tool_registry.register(BashTool())
        self._tool_registry.register(GlobTool())
        self._tool_registry.register(GrepTool())
        self._tool_registry.register(WebFetchTool())
        self._tool_registry.register(WebSearchTool())
        self._tool_registry.register(AskUserQuestionTool())
        self._tool_registry.register(TodoWriteTool())
        self._tool_registry.register(EnterPlanModeTool())
        self._tool_registry.register(ExitPlanModeTool())
        self._tool_executor = ToolExecutor(self._tool_registry)
        self._apply_mode_permissions()
        if self._query_engine is not None:
            self._query_engine.configure_tools(
                self._tool_registry, self._tool_executor, self._tool_context
            )

    @work(exclusive=True)
    async def _init_mcp_servers(self) -> None:
        """Initialize MCP server connections in the background."""
        if self.paths is None or self._tool_registry is None or self._tool_context is None:
            return
        self._mcp_manager = MCPManager()
        mcp_config = load_mcp_config(self.paths)
        if mcp_config.servers:
            await self._mcp_manager.connect_all(
                mcp_config.servers,
                self._tool_registry,
                self._tool_context,
            )
        self.call_later(self._render_status_bar)
        # Keep the worker alive so anyio cancel scopes stay valid (Python 3.14 compat)
        self._mcp_shutdown_event = asyncio.Event()
        try:
            await self._mcp_shutdown_event.wait()
        except asyncio.CancelledError:
            pass

    def _ensure_query_engine(self) -> QueryEngine:
        if self._query_engine is None and self.paths is not None and self.active_conversation_id is not None:
            config = QueryEngineConfig(
                paths=self.paths,
                conversation_id=self.active_conversation_id,
                skill_registry=self._skill_registry,
            )
            self._query_engine = QueryEngine(config)
            self._query_engine.mode = mode_int_to_str(self._mode)
            if self._tool_registry is not None and self._tool_executor is not None and self._tool_context is not None:
                self._query_engine.configure_tools(
                    self._tool_registry, self._tool_executor, self._tool_context
                )
        if self._query_engine is None:
            raise RuntimeError("QueryEngine not initialized")
        return self._query_engine

    def _start_spinner(self) -> None:
        self._is_streaming = True
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.12, self._tick_spinner)
        self._render_status_bar()

    def _stop_spinner(self) -> None:
        self._is_streaming = False
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _request_cancel(self) -> None:
        if self._query_engine is not None:
            self._query_engine.request_cancel()

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        self._render_status_bar()
        self._scroll_chat_to_bottom()

    async def _handle_turn_event(self, event: TurnEvent) -> None:
        match event.event_type:
            case "turn_start":
                self._streaming_assistant_text = ""
                self._last_stream_render_at = 0.0
                self._streaming_output_tokens = 0
                self._todos = []
                self.query_one("#empty-state", Vertical).display = False
                self._render_todo_panel()
            case "thinking":
                pass
            case "text":
                self._streaming_assistant_text += event.data.get("content", "")
                self._streaming_output_tokens = max(1, len(self._streaming_assistant_text) // 4)
                self._render_streaming_assistant()
                self._render_status_bar()
            case "tool_use":
                pass
            case "tool_result":
                if event.data.get("name") == "todo_write":
                    self._refresh_todos_from_context()
            case "skill_resolved":
                self._render_history()
                self._render_status_bar()
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
                self._stop_spinner()
                self._render_history()
                self._render_status_bar()
                if event.data.get("cancelled") and self._pending_prompt is not None:
                    pending = self._pending_prompt
                    self._pending_prompt = None
                    self._submit_pending(pending)
            case "error":
                self._stop_spinner()
                if self._pending_prompt is not None:
                    pending = self._pending_prompt
                    self._pending_prompt = None
                    self._submit_pending(pending)
            case "permission_required":
                self._show_permission_request(event.data)
            case "user_input_required":
                self._show_user_input_form(event.data)

    @work
    async def _submit_via_engine(self, prompt: str) -> None:
        if self.paths is None:
            return
        engine = self._ensure_query_engine()
        result = await engine.submit_message(
            prompt, on_event=self._handle_turn_event, user_message_persisted=True
        )
        if result.status == "error" and result.error:
            self._stop_spinner()
            conv = get_conversation(self.paths.chat_path, conversation_id=self.active_conversation_id)
            if conv is not None:
                self._last_input_tokens = conv.last_input_tokens
                self._total_output_tokens = conv.total_output_tokens
            t = self.i18n.t
            history = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
            history_display = "\n\n---\n\n".join(
                f"**{t(TKey.LABEL_YOU) if msg.role == 'user' else t(TKey.LABEL_ASSISTANT)}**\n\n{self._message_to_display(msg)}"
                for msg in history
            )
            prefix = (history_display + "\n\n---\n\n") if history_display else ""
            self.query_one("#message-view", Markdown).update(
                f"{prefix}**{t(TKey.LABEL_ASSISTANT)}**\n\n{t(TKey.MISC_ERROR_PREFIX, error=result.error)}"
            )
            self._scroll_chat_to_bottom()
            self._render_status_bar()
            return
        self._render_history()
        self._render_status_bar()

    def _submit_pending(self, prompt: str) -> None:
        if self.paths is None or self.active_conversation_id is None:
            return
        add_message(
            self.paths.chat_path,
            conversation_id=self.active_conversation_id,
            role="user",
            content=prompt,
        )
        self._record_prompt_history(prompt)
        self._render_history()
        self._start_spinner()
        self._submit_via_engine(prompt)

    @staticmethod
    def _message_to_api_format(msg) -> dict | None:
        return message_to_api_format(msg)

    @staticmethod
    def _message_to_display(msg) -> str:
        return message_to_display(msg)

    def on_key(self, event: events.Key) -> None:
        if event.key == "shift+tab":
            event.prevent_default()
            self._mode = (self._mode + 1) % 4
            self._apply_mode_permissions()
            self._render_status_bar()
            return

        if event.key == "escape":
            if self._is_streaming:
                self._request_cancel()
                return
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
            if event.key == "a":
                event.prevent_default()
                self._resolve_pending_permission("always_approve")
                return
            if event.key == "n" or event.key == "escape":
                event.prevent_default()
                self._resolve_pending_permission("deny")
                return

        if self._pending_user_input_request_id:
            self._handle_user_input_key(event)
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
                if self.selection_context == "file_mention":
                    self._insert_selected_file_mention()
                    return
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
            self._active_mention_span = None
            self._show_command_menu(value)
            return

        cursor_position = getattr(event.input, "cursor_position", len(event.value))
        if self._show_file_mention_menu(event.value, cursor_position):
            return

        self.query_one("#command-menu", Static).display = False
        if self.selection_context in ("main", "file_mention"):
            self._clear_selection()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if self.paths is None:
            return

        if self.form_state is not None:
            self._submit_form_value(prompt, event.input)
            return

        if self.selection_context == "file_mention" and self.selection_items:
            self._activate_selection()
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

        if self._is_streaming:
            self._pending_prompt = prompt
            self._request_cancel()
            event.input.value = ""
            return

        if prompt.startswith("/"):
            self._run_command(prompt)
            event.input.value = ""
            self.query_one("#command-menu", Static).display = False
            return

        if self.active_conversation_id is None:
            conversation = create_conversation(self.paths.chat_path, title=prompt[:80])
            self.active_conversation_id = conversation.id
            self._last_usage = {}
            self._total_output_tokens = 0
            self._last_input_tokens = 0
            self._query_engine = None
            self._render_status_bar()

        self._clear_selection()
        if self.paths is not None and self.active_conversation_id is not None:
            add_message(
                self.paths.chat_path,
                conversation_id=self.active_conversation_id,
                role="user",
                content=prompt,
            )
            self._record_prompt_history(prompt)
            self._render_history()
        event.input.value = ""
        self._start_spinner()
        self._submit_via_engine(prompt)

    def _record_prompt_history(self, prompt: str) -> None:
        self._prompt_history = (*self._prompt_history, prompt)
        self._prompt_history_index = None
        self._prompt_history_draft = ""

    def _load_prompt_history(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            self._prompt_history = ()
        else:
            messages = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
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
            case "/effort":
                self._show_effort_settings()
            case "/1M":
                self._toggle_context_mode()
            case "/sessions":
                self._show_sessions()
            case "/clear":
                self._start_new_session()
            case "/compact":
                self._run_compact()
            case "/language":
                self._toggle_language()
            case "/init":
                self._run_init()
            case "/mcp":
                self._show_mcp_servers()
            case "/skills":
                self._show_skills()
            case _:
                self._show_panel(
                    self.i18n.t(TKey.PANEL_UNKNOWN_CMD),
                    self.i18n.t(TKey.PANEL_UNKNOWN_CMD_BODY, command=command),
                )

    def _show_skills(self) -> None:
        self._clear_selection()
        if self.paths is None:
            return
        workspace = self.paths.project_dir.parent
        if self._skill_registry is None:
            self._skill_registry = SkillRegistry(workspace)
        snapshot = self._skill_registry.refresh()
        rows: list[str] = []
        if snapshot.loaded_skills:
            rows.append(f"Loaded: {len(snapshot.loaded_skills)}")
            for skill in snapshot.loaded_skills:
                manifest = skill.manifest
                tags = ", ".join(manifest.tags) if manifest.tags else "-"
                rows.append(
                    f"- **{manifest.ref}** `{manifest.source}`\n"
                    f"  {manifest.description}\n"
                    f"  category: `{manifest.category}` · tags: `{tags}`\n"
                    f"  path: `{skill.path}`"
                )
        else:
            rows.append(self.i18n.t(TKey.PANEL_SKILLS_EMPTY))
        if snapshot.invalid_skills:
            rows.append(f"\nInvalid: {len(snapshot.invalid_skills)}")
            for invalid in snapshot.invalid_skills:
                rows.append(f"- `{invalid.path}`\n  {invalid.reason}")
        self._show_panel(self.i18n.t(TKey.PANEL_SKILLS), "\n\n".join(rows))

    def _toggle_language(self) -> None:
        new_lang = Language.ZH if self.i18n.language == Language.EN else Language.EN
        self.i18n.set_language(new_lang)
        if self.paths is not None:
            set_app_setting(self.paths.config_path, "language", new_lang.value)
        self._clear_selection()
        self._show_panel(
            self.i18n.t(TKey.CMD_LANGUAGE),
            self.i18n.t(TKey.HINT_LANGUAGE_SET),
        )
        self._render_status_bar()

    def _run_init(self) -> None:
        if self.paths is None:
            return

        if get_primary_llm_model(self.paths.config_path) is None:
            self._clear_selection()
            self._show_panel(
                self.i18n.t(TKey.PANEL_INIT_NO_MODEL),
                "",
            )
            return

        self._clear_selection()

        if self.active_conversation_id is None:
            conversation = create_conversation(self.paths.chat_path, title="/init")
            self.active_conversation_id = conversation.id
            self._last_usage = {}
            self._total_output_tokens = 0
            self._last_input_tokens = 0
            self._query_engine = None
            self._render_status_bar()

        t = self.i18n.t
        self._show_panel(t(TKey.PANEL_INIT), t(TKey.PANEL_INIT_BODY))

        prompt = t(TKey.INIT_PROMPT)
        add_message(
            self.paths.chat_path,
            conversation_id=self.active_conversation_id,
            role="user",
            content=prompt,
        )
        self._record_prompt_history(prompt)
        self._render_history()
        self._start_spinner()
        self._submit_via_engine(prompt)

    def _show_mcp_servers(self) -> None:
        """Show MCP server list in selection UI."""
        self._clear_selection()
        if self._mcp_manager is None:
            mcp_config = load_mcp_config(self.paths) if self.paths else None
            servers = mcp_config.servers if mcp_config else []
        else:
            mcp_status = self._mcp_manager.get_status()
            mcp_config = load_mcp_config(self.paths) if self.paths else None
            servers = mcp_config.servers if mcp_config else []

        if not servers:
            self._show_panel(
                self.i18n.t(TKey.CMD_MCP),
                self.i18n.t(TKey.PANEL_MCP_NO_SERVERS),
            )
            return

        status_map = self._mcp_manager.get_status() if self._mcp_manager else {}
        t = self.i18n.t

        def status_label(name: str) -> str:
            s = status_map.get(name, "")
            if s == "connected":
                return f"[{t(TKey.PANEL_MCP_STATUS_CONNECTED)}]"
            if s == "error":
                return f"[{t(TKey.PANEL_MCP_STATUS_ERROR)}]"
            if s == "connecting":
                return f"[{t(TKey.PANEL_MCP_STATUS_CONNECTING)}]"
            return f"[{t(TKey.PANEL_MCP_STATUS_DISCONNECTED)}]"

        items = tuple(
            SelectionItem(
                server.name,
                f"{server.name} {status_label(server.name)}",
                f"command: {server.command} {' '.join(server.args)}",
            )
            for server in servers
        )

        self._set_selection(
            context="mcp_select",
            title=t(TKey.SEL_MCP_TITLE),
            items=items,
            footer=t(TKey.SEL_MCP_FOOTER),
            target_menu=True,
        )
        self._force_command_menu_refresh()

    def _force_command_menu_refresh(self) -> None:
        """Force the command menu to refresh and display."""
        self.query_one("#command-menu", Static).display = False
        self.call_later(self._render_selection)

    def _show_mcp_detail(self, server_name: str) -> None:
        """Show detailed info for a specific MCP server."""
        self._clear_selection()
        if self._mcp_manager is None:
            self._show_panel(self.i18n.t(TKey.PANEL_MCP_DETAIL), "MCP manager not initialized.")
            return

        mcp_config = load_mcp_config(self.paths) if self.paths else None
        server = next(
            (s for s in (mcp_config.servers if mcp_config else []) if s.name == server_name),
            None,
        )
        if server is None:
            self._show_panel(self.i18n.t(TKey.PANEL_MCP_DETAIL), f"Server '{server_name}' not found.")
            return

        status_map = self._mcp_manager.get_status()
        status = status_map.get(server_name, "disconnected")
        t = self.i18n.t

        def status_text(s: str) -> str:
            if s == "connected":
                return t(TKey.PANEL_MCP_STATUS_CONNECTED)
            if s == "error":
                return t(TKey.PANEL_MCP_STATUS_ERROR)
            if s == "connecting":
                return t(TKey.PANEL_MCP_STATUS_CONNECTING)
            return t(TKey.PANEL_MCP_STATUS_DISCONNECTED)

        lines = [
            f"**Server:** {server.name}",
            f"**Status:** {status_text(status)}",
            f"**Transport:** {server.transport}",
            f"**Command:** {server.command}",
        ]
        if server.args:
            lines.append(f"**Args:** `{' '.join(server.args)}`")
        if server.env:
            env_str = ", ".join(f"{k}={v}" for k, v in server.env.items())
            lines.append(f"**Env:** {env_str}")
        lines.append(f"**Timeout:** {server.timeout_seconds}s")
        err_msg = self._mcp_manager.get_error(server_name) if self._mcp_manager else None
        if err_msg:
            lines.append("")
            lines.append(f"**Error:** ```{err_msg}```")

        tool_count = 0
        if self._tool_registry:
            mcp_tools = [
                tn for tn in self._tool_registry.list_tools()
                if tn.startswith(f"mcp_{server_name}_")
            ]
            tool_count = len(mcp_tools)
            if mcp_tools:
                lines.append("")
                lines.append(f"**Tools ({tool_count}):**")
                for tool_name in sorted(mcp_tools):
                    tool = self._tool_registry.get(tool_name)
                    lines.append(f"  - `{tool_name}` — {tool.description[:60]}")
            else:
                lines.append("")
                lines.append("**Tools:** None registered")

        lines.append("")
        lines.append(f"---")
        lines.append(f"*按 **Enter** 查看选项*")

        self._show_panel(t(TKey.PANEL_MCP_DETAIL), "\n".join(lines))
        self._pending_mcp_action_server = server_name
        self._set_selection(
            context="mcp_action",
            title=t(TKey.PANEL_MCP_ACTION_TITLE),
            items=(
                SelectionItem("reconnect", t(TKey.PANEL_MCP_RECONNECT), f"Reconnect {server_name}"),
                SelectionItem("back", t(TKey.PANEL_MCP_BACK), "Back to MCP list"),
            ),
        )
        command_menu = self.query_one("#command-menu", Static)
        command_menu.update("")
        command_menu.display = False
        self.call_later(self._render_selection)

    @work
    async def _mcp_reconnect(self, server_name: str) -> None:
        """Reconnect a single MCP server."""
        if self._mcp_manager is None or self.paths is None:
            return
        server = self._mcp_manager.get_server_config(server_name)
        if server is None:
            return
        t = self.i18n.t
        self._clear_selection()
        self._show_panel(t(TKey.PANEL_MCP_DETAIL), t(TKey.PANEL_MCP_RECONNECTING, name=server_name))
        try:
            tool_count = await self._mcp_manager.reconnect_server(
                server, self._tool_registry, self._tool_context
            )
            self._show_panel(
                t(TKey.PANEL_MCP_DETAIL),
                t(TKey.PANEL_MCP_RECONNECT_OK, count=tool_count),
            )
        except Exception:
            self._show_panel(t(TKey.PANEL_MCP_DETAIL), f"Reconnect failed for {server_name}")
        self.call_later(self._render_status_bar)

    def _show_command_menu(self, query: str) -> None:
        command_menu = self.query_one("#command-menu", Static)
        matches = tuple(command for command in self._get_commands() if command.key.startswith(query))
        if not matches:
            self._clear_selection()
            command_menu.update(self.i18n.t(TKey.CMENU_NO_MATCHES))
            command_menu.display = True
            return

        self._set_selection(
            context="main",
            title=self.i18n.t(TKey.CMENU_COMMANDS),
            items=matches,
            footer=self.i18n.t(TKey.CMENU_FOOTER),
            target_menu=True,
        )

    def _show_file_mention_menu(self, value: str, cursor_position: int) -> bool:
        if self.paths is None:
            return False

        span = find_active_mention(value, cursor_position)
        if span is None:
            self._active_mention_span = None
            return False

        self._active_mention_span = span
        suggestions = workspace_path_suggestions(self.paths.project_dir.parent, span.query)
        command_menu = self.query_one("#command-menu", Static)
        if not suggestions:
            self.selection_context = "file_mention"
            self.selection_title = self.i18n.t(TKey.FILE_MENTION_TITLE)
            self.selection_header = ""
            self.selection_footer = ""
            self.selection_items = ()
            self.selected_index = 0
            command_menu.update(self.i18n.t(TKey.FILE_MENTION_NO_MATCHES, query=span.query))
            command_menu.display = True
            return True

        items = tuple(
            SelectionItem(
                suggestion.path,
                f"{suggestion.path}/" if suggestion.is_dir else suggestion.path,
                self.i18n.t(TKey.FILE_MENTION_DIR if suggestion.is_dir else TKey.FILE_MENTION_FILE),
            )
            for suggestion in suggestions
        )
        self._set_selection(
            context="file_mention",
            title=self.i18n.t(TKey.FILE_MENTION_TITLE),
            items=items,
            footer=self.i18n.t(TKey.FILE_MENTION_FOOTER),
            target_menu=True,
        )
        return True

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
            case "effort_select":
                self._set_effort(item.key)
            case "file_mention":
                self._insert_selected_file_mention()
            case "session_select":
                self.active_conversation_id = item.key
                conv = get_conversation(self.paths.chat_path, conversation_id=item.key)
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
            case "mcp_select":
                self._show_mcp_detail(item.key)
            case "mcp_action":
                if item.key == "reconnect":
                    self._mcp_reconnect(self._pending_mcp_action_server or "")
                elif item.key == "back":
                    self._show_mcp_servers()

    def _insert_selected_file_mention(self) -> None:
        if not self.selection_items:
            return

        prompt_input = self.query_one("#prompt-input", Input)
        cursor_position = getattr(prompt_input, "cursor_position", len(prompt_input.value))
        span = find_active_mention(prompt_input.value, cursor_position) or self._active_mention_span
        if span is None:
            self._clear_selection()
            return

        selected_path = self.selection_items[self.selected_index].key
        suffix = prompt_input.value[span.end :]
        separator = "" if suffix[:1].isspace() else " "
        replacement = f"{selected_path}{separator}"
        new_value = f"{prompt_input.value[:span.start]}{replacement}{suffix}"
        new_cursor = span.start + len(replacement)
        self._suppress_menu_update = True
        prompt_input.value = new_value
        prompt_input.cursor_position = new_cursor
        self._active_mention_span = None
        self._clear_selection()

    def _show_permission_request(self, data: dict) -> None:
        tool_name = data.get("tool_name", "unknown")
        risk_level = data.get("risk_level", "medium")
        args_preview = data.get("args_preview", "")
        reason = data.get("reason", "")
        request_id = data.get("request_id", "")
        tool_input = data.get("tool_input", {})

        self._pending_permission_request_id = request_id
        self._pending_permission_tool_input = tool_input
        self._pending_permission_tool_name = tool_name

        t = self.i18n.t
        risk_labels = {"low": t(TKey.RISK_LOW), "medium": t(TKey.RISK_MEDIUM), "high": t(TKey.RISK_HIGH)}
        risk_badge = risk_labels.get(risk_level, risk_level.upper())
        hint = t(
            TKey.PERM_TITLE,
            tool=tool_name,
            risk=risk_badge,
            args=args_preview,
            reason=reason,
        )
        if not self._render_history_with_hint(hint, fallback_title=t(TKey.PERM_LABEL), fallback_body=hint):
            self._show_panel(t(TKey.PERM_LABEL), hint)

        self._set_input_prompt(t(TKey.PERM_LABEL), t(TKey.PERM_PLACEHOLDER))

        items = (
            SelectionItem("approve", t(TKey.PERM_APPROVE), ""),
            SelectionItem("always_approve", t(TKey.PERM_ALWAYS_APPROVE), ""),
            SelectionItem("deny", t(TKey.PERM_DENY), ""),
        )
        self._set_selection(
            context="permission_request",
            title=t(TKey.PERM_ACTION_TITLE),
            items=items,
            footer=t(TKey.PERM_ACTION_FOOTER),
            target_menu=True,
        )

    def _show_user_input_form(self, data: dict) -> None:
        request_id = data.get("request_id", "")
        questions = data.get("questions", [])

        self._pending_user_input_request_id = request_id
        self._pending_user_input_questions = questions
        self._pending_user_input_current_q = 0
        self._pending_user_input_answers = {}

        if not questions:
            self._resolve_pending_user_input({"_empty": True})
            return

        self._render_user_input_question()

    def _render_user_input_question(self) -> None:
        if not self._pending_user_input_questions:
            return

        q_idx = self._pending_user_input_current_q
        if q_idx >= len(self._pending_user_input_questions):
            self._resolve_pending_user_input(self._pending_user_input_answers)
            return

        q = self._pending_user_input_questions[q_idx]
        question_text = q.get("question", "")
        header = q.get("header", "")
        options = q.get("options", [])
        multi = q.get("multiSelect", False)

        t = self.i18n.t
        lines = [
            f"[{header}] {question_text}",
            f"({q_idx + 1}/{len(self._pending_user_input_questions)})",
            "",
        ]
        for i, opt in enumerate(options):
            label = opt.get("label", "")
            desc = opt.get("description", "")
            marker = "> " if i == 0 else "  "
            prev_answer = self._pending_user_input_answers.get(q_idx)
            if multi and isinstance(prev_answer, list) and label in prev_answer:
                marker = "[x] "
            elif not multi and isinstance(prev_answer, str) and prev_answer == label:
                marker = "(*) "
            elif not multi and i == 0 and prev_answer is None:
                marker = "(*) "
            lines.append(f"{marker}{label} — {desc}")

        if multi:
            lines.append("")
            lines.append("Space=toggle  Enter=confirm selection  →=next  ←=prev")
        else:
            lines.append("")
            lines.append("↑↓=navigate  Enter=select  ←=prev")

        questions_display = "\n".join(lines)
        self.query_one("#command-menu", Static).update(questions_display)
        self.query_one("#command-menu", Static).display = True

    def _resolve_pending_user_input(self, answers: dict) -> None:
        engine = self._query_engine
        if engine is not None and self._pending_user_input_request_id:
            engine.resolve_user_input(self._pending_user_input_request_id, answers)
        self._pending_user_input_request_id = None
        self._pending_user_input_questions = []
        self._pending_user_input_current_q = 0
        self._pending_user_input_answers = {}
        self.query_one("#command-menu", Static).display = False
        t = self.i18n.t
        self._set_input_prompt(t(TKey.LABEL_MESSAGE), t(TKey.PLACEHOLDER_INPUT))

    def _handle_user_input_key(self, event: events.Key) -> None:
        if not self._pending_user_input_questions:
            return

        q_idx = self._pending_user_input_current_q
        if q_idx >= len(self._pending_user_input_questions):
            return

        q = self._pending_user_input_questions[q_idx]
        options = q.get("options", [])
        multi = q.get("multiSelect", False)

        if event.key == "escape":
            event.prevent_default()
            self._resolve_pending_user_input({"_cancelled": True})
            return

        if event.key == "left":
            event.prevent_default()
            if q_idx > 0:
                self._pending_user_input_current_q -= 1
                self._render_user_input_question()
            return

        if event.key == "right" or event.key == "enter":
            event.prevent_default()
            if multi:
                selected = self._pending_user_input_answers.get(q_idx, [])
                if not isinstance(selected, list):
                    selected = []
                if options and not selected:
                    selected = [options[0]["label"]]
                if selected:
                    self._pending_user_input_answers[q_idx] = selected
                if q_idx + 1 >= len(self._pending_user_input_questions):
                    self._resolve_pending_user_input(self._pending_user_input_answers)
                else:
                    self._pending_user_input_current_q += 1
                    self._render_user_input_question()
            else:
                if options:
                    label = options[0]["label"]
                    # find currently selected by marker
                    for i, opt in enumerate(options):
                        prev = self._pending_user_input_answers.get(q_idx)
                        if isinstance(prev, str) and prev == opt["label"]:
                            label = opt["label"]
                            break
                        if prev is None and i == 0:
                            label = opt["label"]
                    self._pending_user_input_answers[q_idx] = label
                if q_idx + 1 >= len(self._pending_user_input_questions):
                    self._resolve_pending_user_input(self._pending_user_input_answers)
                else:
                    self._pending_user_input_current_q += 1
                    self._render_user_input_question()
            return

        if event.key == "up":
            event.prevent_default()
            if multi:
                self._toggle_multi_option(-1)
            else:
                self._navigate_single_option(-1)
            return

        if event.key == "down":
            event.prevent_default()
            if multi:
                self._toggle_multi_option(1)
            else:
                self._navigate_single_option(1)
            return

        if event.key == "space":
            event.prevent_default()
            if multi:
                self._toggle_multi_select()
            return

    def _navigate_single_option(self, direction: int) -> None:
        q_idx = self._pending_user_input_current_q
        q = self._pending_user_input_questions[q_idx]
        options = q.get("options", [])
        if not options:
            return

        current = self._pending_user_input_answers.get(q_idx)
        if isinstance(current, list):
            current = None
        try:
            current_idx = next(i for i, o in enumerate(options) if o["label"] == current)
        except StopIteration:
            current_idx = 0 if direction > 0 else -1

        new_idx = (current_idx + direction) % len(options)
        self._pending_user_input_answers[q_idx] = options[new_idx]["label"]
        self._render_user_input_question()

    def _toggle_multi_option(self, direction: int) -> None:
        q_idx = self._pending_user_input_current_q
        q = self._pending_user_input_questions[q_idx]
        options = q.get("options", [])
        if not options:
            return

        current = self._pending_user_input_answers.get(q_idx, [])
        if not isinstance(current, list):
            current = []

        cursor_label = getattr(self, "_multi_cursor_label", options[0]["label"])
        try:
            cursor_idx = next(i for i, o in enumerate(options) if o["label"] == cursor_label)
        except StopIteration:
            cursor_idx = 0

        new_idx = (cursor_idx + direction) % len(options)
        self._multi_cursor_label = options[new_idx]["label"]
        self._render_user_input_question()

    def _toggle_multi_select(self) -> None:
        q_idx = self._pending_user_input_current_q
        q = self._pending_user_input_questions[q_idx]
        options = q.get("options", [])

        cursor_label = getattr(self, "_multi_cursor_label", options[0]["label"] if options else "")
        selected = self._pending_user_input_answers.get(q_idx, [])
        if not isinstance(selected, list):
            selected = []

        if cursor_label in selected:
            selected.remove(cursor_label)
        else:
            selected.append(cursor_label)
        self._pending_user_input_answers[q_idx] = selected
        self._render_user_input_question()

    def _resolve_pending_permission(self, resolution: str) -> None:
        engine = self._query_engine
        if engine is not None and self._pending_permission_request_id:
            if resolution == "always_approve":
                tool_name = getattr(self, "_pending_permission_tool_name", "")
                tool_input = getattr(self, "_pending_permission_tool_input", {})
                if self._tool_executor is not None:
                    if tool_name.startswith("mcp_"):
                        # MCP tool: auto-allow by tool name
                        self._tool_executor.add_auto_allow_tool(tool_name)
                    else:
                        # Bash / native tools: extract command prefix
                        cmd = tool_input.get("command", "").strip()
                        if cmd:
                            try:
                                parts = shlex.split(cmd)
                            except ValueError:
                                parts = cmd.split()
                            if parts:
                                if len(parts) >= 2 and parts[0] == "git":
                                    pattern = f"{parts[0]} {parts[1]}"
                                else:
                                    pattern = parts[0]
                                self._tool_executor.add_command_to_allowlist(pattern)
            engine.resolve_permission(self._pending_permission_request_id, resolution)
        self._pending_permission_request_id = None
        self._clear_selection()
        self.query_one("#command-menu", Static).display = False
        t = self.i18n.t
        self._set_input_prompt(t(TKey.LABEL_MESSAGE), t(TKey.PLACEHOLDER_INPUT))
        self._render_history()

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
                    self.paths.config_path,
                    preset_id="deepseek",
                    api_key=parts[3],
                )
            elif channel_type == "openai":
                if len(parts) != 7:
                    raise ValueError("Usage: /api add openai <name> <base-url> <api-key> <model1,model2>")
                channel, models = create_channel_with_models(
                    self.paths.config_path,
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
                    self.paths.config_path,
                    name=parts[3],
                    provider_type="anthropic",
                    api_key=parts[4],
                    model_names=parts[5].split(","),
                )
            else:
                raise ValueError("Supported channel types: deepseek, openai, anthropic")
        except ValueError as error:
            self._clear_selection()
            self._show_panel(self.i18n.t(TKey.PANEL_API_SETUP_ERR), str(error))
            return

        self._clear_selection()
        self._show_channel_added(channel, models)

    def _show_api_settings(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        channels = list_llm_channels(self.paths.config_path)
        header = t(TKey.SEL_API_HEADER, channels=self._format_channels(channels), presets="\n".join(self._format_presets()))
        self._set_selection(
            context="api_actions",
            title=t(TKey.SEL_API_TITLE),
            items=self._get_api_actions(),
            header=header,
            footer=t(TKey.SEL_API_FOOTER),
        )

    def _show_model_settings(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        channels = list_llm_channels(self.paths.config_path)
        if not channels:
            self._clear_selection()
            self._show_panel(t(TKey.PANEL_PRIMARY_MODEL), t(TKey.PANEL_NO_PROVIDERS))
            return

        primary = get_primary_llm_model(self.paths.config_path)
        rows = [t(TKey.SEL_MODEL_HEADER)]
        items: list[SelectionItem] = []
        for channel_index, channel in enumerate(channels, start=1):
            models = list_llm_models(self.paths.config_path, channel_id=channel.id)
            rows.append(f"{channel_index}. {channel.name} · {channel.provider_type}")
            for model_index, model in enumerate(models, start=1):
                rows.append(self._format_model_row(channel_index, model_index, model, primary))
                items.append(SelectionItem(model.id, f"{channel.name} / {model.name}", t(TKey.CMD_MODEL_DESC)))

        self._set_selection(
            context="model_select",
            title=t(TKey.SEL_MODEL_TITLE),
            items=tuple(items),
            header="\n".join(rows),
            footer=t(TKey.SEL_MODEL_FOOTER),
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
            channels = list_llm_channels(self.paths.config_path)
            channel = channels[channel_index]
            models = list_llm_models(self.paths.config_path, channel_id=channel.id)
            model = models[model_index]
            selected_channel, selected_model = set_primary_llm_model(self.paths.config_path, model_id=model.id)
        except (IndexError, ValueError):
            self._clear_selection()
            self._show_panel(self.i18n.t(TKey.PANEL_MODEL_SELECT_ERR), self.i18n.t(TKey.PANEL_MODEL_SELECT_USAGE))
            return

        self._clear_selection()
        self._show_primary_model_selected(selected_channel, selected_model)

    def _show_sessions(self) -> None:
        if self.paths is None:
            return

        conversations = list_conversations(self.paths.chat_path)
        if not conversations:
            self._clear_selection()
            self._show_panel(self.i18n.t(TKey.PANEL_SESSION_HISTORY), self.i18n.t(TKey.PANEL_NO_SESSIONS))
            return

        items = tuple(
            SelectionItem(conversation.id, conversation.title, conversation.updated_at)
            for conversation in conversations
        )
        self._set_selection(
            context="session_select",
            title=self.i18n.t(TKey.SEL_SESSION_TITLE),
            items=items,
            footer=self.i18n.t(TKey.SEL_SESSION_FOOTER),
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
        self._show_panel(self.i18n.t(TKey.PANEL_NEW_SESSION), self.i18n.t(TKey.PANEL_NEW_SESSION_BODY))
        self._render_status_bar()

    @work
    async def _run_compact(self) -> None:
        t = self.i18n.t
        if self.paths is None or self.active_conversation_id is None:
            self._show_panel(t(TKey.PANEL_COMPACT), t(TKey.PANEL_NO_CONVERSATION))
            return

        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._show_panel(t(TKey.PANEL_COMPACT), t(TKey.PANEL_NO_MODEL))
            return

        channel, model = primary
        all_messages = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
        active_messages = list_active_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
        already_compacted = len(active_messages) < len(all_messages)

        policy = CompactionPolicy.from_model(model)
        estimator = TokenEstimator()
        estimated = estimator.estimate_messages(active_messages)

        if already_compacted and estimated <= policy.soft_limit:
            self._clear_selection()
            self._show_panel(
                t(TKey.PANEL_COMPACT),
                t(TKey.PANEL_COMPACT_OK, tokens=estimated // 1000, limit=policy.soft_limit // 1000),
            )
            return

        api_messages = [
            formatted for msg in active_messages
            if (formatted := self._message_to_api_format(msg)) is not None
        ]

        engine = CompactionEngine(
            self.paths.chat_path,
            self.active_conversation_id,
            _i18n=self.i18n,
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
                t(TKey.PANEL_COMPACT_DONE),
                f"Strategy: {result.strategy}\nTokens: {before_k}K → {after_k}K",
            )
            self._render_history()
            self._render_status_bar()
        else:
            self._show_panel(
                t(TKey.PANEL_COMPACT),
                t(TKey.PANEL_COMPACT_NOT_NEEDED),
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
            self._show_panel(self.i18n.t(TKey.PANEL_INPUT_REQUIRED), self.i18n.t(TKey.PANEL_INPUT_PROMPT))
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
                channel, models = create_preset_channel(self.paths.config_path, preset_id="deepseek", api_key=values[0])
            elif self.form_state.kind == "openai":
                channel, models = create_channel_with_models(
                    self.paths.config_path,
                    name=values[0],
                    provider_type="openai_compatible",
                    base_url=values[1],
                    api_key=values[2],
                    model_names=values[3].split(","),
                )
            elif self.form_state.kind == "anthropic":
                channel, models = create_channel_with_models(
                    self.paths.config_path,
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
            t = self.i18n.t
            self._set_input_prompt(t(TKey.LABEL_MESSAGE), t(TKey.PLACEHOLDER_INPUT))
            self._show_panel(self.i18n.t(TKey.PANEL_API_SETUP_ERR), str(error))
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
            self.i18n.t(TKey.PANEL_ADD_API),
            self.i18n.t(TKey.FORM_STEP, step=self.form_state.step + 1, total=len(fields), field=field),
        )

    def _api_form_fields(self, kind: str) -> tuple[str, ...]:
        t = self.i18n.t
        match kind:
            case "deepseek":
                return (t(TKey.FORM_DEEPSEEK_KEY),)
            case "openai":
                return (t(TKey.FORM_OPENAI_NAME), t(TKey.FORM_OPENAI_URL), t(TKey.FORM_OPENAI_KEY), t(TKey.FORM_OPENAI_MODELS))
            case "anthropic":
                return (t(TKey.FORM_ANTHROPIC_NAME), t(TKey.FORM_ANTHROPIC_KEY), t(TKey.FORM_ANTHROPIC_MODELS))
            case _:
                return ()

    def _api_form_title(self, kind: str) -> str:
        t = self.i18n.t
        match kind:
            case "deepseek":
                return t(TKey.FORM_DEEPSEEK_TITLE)
            case "openai":
                return t(TKey.FORM_OPENAI_TITLE)
            case "anthropic":
                return t(TKey.FORM_ANTHROPIC_TITLE)
            case _:
                return "API channel"

    def _set_primary_model_by_id(self, model_id: str) -> None:
        if self.paths is None:
            return

        selected_channel, selected_model = set_primary_llm_model(self.paths.config_path, model_id=model_id)
        self._clear_selection()
        self._show_primary_model_selected(selected_channel, selected_model)

    def _show_channel_added(self, channel: LLMChannel, models: list[LLMModel]) -> None:
        model_names = ", ".join(model.name for model in models)
        self._show_panel(
            self.i18n.t(TKey.PANEL_API_CHANNEL_ADDED),
            f"{channel.name}\n{channel.provider_type}\n{channel.base_url or self.i18n.t(TKey.MISC_DEFAULT_ENDPOINT)}\nmodels: {model_names}",
        )

    def _show_primary_model_selected(self, channel: LLMChannel, model: LLMModel) -> None:
        self._last_usage = {}
        t = self.i18n.t
        hint = t(TKey.HINT_PRIMARY_MODEL, channel=channel.name, model=model.name)
        self._render_history_with_hint(
            hint,
            fallback_title=t(TKey.PANEL_PRIMARY_MODEL),
            fallback_body=f"{channel.name}\n{model.name}",
        )
        self._render_status_bar()

    def _show_thinking_settings(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            self._show_panel(t(TKey.PANEL_THINKING_MODE), t(TKey.PANEL_THINKING_NO_MODEL))
            return

        channel, model = primary
        status = "enabled" if model.thinking_enabled else "disabled"
        options = (
            SelectionItem("on", t(TKey.SEL_THINKING_ON), t(TKey.SEL_THINKING_ON_DESC)),
            SelectionItem("off", t(TKey.SEL_THINKING_OFF), t(TKey.SEL_THINKING_OFF_DESC)),
        )
        self._set_selection(
            context="thinking_toggle",
            title=t(TKey.SEL_THINKING_TITLE),
            items=options,
            header=f"{channel.name} / {model.name}\nThinking is currently {status}",
            footer=t(TKey.SEL_THINKING_FOOTER),
        )

    def _toggle_thinking(self, action: str) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            return

        model = primary[1]
        enabled = action == "on"
        updated = set_model_thinking(self.paths.config_path, model_id=model.id, enabled=enabled)
        self._clear_selection()
        t = self.i18n.t
        channel = primary[0].name
        if updated.thinking_enabled:
            hint = t(TKey.HINT_THINKING_ON, channel=channel, model=updated.name)
        else:
            hint = t(TKey.HINT_THINKING_OFF, channel=channel, model=updated.name)
        self._render_history_with_hint(hint, fallback_title=t(TKey.PANEL_THINKING_MODE), fallback_body=hint.lstrip("> "))
        self._render_status_bar()

    def _show_reasoning_settings(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            self._show_panel(t(TKey.PANEL_REASONING_EFFORT), t(TKey.PANEL_REASONING_NO_MODEL))
            return

        channel, model = primary
        self._set_selection(
            context="reasoning_select",
            title=t(TKey.SEL_REASONING_TITLE),
            items=self._get_reasoning_levels(),
            header=f"{channel.name} / {model.name}\nCurrent level: {model.reasoning_effort}",
            footer=t(TKey.SEL_REASONING_FOOTER),
        )

    def _set_reasoning_effort(self, level: str) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            return

        model = primary[1]
        updated = set_model_reasoning_effort(self.paths.config_path, model_id=model.id, effort=level)
        self._clear_selection()
        t = self.i18n.t
        hint = t(TKey.HINT_REASONING_SET, effort=updated.reasoning_effort, channel=primary[0].name, model=updated.name)
        self._render_history_with_hint(
            hint,
            fallback_title=t(TKey.PANEL_REASONING_EFFORT),
            fallback_body=f"Level set to **{updated.reasoning_effort}** for {primary[0].name} / {updated.name}",
        )
        self._render_status_bar()

    def _show_effort_settings(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            self._show_panel(t(TKey.PANEL_EFFORT_LEVEL), t(TKey.PANEL_EFFORT_NO_MODEL))
            return

        channel, model = primary
        if model.thinking_enabled:
            current = f"think: on, effort: {model.reasoning_effort}"
        else:
            current = "think: off (low)"

        self._set_selection(
            context="effort_select",
            title=t(TKey.SEL_EFFORT_TITLE),
            items=self._get_effort_levels(),
            header=f"{channel.name} / {model.name}\nCurrent: {current}",
            footer=t(TKey.SEL_EFFORT_FOOTER),
        )

    def _set_effort(self, level: str) -> None:
        if self.paths is None:
            return

        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            return

        model = primary[1]
        if level == "low":
            updated = set_model_thinking(self.paths.config_path, model_id=model.id, enabled=False)
        else:
            updated = set_model_thinking(self.paths.config_path, model_id=model.id, enabled=True)
            updated = set_model_reasoning_effort(self.paths.config_path, model_id=model.id, effort=level)
        self._clear_selection()
        t = self.i18n.t
        if updated.thinking_enabled:
            hint = t(TKey.HINT_EFFORT_ON, effort=updated.reasoning_effort, channel=primary[0].name, model=updated.name)
        else:
            hint = t(TKey.HINT_EFFORT_OFF, channel=primary[0].name, model=updated.name)
        self._render_history_with_hint(
            hint,
            fallback_title=t(TKey.PANEL_EFFORT_LEVEL),
            fallback_body=hint.lstrip("> "),
        )
        self._render_status_bar()

    def _toggle_context_mode(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            self._clear_selection()
            self._show_panel(t(TKey.PANEL_CTX_WINDOW), t(TKey.PANEL_CTX_NO_MODEL))
            return

        channel, model = primary
        new_size = 125_000 if model.context_window >= 1_000_000 else 1_000_000
        updated = set_model_context_window(self.paths.config_path, model_id=model.id, context_window=new_size)
        self._clear_selection()
        label = "1M" if new_size == 1_000_000 else "125K"
        hint = t(TKey.HINT_CTX_SET, label=label, channel=channel.name, model=updated.name)
        self._render_history_with_hint(
            hint,
            fallback_title=t(TKey.PANEL_CTX_WINDOW),
            fallback_body=f"Context window set to **{label}** for {channel.name} / {updated.name}",
        )
        self._render_status_bar()

    def _format_channels(self, channels: list[LLMChannel]) -> str:
        t = self.i18n.t
        if self.paths is None:
            return t(TKey.MISC_NO_PROVIDERS)
        if not channels:
            return t(TKey.MISC_NO_PROVIDERS_ADD)

        rows: list[str] = []
        for index, channel in enumerate(channels, start=1):
            models = list_llm_models(self.paths.config_path, channel_id=channel.id)
            model_names = ", ".join(model.name for model in models) or t(TKey.MISC_NO_MODELS)
            endpoint = channel.base_url or t(TKey.MISC_DEFAULT_ENDPOINT)
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
        marker = self.i18n.t(TKey.MISC_PRIMARY_MARKER) if primary is not None and primary[1].id == model.id else ""
        return self.i18n.t(TKey.MISC_MODEL_ROW, ci=channel_index, mi=model_index, name=model.name, marker=marker)

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
        if target_menu or self.selection_context in ("main", "file_mention", "permission_request", "mcp_action"):
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
        self._active_mention_span = None
        self.query_one("#command-menu", Static).display = False

    def _clear_input(self) -> None:
        self.query_one("#prompt-input", Input).clear()

    def _reset_selection(self) -> None:
        self._clear_selection()
        t = self.i18n.t
        self._set_input_prompt(t(TKey.LABEL_MESSAGE), t(TKey.PLACEHOLDER_INPUT))

    def _set_input_prompt(self, label: str, placeholder: str) -> None:
        self.query_one("#input-label", Static).update(label)
        self.query_one("#prompt-input", Input).placeholder = placeholder

    def _show_panel(self, title: str, body: str) -> None:
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Markdown).update(f"## {title}\n\n{body}")
        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self) -> None:
        def scroll_end() -> None:
            try:
                self.query_one("#chat-area", Container).scroll_end(animate=False)
            except NoMatches:
                return

        self.call_after_refresh(scroll_end)
        self.set_timer(0.08, scroll_end)

    def _render_history_with_hint(self, hint: str, *, fallback_title: str = "", fallback_body: str = "") -> bool:
        """Re-render conversation history with a transient hint appended. Falls back to _show_panel if no history."""
        if self.paths is not None and self.active_conversation_id is not None:
            history = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
            if history:
                t = self.i18n.t
                lines: list[str] = []
                for msg in history:
                    if msg.role == "tool":
                        lines.append(f"**{t(TKey.LABEL_TOOL)}**\n\n{self._message_to_display(msg)}")
                    elif msg.role == "system":
                        lines.append(f"**{t(TKey.LABEL_SYSTEM)}**\n\n{self._message_to_display(msg)}")
                    else:
                        role_label = f"**{t(TKey.LABEL_YOU)}**" if msg.role == "user" else f"**{t(TKey.LABEL_ASSISTANT)}**"
                        lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")
                lines.append(hint)
                self.query_one("#empty-state", Vertical).display = False
                self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
                self._scroll_chat_to_bottom()
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

        t = self.i18n.t
        history = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
        lines: list[str] = []
        for msg in history:
            if msg.role == "tool":
                lines.append(f"**{t(TKey.LABEL_TOOL)}**\n\n{self._message_to_display(msg)}")
            elif msg.role == "system":
                lines.append(f"**{t(TKey.LABEL_SYSTEM)}**\n\n{self._message_to_display(msg)}")
            else:
                role_label = f"**{t(TKey.LABEL_YOU)}**" if msg.role == "user" else f"**{t(TKey.LABEL_ASSISTANT)}**"
                lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")

        lines.append(f"**{t(TKey.LABEL_ASSISTANT)}**\n\n{self._streaming_assistant_text}")
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
        self._scroll_chat_to_bottom()

    def _mode_label(self) -> str:
        """Rich markup label for the current mode."""
        mode_keys: dict[int, tuple[str, str]] = {
            0: ("normal", "#7dd3fc"),
            1: ("auto_edit", "#fbbf24"),
            2: ("yolo", "bold #dc2626"),
            3: ("plan", "#60a5fa"),
        }
        i18n_keys = {
            0: TKey.STATUS_MODE_NORMAL,
            1: TKey.STATUS_MODE_AUTO_EDIT,
            2: TKey.STATUS_MODE_YOLO,
            3: TKey.STATUS_MODE_PLAN,
        }
        key = i18n_keys[self._mode]
        _, color = mode_keys[self._mode]
        label = self.i18n.t(key)
        return f"[{color}]{label}[/{color}]"

    def _apply_mode_permissions(self) -> None:
        """Update tool permissions based on current mode."""
        if self._tool_context is None:
            return
        p = self._tool_context.permission
        if self._mode == 0:  # normal
            p.allowed_tools = {
                "file_read", "glob", "grep",
                "todo_write", "ask_user_question",
            }
            p.ask_tools = {
                "file_write", "file_edit", "bash",
                "web_fetch", "web_search",
                "enter_plan_mode", "exit_plan_mode",
            }
            p.denied_tools = set()
        elif self._mode == 1:  # auto_edit
            p.allowed_tools = {
                "file_read", "file_write", "file_edit",
                "glob", "grep", "todo_write", "ask_user_question",
            }
            p.ask_tools = {
                "bash", "web_fetch", "web_search",
                "enter_plan_mode", "exit_plan_mode",
            }
            p.denied_tools = set()
        elif self._mode == 2:  # yolo
            p.allowed_tools = None
            p.ask_tools = set()
            p.denied_tools = set()
        elif self._mode == 3:  # plan
            p.allowed_tools = {
                "file_read", "glob", "grep",
                "todo_write", "ask_user_question",
                "enter_plan_mode", "exit_plan_mode",
            }
            p.ask_tools = {"bash", "web_fetch", "web_search"}
            p.denied_tools = {"file_write", "file_edit"}
        if self._query_engine is not None:
            self._query_engine.mode = mode_int_to_str(self._mode)

    def _refresh_todos_from_context(self) -> None:
        if self._tool_context is None:
            return
        todos = self._tool_context.turn_state.get("todos")
        if not todos:
            return
        self._todos = list(todos)
        self._render_todo_panel()

    def _render_todo_panel(self) -> None:
        t = self.i18n.t
        panel = self.query_one("#todo-panel", Static)
        if not self._todos:
            panel.display = False
            return

        markers = {"completed": "[green]✓[/]", "in_progress": "[yellow]▸[/]", "pending": "[#555566]○[/]"}
        lines: list[str] = []
        for i, item in enumerate(self._todos):
            status = item.get("status", "pending")
            content = item.get("content", "")
            marker = markers.get(status, "○")
            lines.append(f"{marker} {content}")

        summary_parts = []
        done = sum(1 for t in self._todos if t.get("status") == "completed")
        active = sum(1 for t in self._todos if t.get("status") == "in_progress")
        if done:
            summary_parts.append(f"{done} done")
        if active:
            summary_parts.append(f"{active} active")
        pending = len(self._todos) - done - active
        if pending:
            summary_parts.append(f"{pending} pending")
        summary = " · ".join(summary_parts)

        panel.update(f"[bold green]{t(TKey.TODO_TITLE)}[/]  {summary}\n" + "\n".join(lines))
        panel.display = True

    def _render_status_bar(self) -> None:
        if self.paths is None:
            return

        t = self.i18n.t
        mode_label = self._mode_label()

        def _update(text: str) -> None:
            self.query_one("#status-bar", Static).update(f"{mode_label}  {text}")

        if self._compacting:
            _update(t(TKey.STATUS_COMPACTING))
            return
        if self._is_streaming:
            spinner = self.SPINNER_FRAMES[self._spinner_frame]
            tok = self._streaming_output_tokens
            if tok:
                _update(f"{t(TKey.STATUS_WORKING)}... {spinner} {tok} tok")
            else:
                _update(f"{t(TKey.STATUS_WORKING)}... {spinner}")
            return

        primary = get_primary_llm_model(self.paths.config_path)
        if primary is None:
            _update(t(TKey.STATUS_NO_MODEL))
            return

        channel, model = primary
        parts = [f"{channel.name} / {model.name}"]

        think_label = "ON" if model.thinking_enabled else "OFF"
        parts.append(t(TKey.STATUS_THINK, status=think_label))
        parts.append(f"Effort: {model.reasoning_effort}")
        ctx_label = "1M" if model.context_window >= 1_000_000 else f"{model.context_window // 1000}K"
        parts.append(f"Ctx: {ctx_label}")
        out_label = f"{model.max_output_tokens // 1000}K" if model.max_output_tokens < 1_000_000 else "1M"
        parts.append(f"Out: {out_label}")

        if self.active_conversation_id is not None:
            msgs = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
            parts.append(t(TKey.STATUS_MSGS, count=len(msgs)))

            inp = self._last_input_tokens
            if inp or self._total_output_tokens:
                ctx = model.context_window
                if ctx and inp:
                    pct = (inp / ctx) * 100
                    parts.append(f"↑{inp} ↓{self._total_output_tokens} ({pct:.1f}%)")
                else:
                    parts.append(f"↑{inp} ↓{self._total_output_tokens}")
        else:
            parts.append(t(TKey.STATUS_NO_CONV))

        if self._mcp_manager is not None:
            mcp_status = self._mcp_manager.get_status()
            if mcp_status:
                connected = sum(1 for s in mcp_status.values() if s == "connected")
                total = len(mcp_status)
                errors = sum(1 for s in mcp_status.values() if s == "error")
                if errors > 0:
                    parts.append(f"MCP: {connected}/{total} [red]{errors} err[/]")
                else:
                    parts.append(f"MCP: {connected}/{total}")

        _update("  |  ".join(parts))

    def _render_history(self) -> None:
        if self.paths is None or self.active_conversation_id is None:
            return

        history = list_messages(self.paths.chat_path, conversation_id=self.active_conversation_id)
        self.query_one("#empty-state", Vertical).display = False

        if not history:
            self.query_one("#message-view", Markdown).update(self.i18n.t(TKey.MISC_NO_MESSAGES))
            return

        t = self.i18n.t
        lines: list[str] = []
        for msg in history:
            if msg.role == "tool":
                lines.append(f"**{t(TKey.LABEL_TOOL)}**\n\n{self._message_to_display(msg)}")
            elif msg.role == "system":
                lines.append(f"**{t(TKey.LABEL_SYSTEM)}**\n\n{self._message_to_display(msg)}")
            else:
                role_label = f"**{t(TKey.LABEL_YOU)}**" if msg.role == "user" else f"**{t(TKey.LABEL_ASSISTANT)}**"
                lines.append(f"{role_label}\n\n{self._message_to_display(msg)}")

        self.query_one("#message-view", Markdown).update("\n\n---\n\n".join(lines))
        self._scroll_chat_to_bottom()

    def _mask_api_key(self, api_key: str) -> str:
        if len(api_key) <= 6:
            return self.i18n.t(TKey.MISC_CONFIGURED)
        return f"{api_key[:3]}...{api_key[-2:]}"

def run() -> None:
    configure_logging()
    FlyinChatApp().run()
