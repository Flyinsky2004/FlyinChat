import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from textual.widgets import Input, Static

from flyinchat import FlyinChatApp
from flyinchat.chat_message import ChatMessage
from flyinchat.paths import resolve_app_paths


def _get_message_view_text(app) -> str:
    """Get combined markdown text from all ChatMessage widgets in message-view."""
    msg_view = app.query_one("#message-view")
    parts = []
    for child in msg_view.children:
        if hasattr(child, '_markdown'):
            parts.append(child._markdown)
    return "\n\n".join(parts)
from flyinchat.storage import (
    add_message,
    create_conversation,
    get_primary_llm_model,
    list_conversations,
    list_llm_channels,
    list_llm_models,
    list_messages,
)


class FakeObservabilityClient:
    def __init__(self) -> None:
        self.shutdown_count = 0

    @property
    def enabled(self) -> bool:
        return False

    def start_trace(self, **kwargs):
        return None

    def update_trace(self, *args, **kwargs) -> None:
        return None

    def start_span(self, *args, **kwargs):
        return None

    def end_span(self, *args, **kwargs) -> None:
        return None

    def start_generation(self, *args, **kwargs):
        return None

    def end_generation(self, *args, **kwargs) -> None:
        return None

    def score_trace(self, *args, **kwargs) -> None:
        return None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_count += 1


def test_app_can_be_created() -> None:
    app = FlyinChatApp()

    assert app.title == "FlyinChat"


def test_app_accepts_observability_client(tmp_path: Path) -> None:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
    fake = FakeObservabilityClient()
    app = FlyinChatApp(paths=paths, observability_client=fake)

    assert app._observability_client is fake


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
            assert paths.config_path.exists()
            assert paths.chat_path.exists()

    asyncio.run(run_app())


def test_app_shutdown_calls_observability_client(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        fake = FakeObservabilityClient()
        app = FlyinChatApp(paths=paths, observability_client=fake)

        async with app.run_test():
            await app.action_quit()

        assert fake.shutdown_count == 1

    asyncio.run(run_app())


def test_submitting_prompt_creates_project_conversation(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Explain this project"

            await pilot.press("enter")

            conversations = list_conversations(paths.chat_path)
            messages = list_messages(paths.chat_path, conversation_id=conversations[0].id)
            raw = _get_message_view_text(app)

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

            raw = _get_message_view_text(app)

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

            raw = _get_message_view_text(app)

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

            channels = list_llm_channels(paths.config_path)
            models = list_llm_models(paths.config_path, channel_id=channels[0].id)
            raw = _get_message_view_text(app)

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

            channels = list_llm_channels(paths.config_path)
            models = list_llm_models(paths.config_path, channel_id=channels[0].id)
            raw = _get_message_view_text(app)

            assert channels[0].name == "DeepSeek"
            assert channels[0].base_url == "https://api.deepseek.com/anthropic"
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

            channels = list_llm_channels(paths.config_path)
            models = list_llm_models(paths.config_path, channel_id=channels[0].id)

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

            raw = _get_message_view_text(app)

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

            raw = _get_message_view_text(app)

            assert "Primary model" in raw
            assert "1. DeepSeek · anthropic" in raw
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

            primary = get_primary_llm_model(paths.config_path)

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

            primary = get_primary_llm_model(paths.config_path)
            raw = _get_message_view_text(app)

            assert primary is not None
            assert primary[0].name == "DeepSeek"
            assert primary[1].name == "deepseek-v4-flash"
            assert "Primary model" in raw
            assert "deepseek-v4-flash" in raw

    asyncio.run(run_app())


def test_sessions_command_shows_history(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            create_conversation(paths.chat_path, title="Existing chat")
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/sessions"

            await pilot.press("enter")

            raw = _get_message_view_text(app)

            assert "Session history" in raw
            assert "1. Existing chat" in raw

    asyncio.run(run_app())


def test_selected_session_loads_prompt_history(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            conversation = create_conversation(paths.chat_path, title="Existing chat")
            add_message(paths.chat_path, conversation_id=conversation.id, role="user", content="First old question")
            add_message(paths.chat_path, conversation_id=conversation.id, role="assistant", content="Old answer")
            add_message(paths.chat_path, conversation_id=conversation.id, role="user", content="Second old question")
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/sessions"
            await pilot.press("enter")
            await pilot.press("enter")

            await pilot.press("up")
            assert prompt_input.value == "Second old question"

            await pilot.press("up")
            assert prompt_input.value == "First old question"

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

            raw = _get_message_view_text(app)

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


def test_prompt_history_uses_arrow_keys(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)
        app._submit_via_engine = lambda prompt: app._stop_spinner()

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "First prompt"
            await pilot.press("enter")
            prompt_input.value = "Second prompt"
            await pilot.press("enter")

            await pilot.press("up")
            assert prompt_input.value == "Second prompt"

            await pilot.press("up")
            assert prompt_input.value == "First prompt"

            await pilot.press("down")
            assert prompt_input.value == "Second prompt"

            await pilot.press("down")
            assert prompt_input.value == ""

    asyncio.run(run_app())


def test_prompt_history_restores_draft_and_skips_commands(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)
        app._submit_via_engine = lambda prompt: app._stop_spinner()

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Remember this"
            await pilot.press("enter")
            prompt_input.value = "/not-a-command"
            await pilot.press("enter")
            prompt_input.value = "draft text"

            await pilot.press("up")
            assert prompt_input.value == "Remember this"

            await pilot.press("down")
            assert prompt_input.value == "draft text"

    asyncio.run(run_app())


def test_file_mention_menu_inserts_relative_path(tmp_path: Path) -> None:
    async def run_app() -> None:
        project = tmp_path / "project"
        source = project / "src" / "flyinchat"
        source.mkdir(parents=True)
        (source / "app.py").write_text("SECRET-CONTENT", encoding="utf-8")
        paths = resolve_app_paths(home=tmp_path / "home", cwd=project)
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            command_menu = app.query_one("#command-menu", Static)
            original_text = _get_message_view_text(app)
            prompt_input.value = "Explain @"
            prompt_input.action_end()
            await pilot.press("a")
            await pilot.press("p")
            await pilot.press("p")
            await pilot.pause()

            assert command_menu.display is True
            assert "src/flyinchat/app.py" in command_menu.content
            assert _get_message_view_text(app) == original_text

            await pilot.press("enter")

            assert prompt_input.value == "Explain src/flyinchat/app.py "
            assert "SECRET-CONTENT" not in prompt_input.value

    asyncio.run(run_app())


def test_file_mention_selection_uses_arrow_keys(tmp_path: Path) -> None:
    async def run_app() -> None:
        project = tmp_path / "project"
        source = project / "src" / "flyinchat"
        source.mkdir(parents=True)
        (source / "api_client.py").write_text("api", encoding="utf-8")
        (source / "app.py").write_text("app", encoding="utf-8")
        paths = resolve_app_paths(home=tmp_path / "home", cwd=project)
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Open @a"
            prompt_input.action_end()
            await pilot.pause()

            original_text = _get_message_view_text(app)

            assert app.selection_context == "file_mention"
            assert app.selected_index == 0

            await pilot.press("down")
            assert app.selected_index == 1
            assert _get_message_view_text(app) == original_text

            await pilot.press("up")
            assert app.selected_index == 0
            assert _get_message_view_text(app) == original_text

    asyncio.run(run_app())


def test_file_mention_submit_persists_path_without_content(tmp_path: Path) -> None:
    async def run_app() -> None:
        project = tmp_path / "project"
        source = project / "src" / "flyinchat"
        source.mkdir(parents=True)
        (source / "app.py").write_text("SECRET-CONTENT", encoding="utf-8")
        paths = resolve_app_paths(home=tmp_path / "home", cwd=project)
        app = FlyinChatApp(paths=paths)
        app._submit_via_engine = lambda prompt: app._stop_spinner()

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "Read @app"
            prompt_input.action_end()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.press("enter")

            conversations = list_conversations(paths.chat_path)
            messages = list_messages(paths.chat_path, conversation_id=conversations[0].id)

            assert messages[0].content == "Read src/flyinchat/app.py"
            assert "SECRET-CONTENT" not in messages[0].content

    asyncio.run(run_app())


def test_streaming_text_renders_before_turn_end(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)
        first_chunk_seen = asyncio.Event()
        release_stream = asyncio.Event()

        async def mock_stream(channel, model, messages, usage_info, tools):
            usage_info["completion_tokens"] = 2
            usage_info["prompt_tokens"] = 1
            yield {"type": "text", "content": "partial"}
            first_chunk_seen.set()
            await release_stream.wait()
            yield {"type": "text", "content": " complete"}

        async with app.run_test() as pilot:
            with (
                patch(
                    "flyinchat.query_engine.stream_chat_completion",
                    side_effect=mock_stream,
                ),
                patch(
                    "flyinchat.query_engine.CompactionEngine.compact_if_needed_async",
                    new_callable=AsyncMock,
                ) as mock_compact,
            ):
                mock_compact.return_value.applied = False
                prompt_input = app.query_one("#prompt-input", Input)
                prompt_input.value = "/api add deepseek deepseek-secret"
                await pilot.press("enter")
                prompt_input.value = "stream please"
                await pilot.press("enter")

                await asyncio.wait_for(first_chunk_seen.wait(), timeout=1)
                await pilot.pause()

                text = _get_message_view_text(app)
                assert "partial" in text
                assert "partial complete" not in text

                release_stream.set()
                await pilot.pause(0.2)

                text = _get_message_view_text(app)
                assert "partial complete" in text

    asyncio.run(run_app())


def test_tool_permission_request_appears_during_conversation(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)
        stream_count = 0

        async def mock_stream(channel, model, messages, usage_info, tools):
            nonlocal stream_count
            stream_count += 1
            usage_info["completion_tokens"] = 1
            usage_info["prompt_tokens"] = 1
            if stream_count == 1:
                yield {
                    "type": "tool_use",
                    "id": "tu_write",
                    "name": "file_write",
                    "input": {"path": "hello.txt", "content": "hello"},
                }
                return
            yield {"type": "text", "content": "done"}

        async with app.run_test() as pilot:
            with (
                patch(
                    "flyinchat.query_engine.stream_chat_completion",
                    side_effect=mock_stream,
                ),
                patch(
                    "flyinchat.query_engine.CompactionEngine.compact_if_needed_async",
                    new_callable=AsyncMock,
                ) as mock_compact,
            ):
                mock_compact.return_value.applied = False
                prompt_input = app.query_one("#prompt-input", Input)
                prompt_input.value = "/api add deepseek deepseek-secret"
                await pilot.press("enter")
                prompt_input.value = "write hello.txt"
                await pilot.press("enter")

                await pilot.pause()

                text = _get_message_view_text(app)
                command_menu = app.query_one("#command-menu", Static)

                assert app._pending_permission_request_id is not None
                assert "Permission Required" in text
                assert "file_write" in text
                assert command_menu.display is True
                assert "Approve" in command_menu.content

                await pilot.press("enter")
                await pilot.pause(0.2)

                assert app._pending_permission_request_id is None
                assert (tmp_path / "project" / "hello.txt").read_text() == "hello"

    asyncio.run(run_app())


def test_init_appears_in_command_menu(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            await pilot.press("/")

            command_menu = app.query_one("#command-menu", Static)

            assert command_menu.display is True
            assert "/init" in command_menu.content

    asyncio.run(run_app())


def test_init_shows_error_without_model(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/init"
            await pilot.press("enter")

            raw = _get_message_view_text(app)

            assert "No primary model configured" in raw or "未配置主模型" in raw

    asyncio.run(run_app())


def test_init_creates_conversation_and_submits_prompt(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        app = FlyinChatApp(paths=paths)

        async def mock_stream(channel, model, messages, usage_info, tools):
            usage_info["completion_tokens"] = 5
            usage_info["prompt_tokens"] = 3
            yield {"type": "text", "content": "FLYINCHAT.md generated"}

        async with app.run_test() as pilot:
            with (
                patch(
                    "flyinchat.query_engine.stream_chat_completion",
                    side_effect=mock_stream,
                ),
                patch(
                    "flyinchat.query_engine.CompactionEngine.compact_if_needed_async",
                    new_callable=AsyncMock,
                ) as mock_compact,
            ):
                mock_compact.return_value.applied = False

                # Configure DeepSeek model first
                prompt_input = app.query_one("#prompt-input", Input)
                prompt_input.value = "/api add deepseek test-key"
                await pilot.press("enter")
                await pilot.pause(0.2)

                # Select it as primary
                prompt_input.value = "/model use DeepSeek deepseek-v4-pro"
                await pilot.press("enter")
                await pilot.pause(0.2)

                # Run init
                prompt_input.value = "/init"
                await pilot.press("enter")
                await pilot.pause(0.2)
                await pilot.pause(0.2)

                convs = list_conversations(paths.chat_path)
                assert len(convs) >= 1
                # The init conversation should be the second one (first is /api conversation)
                init_conv = convs[-1]
                messages = list_messages(paths.chat_path, conversation_id=init_conv.id)
                assert len(messages) >= 1
                assert messages[0].role == "user"

                text = _get_message_view_text(app)
                assert "FLYINCHAT.md generated" in text

    asyncio.run(run_app())


def test_skills_command_shows_loaded_skills(tmp_path: Path) -> None:
    async def run_app() -> None:
        paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
        skill_path = tmp_path / "project" / "skills" / "safe-edit" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(
            """---
name: safe-edit
description: Use when editing files
version: 1.0.0
category: software-development
metadata:
  tags: [edit, files]
---

# Safe Edit

## Workflow
Read before editing.
""",
            encoding="utf-8",
        )
        app = FlyinChatApp(paths=paths)

        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", Input)
            prompt_input.value = "/skills"
            await pilot.press("enter")
            await pilot.pause(0.1)

            raw = _get_message_view_text(app)
            assert "Agent Skills" in raw
            assert "safe-edit@1.0.0" in raw
            assert "Use when editing files" in raw
            assert "edit, files" in raw

    asyncio.run(run_app())
