from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from flyinchat.models import LLMChannel, LLMModel
from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    create_conversation,
    initialize_storage,
    list_subagent_conversations,
)
from flyinchat.subagents import SubAgentDefinition
from flyinchat.subagents.executor import SubAgentExecutor
from flyinchat.tools import (
    FileReadTool,
    FileWriteTool,
    PermissionContext,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
)


def _channel_model() -> tuple[LLMChannel, LLMModel]:
    channel = LLMChannel(
        id="channel-1",
        name="Test",
        provider_type="anthropic",
        base_url=None,
        api_key="test-key",
        created_at="",
        updated_at="",
    )
    model = LLMModel(
        id="model-1",
        channel_id=channel.id,
        name="test-model",
        is_default=True,
    )
    return channel, model


def _tool_setup(workspace: Path) -> tuple[ToolRegistry, ToolExecutor, ToolContext]:
    registry = ToolRegistry()
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    executor = ToolExecutor(registry)
    context = ToolContext(
        session_id="parent",
        user_id="user",
        workspace_root=workspace,
        permission=PermissionContext(
            allowed_tools={"file_read", "file_write"},
            allowed_read_roots=[workspace],
            allowed_write_roots=[workspace],
        ),
    )
    return registry, executor, context


def test_subagent_reads_file_in_isolated_conversation(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
        workspace = paths.project_dir.parent
        target = workspace / "example.txt"
        target.write_text("hello sub-agent", encoding="utf-8")
        parent = create_conversation(paths.chat_path, title="Parent")
        registry, executor, context = _tool_setup(workspace)
        channel, model = _channel_model()
        calls = 0

        async def fake_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                yield {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "file_read",
                    "input": {"path": "example.txt"},
                }
            else:
                yield {"type": "text", "content": "- Read example.txt and confirmed its content."}

        monkeypatch.setattr("flyinchat.subagents.executor.stream_chat_completion", fake_stream)
        definition = SubAgentDefinition(
            name="general-purpose",
            description="General",
            system_prompt="Read files and summarize.",
            allowed_tools=("file_read",),
            permission_mode="readonly",
            max_turns=3,
        )
        sub_executor = SubAgentExecutor(
            definition,
            channel,
            model,
            registry,
            executor,
            context,
            paths.chat_path,
            parent.id,
        )

        result = await sub_executor.execute("Read example.txt")

        assert result.status == "success"
        assert result.tool_calls_count == 1
        assert str(target) in result.files_read
        assert list_subagent_conversations(paths.chat_path, parent_conversation_id=parent.id)[0].agent_type == "general-purpose"

    import asyncio

    asyncio.run(run())


def test_subagent_denies_write_when_readonly(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
        workspace = paths.project_dir.parent
        parent = create_conversation(paths.chat_path, title="Parent")
        registry, executor, context = _tool_setup(workspace)
        channel, model = _channel_model()
        calls = 0

        async def fake_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                yield {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "file_write",
                    "input": {"path": "created.txt", "content": "bad"},
                }
            else:
                yield {"type": "text", "content": "Write was blocked."}

        monkeypatch.setattr("flyinchat.subagents.executor.stream_chat_completion", fake_stream)
        definition = SubAgentDefinition(
            name="readonly-writer",
            description="Readonly writer",
            system_prompt="Attempt diagnostics only.",
            allowed_tools=("file_write",),
            permission_mode="readonly",
            max_turns=3,
        )
        sub_executor = SubAgentExecutor(
            definition,
            channel,
            model,
            registry,
            executor,
            context,
            paths.chat_path,
            parent.id,
        )

        result = await sub_executor.execute("Try to write a file")

        assert not (workspace / "created.txt").exists()
        assert result.errors
        assert "write not allowed" in result.errors[0]

    import asyncio

    asyncio.run(run())
