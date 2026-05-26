import sqlite3
from pathlib import Path

import pytest

from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    add_message,
    add_message_with_turn,
    create_channel_with_models,
    create_conversation,
    create_llm_channel,
    create_preset_channel,
    get_primary_llm_model,
    get_turn_messages,
    increment_turn,
    initialize_storage,
    list_active_messages,
    list_conversations,
    list_llm_channels,
    list_llm_models,
    list_messages,
    set_primary_llm_model,
)


def test_resolve_app_paths_uses_home_and_cwd(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "project"

    paths = resolve_app_paths(home=home, cwd=cwd)

    assert paths.global_dir == home / ".flyinchat"
    assert paths.project_dir == cwd / ".flyinchat"
    assert paths.config_path == home / ".flyinchat" / "config.json"
    assert paths.chat_path == cwd / ".flyinchat" / "chat.json"


def test_initialize_storage_creates_databases(tmp_path: Path) -> None:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")

    initialized_paths = initialize_storage(paths)

    assert initialized_paths == paths
    assert paths.config_path.exists()
    assert paths.chat_path.exists()


def test_openai_compatible_channel_can_have_multiple_models(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    channel, models = create_channel_with_models(
        paths.config_path,
        name="Local",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
        model_names=("qwen3", "glm4"),
    )

    assert list_llm_channels(paths.config_path) == [channel]
    assert [model.name for model in models] == ["qwen3", "glm4"]
    assert list_llm_models(paths.config_path, channel_id=channel.id) == models
    assert models[0].is_default is True
    assert models[1].is_default is False
    assert get_primary_llm_model(paths.config_path) == (channel, models[0])


def test_setting_primary_model_moves_default(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    channel, models = create_channel_with_models(
        paths.config_path,
        name="Local",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
        model_names=("qwen3", "glm4"),
    )

    selected_channel, selected_model = set_primary_llm_model(
        paths.config_path,
        model_id=models[1].id,
    )
    updated_models = list_llm_models(paths.config_path, channel_id=channel.id)

    assert selected_channel == channel
    assert selected_model.name == "glm4"
    assert get_primary_llm_model(paths.config_path) == (selected_channel, selected_model)
    assert [model.is_default for model in updated_models] == [True, False]
    assert updated_models[0].name == "glm4"


def test_anthropic_channel_can_have_models(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    channel, models = create_channel_with_models(
        paths.config_path,
        name="Claude",
        provider_type="anthropic",
        api_key="anthropic-key",
        model_names=("claude-opus-4-7", "claude-sonnet-4-6"),
    )

    assert channel.provider_type == "anthropic"
    assert channel.base_url is None
    assert [model.name for model in models] == ["claude-opus-4-7", "claude-sonnet-4-6"]


def test_deepseek_preset_uses_only_api_key(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    channel, models = create_preset_channel(
        paths.config_path,
        preset_id="deepseek",
        api_key="deepseek-key",
    )

    assert channel.name == "DeepSeek"
    assert channel.provider_type == "openai_compatible"
    assert channel.base_url == "https://api.deepseek.com"
    assert channel.api_key == "deepseek-key"
    assert [model.name for model in models] == ["deepseek-v4-pro", "deepseek-v4-flash"]


def test_invalid_provider_type_is_rejected(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="Unsupported provider_type"):
        create_llm_channel(
            paths.config_path,
            name="Bad",
            provider_type="unknown",
            api_key="key",
        )


def test_empty_model_list_is_rejected(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="At least one model"):
        create_channel_with_models(
            paths.config_path,
            name="Bad",
            provider_type="anthropic",
            api_key="key",
            model_names=(),
        )


def test_conversations_and_messages_are_project_local(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_a = initialize_storage(resolve_app_paths(home=home, cwd=tmp_path / "project-a"))
    project_b = initialize_storage(resolve_app_paths(home=home, cwd=tmp_path / "project-b"))

    conversation = create_conversation(project_a.chat_path, title="Project A chat")
    user_message = add_message(
        project_a.chat_path,
        conversation_id=conversation.id,
        role="user",
        content="Hello",
    )
    assistant_message = add_message(
        project_a.chat_path,
        conversation_id=conversation.id,
        role="assistant",
        content="Hi",
    )

    conversations = list_conversations(project_a.chat_path)

    assert len(conversations) == 1
    assert conversations[0].id == conversation.id
    assert conversations[0].title == conversation.title
    assert list_messages(project_a.chat_path, conversation_id=conversation.id) == [
        user_message,
        assistant_message,
    ]
    assert list_conversations(project_b.chat_path) == []


def test_message_requires_existing_conversation(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="Conversation not found"):
        add_message(
            paths.chat_path,
            conversation_id="missing",
            role="user",
            content="Hello",
        )


def test_message_default_fields(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")

    msg = add_message(paths.chat_path, conversation_id=conv.id, role="user", content="hello")
    assert msg.turn_id == ""
    assert msg.subtype == "normal"
    assert msg.tool_call_id is None
    assert msg.meta == "{}"


def test_add_message_with_turn(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")

    msg = add_message_with_turn(
        paths.chat_path,
        conversation_id=conv.id,
        turn_id="turn_1_abc",
        role="user",
        subtype="normal",
        content="hello",
    )
    assert msg.turn_id == "turn_1_abc"
    assert msg.subtype == "normal"


def test_get_turn_messages(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")

    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t1", role="user",
        content="msg1",
    )
    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t1", role="assistant",
        content="msg2",
    )
    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t2", role="user",
        content="msg3",
    )

    t1_msgs = get_turn_messages(paths.chat_path, conversation_id=conv.id, turn_id="t1")
    assert len(t1_msgs) == 2
    t2_msgs = get_turn_messages(paths.chat_path, conversation_id=conv.id, turn_id="t2")
    assert len(t2_msgs) == 1


def test_increment_turn(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")
    assert conv.current_turn == 0

    t1 = increment_turn(paths.chat_path, conversation_id=conv.id)
    assert t1 == 1
    t2 = increment_turn(paths.chat_path, conversation_id=conv.id)
    assert t2 == 2


def test_tool_result_message(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")

    msg = add_message_with_turn(
        paths.chat_path,
        conversation_id=conv.id,
        turn_id="t1",
        role="tool",
        subtype="tool_result",
        content='{"tool_use_id":"tu_001","content":"result"}',
        tool_call_id="tu_001",
        meta='{"tool_name":"file_read","ok":true}',
    )
    assert msg.subtype == "tool_result"
    assert msg.tool_call_id == "tu_001"


def test_list_active_messages_with_subtype_boundary(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="test")

    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t1", role="user",
        content="msg1",
    )
    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t1", role="assistant",
        content="msg2",
    )
    # Compact boundary with subtype
    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t1", role="system",
        subtype="compact_boundary",
        content='{"type":"compact_boundary","boundary_id":"cb1"}',
    )
    add_message_with_turn(
        paths.chat_path, conversation_id=conv.id, turn_id="t2", role="user",
        content="msg3",
    )

    active = list_active_messages(paths.chat_path, conversation_id=conv.id)
    assert len(active) == 2  # boundary + msg3
    assert active[0].subtype == "compact_boundary"


def test_migration_idempotent(tmp_path: Path) -> None:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
    initialize_storage(paths)
    # Running again should not fail
    initialize_storage(paths)
    # Should be able to use new fields
    conv = create_conversation(paths.chat_path, title="test")
    assert conv.current_turn == 0
    assert conv.status == "active"


def test_initialize_storage_imports_existing_sqlite_files(tmp_path: Path) -> None:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")
    paths.global_dir.mkdir(parents=True)
    paths.project_dir.mkdir(parents=True)

    with sqlite3.connect(paths.config_path.with_name("config.sqlite")) as connection:
        connection.execute(
            """
            CREATE TABLE llm_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL,
                base_url TEXT,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE llm_models (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                thinking_enabled INTEGER NOT NULL,
                reasoning_effort TEXT NOT NULL,
                context_window INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO llm_channels
            VALUES (
                'channel-1', 'Migrated', 'openai_compatible',
                'https://example.test', 'sk-old', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO llm_models
            VALUES (
                'model-1', 'channel-1', 'gpt-test', 1, 1, 'high', 125000,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )

    with sqlite3.connect(paths.chat_path.with_name("chat.sqlite")) as connection:
        connection.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                total_output_tokens INTEGER NOT NULL,
                last_input_tokens INTEGER NOT NULL,
                compacted_message_count INTEGER NOT NULL,
                current_turn INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                subtype TEXT NOT NULL,
                tool_call_id TEXT,
                meta TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO conversations
            VALUES (
                'conv-1', 'Old chat', 3, 2, 0, 1, 'active',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO messages
            VALUES (
                'msg-1', 'conv-1', 'user', 'hello',
                '2026-01-01T00:00:01Z', 'turn-1', 'normal', NULL, '{}'
            )
            """
        )

    initialize_storage(paths)

    assert paths.config_path.exists()
    assert paths.chat_path.exists()
    assert list_llm_channels(paths.config_path)[0].name == "Migrated"
    assert get_primary_llm_model(paths.config_path)[1].name == "gpt-test"
    assert list_conversations(paths.chat_path)[0].title == "Old chat"
    assert list_messages(paths.chat_path, conversation_id="conv-1")[0].content == "hello"
