import asyncio
from pathlib import Path

from textual.widgets import Input, Markdown, Static

from flyinchat import FlyinChatApp
from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    create_conversation,
    get_primary_llm_model,
    list_conversations,
    list_llm_channels,
    list_llm_models,
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
            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert conversations[0].title == "Explain this project"
            assert messages[0].role == "user"
            assert messages[0].content == "Explain this project"
            assert "**You**" in raw
            assert "Explain this project" in raw
            assert "Error" in raw
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


def test_api_command_shows_presets_when_empty(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api"

            await pilot.press("enter")

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert "LLM API providers" in raw
            assert "No providers configured yet" in raw
            assert "deepseek: DeepSeek" in raw
            assert "Add DeepSeek preset" in raw
            assert "Use ↑/↓ to choose an action, Enter to continue." in raw

    asyncio.run(run_app())


def test_slash_menu_can_open_api_with_enter(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("enter")

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert "LLM API providers" in raw
            assert "Add DeepSeek preset" in raw

    asyncio.run(run_app())


def test_api_selection_flow_adds_deepseek(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api"
            await pilot.press("enter")
            await pilot.press("enter")
            prompt_input.value = "deepseek-secret"
            await pilot.press("enter")

            channels = list_llm_channels(paths.config_db)
            models = list_llm_models(paths.config_db, channel_id=channels[0].id)
            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert channels[0].name == "DeepSeek"
            assert [model.name for model in models] == ["deepseek-v4-pro", "deepseek-v4-flash"]
            assert "API channel added" in raw

    asyncio.run(run_app())


def test_api_add_deepseek_creates_preset_channel(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add deepseek deepseek-secret"

            await pilot.press("enter")

            channels = list_llm_channels(paths.config_db)
            models = list_llm_models(paths.config_db, channel_id=channels[0].id)
            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert channels[0].name == "DeepSeek"
            assert channels[0].base_url == "https://api.deepseek.com"
            assert [model.name for model in models] == ["deepseek-v4-pro", "deepseek-v4-flash"]
            assert "API channel added" in raw
            assert "deepseek-secret" not in raw

    asyncio.run(run_app())


def test_api_add_openai_creates_channel_with_models(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add openai Local http://localhost:11434/v1 local-secret qwen3,glm4"

            await pilot.press("enter")

            channels = list_llm_channels(paths.config_db)
            models = list_llm_models(paths.config_db, channel_id=channels[0].id)

            assert channels[0].name == "Local"
            assert channels[0].provider_type == "openai_compatible"
            assert channels[0].base_url == "http://localhost:11434/v1"
            assert [model.name for model in models] == ["qwen3", "glm4"]

    asyncio.run(run_app())


def test_api_page_masks_configured_keys(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add deepseek deepseek-secret"
            await pilot.press("enter")
            prompt_input.value = "/api"
            await pilot.press("enter")

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert "dee...et" in raw
            assert "deepseek-secret" not in raw

    asyncio.run(run_app())


def test_model_command_lists_configured_models(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add deepseek deepseek-secret"
            await pilot.press("enter")
            prompt_input.value = "/model"
            await pilot.press("enter")

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert "Primary model" in raw
            assert "1. DeepSeek · openai_compatible" in raw
            assert "1.1 deepseek-v4-pro [primary]" in raw
            assert "1.2 deepseek-v4-flash" in raw
            assert "Use ↑/↓ to choose a model, Enter to set primary." in raw

    asyncio.run(run_app())


def test_model_selection_uses_arrow_keys(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add deepseek deepseek-secret"
            await pilot.press("enter")
            prompt_input.value = "/model"
            await pilot.press("enter")
            await pilot.press("down")
            await pilot.press("enter")

            primary = get_primary_llm_model(paths.config_db)

            assert primary is not None
            assert primary[1].name == "deepseek-v4-flash"

    asyncio.run(run_app())


def test_model_use_selects_primary_model(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/api add deepseek deepseek-secret"
            await pilot.press("enter")
            prompt_input.value = "/model use 1 2"
            await pilot.press("enter")

            primary = get_primary_llm_model(paths.config_db)
            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert primary is not None
            assert primary[0].name == "DeepSeek"
            assert primary[1].name == "deepseek-v4-flash"
            assert "Primary model selected" in raw
            assert "deepseek-v4-flash" in raw

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

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert "Session history" in raw
            assert "1. Existing chat" in raw

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

            message_view = app.query_one("#message-view", Markdown)
            raw = message_view._markdown

            assert app.active_conversation_id is None
            assert "New session" in raw
            assert "Ready for a new project-local conversation." in raw

    asyncio.run(run_app())


def test_double_escape_clears_input(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "hello world"

            await pilot.press("escape")
            assert prompt_input.value == "hello world"

            await pilot.press("escape")
            assert prompt_input.value == ""
            assert app.selection_items == ()

    asyncio.run(run_app())
