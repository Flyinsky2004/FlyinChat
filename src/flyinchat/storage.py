import json
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import Conversation, LLMChannel, LLMModel, Message
from .paths import AppPaths, resolve_app_paths
from .mcp.config import MCPConfig

_PROVIDER_TYPES = frozenset({"openai_compatible", "anthropic"})
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    provider_type: str
    base_url: str | None
    model_names: tuple[str, ...]
    context_window: int = 125_000
    max_output_tokens: int = 128_000


PROVIDER_PRESETS = {
    "deepseek": ProviderPreset(
        id="deepseek",
        name="DeepSeek",
        provider_type="anthropic",
        base_url="https://api.deepseek.com/anthropic",
        model_names=("deepseek-v4-pro", "deepseek-v4-flash"),
        context_window=1_000_000,
        max_output_tokens=128_000,
    )
}


def initialize_storage(paths: AppPaths | None = None) -> AppPaths:
    app_paths = paths if paths is not None else resolve_app_paths()
    initialize_config_store(app_paths.config_path)
    initialize_chat_store(app_paths.chat_path)
    return app_paths


def initialize_config_store(path: Path) -> None:
    if path.exists():
        store = _load_config_store(path)
    else:
        sqlite_path = path.with_name("config.sqlite")
        store = (
            _migrate_config_store(sqlite_path)
            if sqlite_path.exists()
            else _default_config_store()
        )
    _write_json(path, store)


def initialize_chat_store(path: Path) -> None:
    if path.exists():
        store = _load_chat_store(path)
    else:
        sqlite_path = path.with_name("chat.sqlite")
        store = (
            _migrate_chat_store(sqlite_path)
            if sqlite_path.exists()
            else _default_chat_store()
        )
    _write_json(path, store)


def create_llm_channel(
    config_path: Path,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    base_url: str | None = None,
) -> LLMChannel:
    _validate_channel_fields(name=name, provider_type=provider_type, api_key=api_key)
    now = _now_iso()
    channel = {
        "id": str(uuid4()),
        "name": name,
        "provider_type": provider_type,
        "base_url": base_url,
        "api_key": api_key,
        "created_at": now,
        "updated_at": now,
    }
    store = _load_config_store(config_path)
    next_store = {**store, "llm_channels": [*store["llm_channels"], channel]}
    _write_json(config_path, next_store)
    return _channel_from_dict(channel)


def create_channel_with_models(
    config_path: Path,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    model_names: Sequence[str],
    base_url: str | None = None,
    context_window: int = 125_000,
    max_output_tokens: int = 128_000,
) -> tuple[LLMChannel, list[LLMModel]]:
    _validate_channel_fields(name=name, provider_type=provider_type, api_key=api_key)
    cleaned_models = _clean_model_names(model_names)
    store = _load_config_store(config_path)
    channel_id = str(uuid4())
    now = _now_iso()
    channel = {
        "id": channel_id,
        "name": name,
        "provider_type": provider_type,
        "base_url": base_url,
        "api_key": api_key,
        "created_at": now,
        "updated_at": now,
    }
    has_primary_model = _has_primary_model(store)
    models = [
        {
            "id": str(uuid4()),
            "channel_id": channel_id,
            "name": model_name,
            "is_default": index == 0 and not has_primary_model,
            "thinking_enabled": True,
            "reasoning_effort": "high",
            "context_window": context_window,
            "max_output_tokens": max_output_tokens,
            "created_at": now,
            "updated_at": now,
        }
        for index, model_name in enumerate(cleaned_models)
    ]
    next_store = {
        **store,
        "llm_channels": [*store["llm_channels"], channel],
        "llm_models": [*store["llm_models"], *models],
    }
    _write_json(config_path, next_store)
    sorted_models = sorted(
        models,
        key=lambda item: (not item["is_default"], item["name"]),
    )
    return _channel_from_dict(channel), [
        _model_from_dict(model) for model in sorted_models
    ]


def create_preset_channel(
    config_path: Path, *, preset_id: str, api_key: str
) -> tuple[LLMChannel, list[LLMModel]]:
    preset = PROVIDER_PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(f"Unsupported provider preset: {preset_id}")

    return create_channel_with_models(
        config_path,
        name=preset.name,
        provider_type=preset.provider_type,
        base_url=preset.base_url,
        api_key=api_key,
        model_names=preset.model_names,
        context_window=preset.context_window,
        max_output_tokens=preset.max_output_tokens,
    )


def add_llm_model(
    config_path: Path,
    *,
    channel_id: str,
    name: str,
    is_default: bool = False,
    context_window: int = 125_000,
    max_output_tokens: int = 128_000,
) -> LLMModel:
    if not name.strip():
        raise ValueError("Model name is required")

    store = _load_config_store(config_path)
    if not any(channel["id"] == channel_id for channel in store["llm_channels"]):
        raise ValueError("Channel not found")
    if any(
        model["channel_id"] == channel_id and model["name"] == name
        for model in store["llm_models"]
    ):
        raise ValueError("Model already exists for channel")

    now = _now_iso()
    model = {
        "id": str(uuid4()),
        "channel_id": channel_id,
        "name": name,
        "is_default": is_default,
        "thinking_enabled": True,
        "reasoning_effort": "high",
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "created_at": now,
        "updated_at": now,
    }
    existing_models = [
        {**existing, "is_default": False}
        if is_default and existing["channel_id"] == channel_id
        else existing
        for existing in store["llm_models"]
    ]
    next_store = {**store, "llm_models": [*existing_models, model]}
    _write_json(config_path, next_store)
    return _model_from_dict(model)


def list_llm_channels(config_path: Path) -> list[LLMChannel]:
    store = _load_config_store(config_path)
    rows = sorted(
        store["llm_channels"],
        key=lambda item: (item["name"], item["created_at"]),
    )
    return [_channel_from_dict(row) for row in rows]


def list_llm_models(config_path: Path, *, channel_id: str | None = None) -> list[LLMModel]:
    store = _load_config_store(config_path)
    rows = store["llm_models"]
    if channel_id is not None:
        rows = [row for row in rows if row["channel_id"] == channel_id]
        rows = sorted(rows, key=lambda item: (not item["is_default"], item["name"]))
    else:
        rows = sorted(
            rows,
            key=lambda item: (
                item["channel_id"],
                not item["is_default"],
                item["name"],
            ),
        )
    return [_model_from_dict(row) for row in rows]


def get_primary_llm_model(config_path: Path) -> tuple[LLMChannel, LLMModel] | None:
    store = _load_config_store(config_path)
    default_models = [model for model in store["llm_models"] if model["is_default"]]
    if not default_models:
        return None
    channel_by_id = {channel["id"]: channel for channel in store["llm_channels"]}
    joined = [
        (channel_by_id[model["channel_id"]], model)
        for model in default_models
        if model["channel_id"] in channel_by_id
    ]
    if not joined:
        return None
    channel, model = sorted(
        joined,
        key=lambda pair: (pair[0]["name"], pair[1]["name"]),
    )[0]
    return _channel_from_dict(channel), _model_from_dict(model)


def set_primary_llm_model(config_path: Path, *, model_id: str) -> tuple[LLMChannel, LLMModel]:
    store = _load_config_store(config_path)
    target = next((model for model in store["llm_models"] if model["id"] == model_id), None)
    if target is None:
        raise ValueError("Model not found")

    now = _now_iso()
    next_models = [
        {
            **model,
            "is_default": model["id"] == model_id,
            "updated_at": now if model["id"] == model_id else model["updated_at"],
        }
        for model in store["llm_models"]
    ]
    next_store = {**store, "llm_models": next_models}
    _write_json(config_path, next_store)
    updated_model = next(model for model in next_models if model["id"] == model_id)
    channel = _require_channel(next_store, updated_model["channel_id"])
    return _channel_from_dict(channel), _model_from_dict(updated_model)


def set_model_thinking(config_path: Path, *, model_id: str, enabled: bool) -> LLMModel:
    return _update_model(config_path, model_id, {"thinking_enabled": enabled})


def set_model_reasoning_effort(config_path: Path, *, model_id: str, effort: str) -> LLMModel:
    if effort not in ("low", "medium", "high"):
        raise ValueError(f"Invalid reasoning effort: {effort}. Must be low, medium, or high.")
    return _update_model(config_path, model_id, {"reasoning_effort": effort})


def set_model_context_window(config_path: Path, *, model_id: str, context_window: int) -> LLMModel:
    return _update_model(config_path, model_id, {"context_window": context_window})


def create_conversation(chat_path: Path, *, title: str) -> Conversation:
    if not title.strip():
        raise ValueError("Conversation title is required")

    now = _now_iso()
    conversation = {
        "id": str(uuid4()),
        "title": title,
        "total_output_tokens": 0,
        "last_input_tokens": 0,
        "compacted_message_count": 0,
        "current_turn": 0,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    store = _load_chat_store(chat_path)
    next_store = {**store, "conversations": [*store["conversations"], conversation]}
    _write_json(chat_path, next_store)
    return _conversation_from_dict(conversation)


def get_conversation(chat_path: Path, *, conversation_id: str) -> Conversation | None:
    store = _load_chat_store(chat_path)
    row = next(
        (
            conversation
            for conversation in store["conversations"]
            if conversation["id"] == conversation_id
        ),
        None,
    )
    return _conversation_from_dict(row) if row is not None else None


def list_conversations(chat_path: Path) -> list[Conversation]:
    store = _load_chat_store(chat_path)
    rows = sorted(
        store["conversations"],
        key=lambda item: (item["updated_at"], item["created_at"]),
        reverse=True,
    )
    return [_conversation_from_dict(row) for row in rows]


def add_message(
    chat_path: Path,
    *,
    conversation_id: str,
    role: str,
    content: str,
    turn_id: str = "",
    subtype: str = "normal",
    tool_call_id: str | None = None,
    meta: str = "{}",
) -> Message:
    if role not in _MESSAGE_ROLES:
        raise ValueError(f"Unsupported message role: {role}")
    if not content:
        raise ValueError("Message content is required")

    store = _load_chat_store(chat_path)
    if not any(conversation["id"] == conversation_id for conversation in store["conversations"]):
        raise ValueError("Conversation not found")

    now = _now_iso()
    message = {
        "id": str(uuid4()),
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "created_at": now,
        "turn_id": turn_id,
        "subtype": subtype,
        "tool_call_id": tool_call_id,
        "meta": meta,
    }
    conversations = [
        {**conversation, "updated_at": now}
        if conversation["id"] == conversation_id
        else conversation
        for conversation in store["conversations"]
    ]
    next_store = {
        **store,
        "conversations": conversations,
        "messages": [*store["messages"], message],
    }
    _write_json(chat_path, next_store)
    return _message_from_dict(message)


def update_conversation_usage(
    chat_path: Path, *, conversation_id: str, total_output_tokens: int, last_input_tokens: int
) -> None:
    store = _load_chat_store(chat_path)
    now = _now_iso()
    conversations = [
        {
            **conversation,
            "total_output_tokens": total_output_tokens,
            "last_input_tokens": last_input_tokens,
            "updated_at": now,
        }
        if conversation["id"] == conversation_id
        else conversation
        for conversation in store["conversations"]
    ]
    _write_json(chat_path, {**store, "conversations": conversations})


def list_messages(chat_path: Path, *, conversation_id: str) -> list[Message]:
    store = _load_chat_store(chat_path)
    rows = [
        message
        for message in store["messages"]
        if message["conversation_id"] == conversation_id
    ]
    rows = sorted(rows, key=lambda item: item["created_at"])
    return [_message_from_dict(row) for row in rows]


def update_message_content(chat_path: Path, *, message_id: str, content: str) -> None:
    store = _load_chat_store(chat_path)
    messages = [
        {**message, "content": content} if message["id"] == message_id else message
        for message in store["messages"]
    ]
    _write_json(chat_path, {**store, "messages": messages})


def add_message_with_turn(
    chat_path: Path,
    *,
    conversation_id: str,
    turn_id: str,
    role: str,
    subtype: str = "normal",
    content: str,
    tool_call_id: str | None = None,
    meta: str = "{}",
) -> Message:
    return add_message(
        chat_path,
        conversation_id=conversation_id,
        role=role,
        content=content,
        turn_id=turn_id,
        subtype=subtype,
        tool_call_id=tool_call_id,
        meta=meta,
    )


def get_turn_messages(
    chat_path: Path, *, conversation_id: str, turn_id: str
) -> list[Message]:
    store = _load_chat_store(chat_path)
    rows = [
        message
        for message in store["messages"]
        if message["conversation_id"] == conversation_id and message["turn_id"] == turn_id
    ]
    rows = sorted(rows, key=lambda item: item["created_at"])
    return [_message_from_dict(row) for row in rows]


def increment_turn(chat_path: Path, *, conversation_id: str) -> int:
    store = _load_chat_store(chat_path)
    now = _now_iso()
    current_turn = 0
    conversations = []
    for conversation in store["conversations"]:
        if conversation["id"] == conversation_id:
            current_turn = int(conversation["current_turn"]) + 1
            conversations.append({**conversation, "current_turn": current_turn, "updated_at": now})
        else:
            conversations.append(conversation)
    _write_json(chat_path, {**store, "conversations": conversations})
    return current_turn


def update_conversation_compacted_count(
    chat_path: Path, *, conversation_id: str, count: int
) -> None:
    store = _load_chat_store(chat_path)
    now = _now_iso()
    conversations = [
        {**conversation, "compacted_message_count": count, "updated_at": now}
        if conversation["id"] == conversation_id
        else conversation
        for conversation in store["conversations"]
    ]
    _write_json(chat_path, {**store, "conversations": conversations})


def list_active_messages(chat_path: Path, *, conversation_id: str) -> list[Message]:
    all_msgs = list_messages(chat_path, conversation_id=conversation_id)
    boundary_idx: int | None = None
    for index, msg in enumerate(all_msgs):
        if msg.subtype == "compact_boundary":
            boundary_idx = index
            break
        try:
            parsed = json.loads(msg.content)
            if isinstance(parsed, dict) and parsed.get("type") == "compact_boundary":
                boundary_idx = index
                break
        except (json.JSONDecodeError, TypeError):
            pass

    if boundary_idx is None:
        return all_msgs

    start = boundary_idx
    if start > 0:
        prev = all_msgs[start - 1]
        if prev.subtype == "compact_summary":
            start = boundary_idx - 1
        else:
            try:
                parsed = json.loads(prev.content)
                if isinstance(parsed, dict) and parsed.get("type") == "compact_summary":
                    start = boundary_idx - 1
            except (json.JSONDecodeError, TypeError):
                pass

    return all_msgs[start:]


def get_app_setting(path: Path, key: str) -> str | None:
    store = _load_config_store(path)
    value = store["app_settings"].get(key)
    return str(value) if value is not None else None


def set_app_setting(path: Path, key: str, value: str) -> None:
    store = _load_config_store(path)
    settings = {**store["app_settings"], key: value}
    _write_json(path, {**store, "app_settings": settings})


def load_mcp_config(paths: AppPaths) -> MCPConfig:
    """Load MCP server configuration from config.json."""
    store = _load_config_store(paths.config_path)
    return MCPConfig.from_dict(store)


def _load_config_store(path: Path) -> dict[str, Any]:
    store = _load_json(path, _default_config_store)
    return {
        "schema_version": int(store.get("schema_version", _SCHEMA_VERSION)),
        "llm_channels": [_normalize_channel_dict(row) for row in store.get("llm_channels", [])],
        "llm_models": [_normalize_model_dict(row) for row in store.get("llm_models", [])],
        "app_settings": dict(store.get("app_settings", {})),
        "mcp_servers": list(store.get("mcp_servers", [])),
    }


def _load_chat_store(path: Path) -> dict[str, Any]:
    store = _load_json(path, _default_chat_store)
    return {
        "schema_version": int(store.get("schema_version", _SCHEMA_VERSION)),
        "conversations": [
            _normalize_conversation_dict(row)
            for row in store.get("conversations", [])
        ],
        "messages": [_normalize_message_dict(row) for row in store.get("messages", [])],
    }


def _load_json(path: Path, default_factory) -> dict[str, Any]:
    if not path.exists():
        return default_factory()
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return default_factory()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid storage file: {path}")
    return data


def _write_json(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def _default_config_store() -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "llm_channels": [],
        "llm_models": [],
        "app_settings": {},
    }


def _default_chat_store() -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "conversations": [],
        "messages": [],
    }


def _migrate_config_store(sqlite_path: Path) -> dict[str, Any]:
    with _connect_sqlite(sqlite_path) as connection:
        channels = [
            _normalize_channel_dict(row)
            for row in _fetch_sqlite_rows(connection, "llm_channels")
        ]
        models = [
            _normalize_model_dict(row)
            for row in _fetch_sqlite_rows(connection, "llm_models")
        ]
        settings = {
            str(row.get("key", "")): str(row.get("value", ""))
            for row in _fetch_sqlite_rows(connection, "app_settings")
            if row.get("key") is not None
        }
    return {
        "schema_version": _SCHEMA_VERSION,
        "llm_channels": channels,
        "llm_models": models,
        "app_settings": settings,
    }


def _migrate_chat_store(sqlite_path: Path) -> dict[str, Any]:
    with _connect_sqlite(sqlite_path) as connection:
        conversations = [
            _normalize_conversation_dict(row)
            for row in _fetch_sqlite_rows(connection, "conversations")
        ]
        messages = [
            _normalize_message_dict(row)
            for row in _fetch_sqlite_rows(connection, "messages")
        ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "conversations": conversations,
        "messages": messages,
    }


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _fetch_sqlite_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if exists is None:
        return []
    rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(row) for row in rows]


def _validate_channel_fields(*, name: str, provider_type: str, api_key: str) -> None:
    if provider_type not in _PROVIDER_TYPES:
        raise ValueError(f"Unsupported provider_type: {provider_type}")
    if not name.strip():
        raise ValueError("Channel name is required")
    if not api_key.strip():
        raise ValueError("API key is required")


def _clean_model_names(model_names: Sequence[str]) -> tuple[str, ...]:
    cleaned = tuple(
        dict.fromkeys(
            model_name.strip() for model_name in model_names if model_name.strip()
        )
    )
    if not cleaned:
        raise ValueError("At least one model is required")
    return cleaned


def _has_primary_model(store: dict[str, Any]) -> bool:
    return any(model["is_default"] for model in store["llm_models"])


def _update_model(config_path: Path, model_id: str, updates: dict[str, Any]) -> LLMModel:
    store = _load_config_store(config_path)
    now = _now_iso()
    found = False
    models = []
    for model in store["llm_models"]:
        if model["id"] == model_id:
            found = True
            models.append({**model, **updates, "updated_at": now})
        else:
            models.append(model)
    if not found:
        raise ValueError("Model not found")
    _write_json(config_path, {**store, "llm_models": models})
    return _model_from_dict(
        next(model for model in models if model["id"] == model_id)
    )


def _require_channel(store: dict[str, Any], channel_id: str) -> dict[str, Any]:
    channel = next(
        (item for item in store["llm_channels"] if item["id"] == channel_id),
        None,
    )
    if channel is None:
        raise ValueError("Channel not found")
    return channel


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_channel_dict(row: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "provider_type": str(row["provider_type"]),
        "base_url": row.get("base_url"),
        "api_key": str(row["api_key"]),
        "created_at": str(row.get("created_at") or now),
        "updated_at": str(row.get("updated_at") or now),
    }


def _normalize_model_dict(row: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(row["id"]),
        "channel_id": str(row["channel_id"]),
        "name": str(row["name"]),
        "is_default": bool(row.get("is_default", False)),
        "thinking_enabled": bool(row.get("thinking_enabled", True)),
        "reasoning_effort": str(row.get("reasoning_effort") or "high"),
        "context_window": int(row.get("context_window") or 125_000),
        "max_output_tokens": int(row.get("max_output_tokens") or 128_000),
        "created_at": str(row.get("created_at") or now),
        "updated_at": str(row.get("updated_at") or now),
    }


def _normalize_conversation_dict(row: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "total_output_tokens": int(row.get("total_output_tokens") or 0),
        "last_input_tokens": int(row.get("last_input_tokens") or 0),
        "compacted_message_count": int(row.get("compacted_message_count") or 0),
        "current_turn": int(row.get("current_turn") or 0),
        "status": str(row.get("status") or "active"),
        "created_at": str(row.get("created_at") or now),
        "updated_at": str(row.get("updated_at") or now),
    }


def _normalize_message_dict(row: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(row["id"]),
        "conversation_id": str(row["conversation_id"]),
        "role": str(row["role"]),
        "content": str(row["content"]),
        "created_at": str(row.get("created_at") or now),
        "turn_id": str(row.get("turn_id") or ""),
        "subtype": str(row.get("subtype") or "normal"),
        "tool_call_id": row.get("tool_call_id"),
        "meta": str(row.get("meta") or "{}"),
    }


def _channel_from_dict(row: dict[str, Any]) -> LLMChannel:
    return LLMChannel(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _model_from_dict(row: dict[str, Any]) -> LLMModel:
    return LLMModel(
        id=row["id"],
        channel_id=row["channel_id"],
        name=row["name"],
        is_default=bool(row["is_default"]),
        thinking_enabled=bool(row["thinking_enabled"]),
        reasoning_effort=row["reasoning_effort"],
        context_window=int(row["context_window"]),
        max_output_tokens=int(row.get("max_output_tokens", 384_000)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _conversation_from_dict(row: dict[str, Any]) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        total_output_tokens=int(row["total_output_tokens"]),
        last_input_tokens=int(row["last_input_tokens"]),
        compacted_message_count=int(row["compacted_message_count"]),
        current_turn=int(row["current_turn"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_dict(row: dict[str, Any]) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        turn_id=row["turn_id"],
        subtype=row["subtype"],
        tool_call_id=row["tool_call_id"],
        meta=row["meta"],
    )
