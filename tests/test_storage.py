import sqlite3
from pathlib import Path

import pytest

from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    add_message,
    create_conversation,
    create_llm_api_profile,
    get_default_llm_api_profile,
    initialize_storage,
    list_conversations,
    list_llm_api_profiles,
    list_messages,
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


def test_llm_api_profiles_support_openai_compatible_and_anthropic(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    openai_profile = create_llm_api_profile(
        paths.config_db,
        name="Local OpenAI Compatible",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
        model="qwen3",
        is_default=True,
    )
    anthropic_profile = create_llm_api_profile(
        paths.config_db,
        name="Claude",
        provider_type="anthropic",
        api_key="anthropic-key",
        model="claude-opus-4-7",
        is_default=True,
    )

    profiles = list_llm_api_profiles(paths.config_db)

    assert [profile.id for profile in profiles] == [anthropic_profile.id, openai_profile.id]
    assert profiles[0].is_default is True
    assert profiles[1].is_default is False
    assert get_default_llm_api_profile(paths.config_db) == anthropic_profile
    assert openai_profile.base_url == "http://localhost:11434/v1"


def test_invalid_provider_type_is_rejected(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))

    with pytest.raises(ValueError, match="Unsupported provider_type"):
        create_llm_api_profile(
            paths.config_db,
            name="Bad",
            provider_type="unknown",
            api_key="key",
            model="model",
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
