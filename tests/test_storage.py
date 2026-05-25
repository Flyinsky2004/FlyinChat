import sqlite3
from pathlib import Path

import pytest

from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    add_message,
    create_channel_with_models,
    create_conversation,
    create_llm_channel,
    create_preset_channel,
    get_primary_llm_model,
    initialize_storage,
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
    assert paths.config_db == home / ".flyinchat" / "config.sqlite"
    assert paths.chat_db == cwd / ".flyinchat" / "chat.sqlite"


def test_initialize_storage_creates_databases(tmp_path: Path) -> None:
    paths = resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project")

    initialized_paths = initialize_storage(paths)

    assert initialized_paths == paths
    assert paths.config_db.exists()
    assert paths.chat_db.exists()


def test_openai_compatible_channel_can_have_multiple_models(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    channel, models = create_channel_with_models(
        paths.config_db,
        name="Local",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
        model_names=("qwen3", "glm4"),
    )

    assert list_llm_channels(paths.config_db) == [channel]
    assert [model.name for model in models] == ["qwen3", "glm4"]
    assert list_llm_models(paths.config_db, channel_id=channel.id) == models
    assert models[0].is_default is True
    assert models[1].is_default is False
    assert get_primary_llm_model(paths.config_db) == (channel, models[0])


def test_setting_primary_model_moves_default(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    channel, models = create_channel_with_models(
        paths.config_db,
        name="Local",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
        model_names=("qwen3", "glm4"),
    )

    selected_channel, selected_model = set_primary_llm_model(paths.config_db, model_id=models[1].id)
    updated_models = list_llm_models(paths.config_db, channel_id=channel.id)

    assert selected_channel == channel
    assert selected_model.name == "glm4"
    assert get_primary_llm_model(paths.config_db) == (selected_channel, selected_model)
    assert [model.is_default for model in updated_models] == [True, False]
    assert updated_models[0].name == "glm4"


def test_anthropic_channel_can_have_models(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    channel, models = create_channel_with_models(
        paths.config_db,
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

    channel, models = create_preset_channel(paths.config_db, preset_id="deepseek", api_key="deepseek-key")

    assert channel.name == "DeepSeek"
    assert channel.provider_type == "anthropic"
    assert channel.base_url == "https://api.deepseek.com/anthropic"
    assert channel.api_key == "deepseek-key"
    assert [model.name for model in models] == ["deepseek-v4-pro", "deepseek-v4-flash"]


def test_invalid_provider_type_is_rejected(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="Unsupported provider_type"):
        create_llm_channel(
            paths.config_db,
            name="Bad",
            provider_type="unknown",
            api_key="key",
        )


def test_empty_model_list_is_rejected(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="At least one model"):
        create_channel_with_models(
            paths.config_db,
            name="Bad",
            provider_type="anthropic",
            api_key="key",
            model_names=(),
        )


def test_conversations_and_messages_are_project_local(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_a = initialize_storage(resolve_app_paths(home=home, cwd=tmp_path / "project-a"))
    project_b = initialize_storage(resolve_app_paths(home=home, cwd=tmp_path / "project-b"))

    conversation = create_conversation(project_a.chat_db, title="Project A chat")
    user_message = add_message(
        project_a.chat_db,
        conversation_id=conversation.id,
        role="user",
        content="Hello",
    )
    assistant_message = add_message(
        project_a.chat_db,
        conversation_id=conversation.id,
        role="assistant",
        content="Hi",
    )

    conversations = list_conversations(project_a.chat_db)

    assert len(conversations) == 1
    assert conversations[0].id == conversation.id
    assert conversations[0].title == conversation.title
    assert list_messages(project_a.chat_db, conversation_id=conversation.id) == [
        user_message,
        assistant_message,
    ]
    assert list_conversations(project_b.chat_db) == []


def test_message_requires_existing_conversation(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(sqlite3.IntegrityError):
        add_message(
            paths.chat_db,
            conversation_id="missing",
            role="user",
            content="Hello",
        )
