from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Input, Static

from .paths import AppPaths
from .storage import (
    add_message,
    create_conversation,
    initialize_storage,
    list_conversations,
    list_llm_api_profiles,
)

_EMPTY_LOGO = """
███████╗██╗  ██╗   ██╗██╗███╗   ██╗ ██████╗██╗  ██╗ █████╗ ████████╗
██╔════╝██║  ╚██╗ ██╔╝██║████╗  ██║██╔════╝██║  ██║██╔══██╗╚══██╔══╝
█████╗  ██║   ╚████╔╝ ██║██╔██╗ ██║██║     ███████║███████║   ██║
██╔══╝  ██║    ╚██╔╝  ██║██║╚██╗██║██║     ██╔══██║██╔══██║   ██║
██║     ███████╗██║   ██║██║ ╚████║╚██████╗██║  ██║██║  ██║   ██║
╚═╝     ╚══════╝╚═╝   ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
""".strip()

_COMMANDS = (
    ("/api", "LLM API providers", "Open provider settings"),
    ("/sessions", "Session history", "Choose from project conversations"),
    ("/clear", "New session", "Clear the current conversation view"),
)


class FlyinChatApp(App[None]):
    TITLE = "FlyinChat"

    def __init__(self, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.paths = paths
        self.active_conversation_id: str | None = None

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
        align: center middle;
        padding: 2 4;
    }

    #empty-state {
        width: 100%;
        max-width: 90;
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
        max-width: 90;
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

    def on_input_changed(self, event: Input.Changed) -> None:
        command_menu = self.query_one("#command-menu", Static)
        value = event.value.strip()

        if value.startswith("/"):
            command_menu.update(self._format_command_menu(value))
            command_menu.display = True
            return

        command_menu.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt or self.paths is None:
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
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Static).update(f"You\n{prompt}")
        event.input.value = ""

    def _run_command(self, command: str) -> None:
        match command:
            case "/api":
                self._show_api_settings()
            case "/sessions":
                self._show_sessions()
            case "/clear":
                self._start_new_session()
            case _:
                self._show_panel("Unknown command", f"No command named {command}. Type / to see available commands.")

    def _format_command_menu(self, query: str) -> str:
        matches = [command for command in _COMMANDS if command[0].startswith(query)]
        if not matches:
            return "No matching commands\nType /api, /sessions, or /clear"

        rows = ["Commands"]
        rows.extend(f"{name:<10} {title} — {description}" for name, title, description in matches)
        return "\n".join(rows)

    def _show_api_settings(self) -> None:
        if self.paths is None:
            return

        profiles = list_llm_api_profiles(self.paths.config_db)
        if profiles:
            details = "\n".join(
                f"{profile.name} · {profile.provider_type} · {profile.model}"
                for profile in profiles
            )
        else:
            details = "No providers configured yet. Supported types: openai_compatible, anthropic."

        self._show_panel("LLM API providers", details)

    def _show_sessions(self) -> None:
        if self.paths is None:
            return

        conversations = list_conversations(self.paths.chat_db)
        if conversations:
            details = "\n".join(
                f"{index}. {conversation.title}"
                for index, conversation in enumerate(conversations, start=1)
            )
        else:
            details = "No project-local sessions yet. Send a message to create one."

        self._show_panel("Session history", details)

    def _start_new_session(self) -> None:
        self.active_conversation_id = None
        self.query_one("#empty-state", Vertical).display = True
        self._show_panel("New session", "Ready for a new project-local conversation.")

    def _show_panel(self, title: str, body: str) -> None:
        self.query_one("#empty-state", Vertical).display = False
        self.query_one("#message-view", Static).update(f"{title}\n\n{body}")


def run() -> None:
    FlyinChatApp().run()
