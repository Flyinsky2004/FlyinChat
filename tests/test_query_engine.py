from collections.abc import AsyncIterator
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from flyinchat.models import LLMChannel, LLMModel
from flyinchat.paths import AppPaths, resolve_app_paths
from flyinchat.query_engine import QueryEngine, QueryEngineConfig, TurnEvent
from flyinchat.storage import (
    add_message,
    create_conversation,
    create_preset_channel,
    get_conversation,
    initialize_storage,
    list_messages,
)
from flyinchat.tools.core import (
    PermissionContext,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
)
from flyinchat.tools.file_tools import FileReadTool


def _setup_storage(tmp_path: Path) -> AppPaths:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
    initialize_storage(paths)
    create_preset_channel(paths.config_path, preset_id="deepseek", api_key="sk-test")
    return paths


def _make_tool_context(workspace: Path) -> ToolContext:
    permission = PermissionContext(
        allowed_tools={"file_read", "file_write", "bash"},
        allowed_read_roots=[workspace],
        allowed_write_roots=[workspace],
    )
    return ToolContext(
        session_id="test",
        user_id="test-user",
        workspace_root=workspace,
        permission=permission,
    )


def _make_query_engine(paths: AppPaths, conversation_id: str) -> QueryEngine:
    config = QueryEngineConfig(paths=paths, conversation_id=conversation_id)
    engine = QueryEngine(config)

    registry = ToolRegistry()
    registry.register(FileReadTool())
    executor = ToolExecutor(registry)
    ctx = _make_tool_context(paths.project_dir)
    engine.configure_tools(registry, executor, ctx)
    return engine


async def _collect_events(engine, prompt):
    events: list[TurnEvent] = []

    async def on_event(e: TurnEvent) -> None:
        events.append(e)

    result = await engine.submit_message(prompt, on_event=on_event)
    return result, events


class TestQueryEngineBasic:
    def test_no_model_configured(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = resolve_app_paths(
                home=tmp_path / "home", cwd=tmp_path / "project"
            )
            initialize_storage(paths)
            conv = create_conversation(paths.chat_path, title="test")
            engine = QueryEngine(
                QueryEngineConfig(paths=paths, conversation_id=conv.id)
            )
            result, events = await _collect_events(engine, "hello")
            assert result.status == "error"
            assert "No model configured" in (result.error or "")
            assert any(e.event_type == "error" for e in events)

        asyncio.run(run())

    def test_submit_message_persists_user_message(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            # Mock the API to return plain text
            async def mock_stream(channel, model, messages, usage_info, tools):
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                yield {"type": "text", "content": "Hello back"}
                return

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
                result, events = await _collect_events(engine, "hello there")
                assert result.status == "completed"
                assert result.final_text == "Hello back"

            messages = list_messages(paths.chat_path, conversation_id=conv.id)
            assert len(messages) >= 2
            assert messages[0].role == "user"
            assert messages[0].content == "hello there"
            assert messages[0].turn_id != ""

        asyncio.run(run())

    def test_turn_event_sequence(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            async def mock_stream(channel, model, messages, usage_info, tools):
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                yield {"type": "text", "content": "response"}
                return

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
                _, events = await _collect_events(engine, "hello")
                event_types = [e.event_type for e in events]
                assert "turn_start" in event_types
                assert "text" in event_types
                assert "turn_end" in event_types

        asyncio.run(run())

    def test_tool_call_loop(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            # Create a small test file for file_read
            test_file = tmp_path / "project" / "test.txt"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("file content here")

            workspace = tmp_path / "project"
            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            call_count = 0

            async def mock_stream(channel, model, messages, usage_info, tools):
                nonlocal call_count
                call_count += 1
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                if call_count == 1:
                    yield {
                        "type": "tool_use",
                        "id": "tu_001",
                        "name": "file_read",
                        "input": {"path": "test.txt"},
                    }
                else:
                    yield {"type": "text", "content": "I read the file"}
                return

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
                result, events = await _collect_events(engine, "read test.txt")
                assert result.status == "completed"
                assert result.tool_rounds == 1

            messages = list_messages(paths.chat_path, conversation_id=conv.id)
            roles = [(m.role, m.subtype) for m in messages]
            assert ("user", "normal") in roles
            assert ("assistant", "tool_call") in roles
            assert ("tool", "tool_result") in roles
            assert ("assistant", "normal") in roles

        asyncio.run(run())

    def test_normal_assistant_message_preserves_reasoning_content(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            async def mock_stream(channel, model, messages, usage_info, tools):
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                yield {"type": "reasoning", "content": "thinking before answer"}
                yield {"type": "text", "content": "final answer"}
                return

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
                result, _ = await _collect_events(engine, "hello")

            assert result.status == "completed"
            messages = list_messages(paths.chat_path, conversation_id=conv.id)
            assistant = next(msg for msg in messages if msg.role == "assistant")
            content = json.loads(assistant.content)
            assert content == [
                {"type": "thinking", "thinking": "thinking before answer", "signature": ""},
                {"type": "text", "text": "final answer"},
            ]

        asyncio.run(run())

    def test_turn_id_increments(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            async def mock_stream(channel, model, messages, usage_info, tools):
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                yield {"type": "text", "content": "ok"}
                return

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
                await _collect_events(engine, "first")
                await _collect_events(engine, "second")

            conv_after = get_conversation(paths.chat_path, conversation_id=conv.id)
            assert conv_after is not None
            assert conv_after.current_turn == 2

        asyncio.run(run())

    def test_multi_round_tool_call_with_reasoning(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            test_file = tmp_path / "project" / "test.txt"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("file content here")

            conv = create_conversation(paths.chat_path, title="test")
            engine = _make_query_engine(paths, conv.id)

            call_count = 0

            async def mock_stream(channel, model, messages, usage_info, tools):
                nonlocal call_count
                call_count += 1
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                if call_count == 1:
                    yield {"type": "reasoning", "content": "need to read the file first"}
                    yield {
                        "type": "tool_use",
                        "id": "tu_001",
                        "name": "file_read",
                        "input": {"path": "test.txt"},
                    }
                elif call_count == 2:
                    yield {"type": "reasoning", "content": "I see the file content, now I can answer"}
                    yield {"type": "text", "content": "The file contains: file content here"}
                return

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
                result, events = await _collect_events(engine, "read test.txt")

            assert result.status == "completed"
            assert result.tool_rounds == 1
            assert result.final_text == "The file contains: file content here"

            messages = list_messages(paths.chat_path, conversation_id=conv.id)
            roles_subtypes = [(m.role, m.subtype) for m in messages]
            assert ("user", "normal") in roles_subtypes
            assert ("assistant", "tool_call") in roles_subtypes
            assert ("tool", "tool_result") in roles_subtypes
            assert ("assistant", "normal") in roles_subtypes

            tool_call_msg = next(
                m for m in messages if m.role == "assistant" and m.subtype == "tool_call"
            )
            content = json.loads(tool_call_msg.content)
            assert content[0]["type"] == "thinking"
            assert content[0]["thinking"] == "need to read the file first"
            assert content[1]["type"] == "tool_use"
            assert content[1]["name"] == "file_read"

            normal_msg = next(
                m for m in messages if m.role == "assistant" and m.subtype == "normal"
            )
            normal_content = json.loads(normal_msg.content)
            assert normal_content[0]["type"] == "thinking"
            assert normal_content[0]["thinking"] == "I see the file content, now I can answer"
            assert normal_content[1]["type"] == "text"
            assert normal_content[1]["text"] == "The file contains: file content here"

        asyncio.run(run())

    def test_max_tool_rounds_enforced(self, tmp_path: Path) -> None:
        import asyncio

        async def run():
            paths = _setup_storage(tmp_path)
            conv = create_conversation(paths.chat_path, title="test")
            config = QueryEngineConfig(
                paths=paths, conversation_id=conv.id, max_tool_rounds=3
            )
            engine = QueryEngine(config)

            async def mock_stream(channel, model, messages, usage_info, tools):
                usage_info["completion_tokens"] = 10
                usage_info["prompt_tokens"] = 5
                yield {
                    "type": "tool_use",
                    "id": "tu_001",
                    "name": "file_read",
                    "input": {"path": "dne.txt"},
                }
                return

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
                result, _ = await _collect_events(engine, "loop forever")
                assert result.status == "max_rounds"
                assert result.tool_rounds == 3

        asyncio.run(run())
