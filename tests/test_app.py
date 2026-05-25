import asyncio
from pathlib import Path

from textual.widgets import Input, Static

from flyinchat import FlyinChatApp
from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    create_conversation,
    create_llm_api_profile,
    list_conversations,
    list_messages,
)


def test_app_can_be_created() -> None:
    app = FlyinChatApp()

    assert app.title == "FlyinChat"


def test_app_renders_empty_homepage(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test():
            empty_logo = app.query_one("#empty-logo", Static)
            prompt_input = app.query_one("#prompt-input", Input)

            assert "███████" in empty_logo.content
            assert "FlyinChat" in app.title
            assert prompt_input.placeholder == "Ask FlyinChat anything, or type / for commands"
            assert paths.config_db.exists()
            assert paths.chat_db.exists()

    asyncio.run(run_app())


def test_submitting_prompt_creates_project_conversation(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Explain this project"

            await pilot.press("enter")

            conversations = list_conversations(paths.chat_db)
            messages = list_messages(paths.chat_db, conversation_id=conversations[0].id)
            message_view = app.query_one("#message-view", Static)

            assert conversations[0].title == "Explain this project"
            assert messages[0].role == "user"
            assert messages[0].content == "Explain this project"
            assert message_view.content == "You\nExplain this project"
            assert prompt_input.value == ""

    asyncio.run(run_app())


def test_slash_opens_command_menu(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            await pilot.press("/")

            command_menu = app.query_one("#command-menu", Static)

            assert command_menu.display is True
            assert "/api" in command_menu.content
            assert "/sessions" in command_menu.content
            assert "/clear" in command_menu.content

    asyncio.run(run_app())


def test_api_command_shows_provider_settings(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            create_llm_api_profile(
                paths.config_db,
                name="Claude",
                provider_type="anthropic",
                api_key="key",
                model="claude-opus-4-7",
            )
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api"

            await pilot.press("enter")

            message_view = app.query_one("#message-view", Static)

            assert "LLM API providers" in message_view.content
            assert "Claude · anthropic · claude-opus-4-7" in message_view.content
            assert prompt_input.value == ""

    asyncio.run(run_app())


def test_sessions_command_shows_history(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            create_conversation(paths.chat_db, title="Existing chat")
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/sessions"

            await pilot.press("enter")

            message_view = app.query_one("#message-view", Static)

            assert "Session history" in message_view.content
            assert "1. Existing chat" in message_view.content

    asyncio.run(run_app())


def test_clear_command_starts_new_session(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Existing prompt"
            await pilot.press("enter")
            assert app.active_conversation_id is not None

            prompt_input.value = "/clear"
            await pilot.press("enter")

            message_view = app.query_one("#message-view", Static)

            assert app.active_conversation_id is None
            assert "New session" in message_view.content
            assert "Ready for a new project-local conversation." in message_view.content

    asyncio.run(run_app())
