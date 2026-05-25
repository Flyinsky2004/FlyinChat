import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .models import Conversation, LLMChannel, LLMModel, Message
from .paths import AppPaths, resolve_app_paths

_PROVIDER_TYPES = frozenset({"openai_compatible", "anthropic"})
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    provider_type: str
    base_url: str | None
    model_names: tuple[str, ...]
    context_window: int = 125_000


PROVIDER_PRESETS = {
    "deepseek": ProviderPreset(
        id="deepseek",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com",
        model_names=("deepseek-v4-pro", "deepseek-v4-flash"),
        context_window=1_000_000,
    )
}


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_storage(paths: AppPaths | None = None) -> AppPaths:
    app_paths = paths if paths is not None else resolve_app_paths()
    initialize_config_db(app_paths.config_db)
    initialize_chat_db(app_paths.chat_db)
    return app_paths


def initialize_config_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL CHECK (provider_type IN ('openai_compatible', 'anthropic')),
                base_url TEXT,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_models (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
                thinking_enabled INTEGER NOT NULL DEFAULT 1,
                reasoning_effort TEXT NOT NULL DEFAULT 'high',
                context_window INTEGER NOT NULL DEFAULT 125000,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (channel_id) REFERENCES llm_channels (id) ON DELETE CASCADE,
                UNIQUE (channel_id, name)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_models_single_default_per_channel
            ON llm_models (channel_id)
            WHERE is_default = 1
            """
        )
        _migrate_config_db(connection)


def _migrate_config_db(connection: sqlite3.Connection) -> None:
    for column, default_val in [("thinking_enabled", 1), ("reasoning_effort", "'high'"), ("context_window", 125000)]:
        try:
            connection.execute(
                f"ALTER TABLE llm_models ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default_val}"
            )
        except sqlite3.OperationalError:
            pass


def initialize_chat_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                last_input_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
            ON messages (conversation_id, created_at)
            """
        )
        for column, default_val in [("total_output_tokens", 0), ("last_input_tokens", 0), ("compacted_message_count", 0)]:
            try:
                connection.execute(
                    f"ALTER TABLE conversations ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default_val}"
                )
            except sqlite3.OperationalError:
                pass


def create_llm_channel(
    config_db: Path,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    base_url: str | None = None,
) -> LLMChannel:
    _validate_channel_fields(name=name, provider_type=provider_type, api_key=api_key)

    channel_id = str(uuid4())
    with _connect(config_db) as connection:
        connection.execute(
            """
            INSERT INTO llm_channels (id, name, provider_type, base_url, api_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, name, provider_type, base_url, api_key),
        )
        row = connection.execute(
            "SELECT * FROM llm_channels WHERE id = ?",
            (channel_id,),
        ).fetchone()

    return _channel_from_row(row)


def create_channel_with_models(
    config_db: Path,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    model_names: Sequence[str],
    base_url: str | None = None,
    context_window: int = 125_000,
) -> tuple[LLMChannel, list[LLMModel]]:
    cleaned_models = _clean_model_names(model_names)
    channel_id = str(uuid4())

    with _connect(config_db) as connection:
        _validate_channel_fields(name=name, provider_type=provider_type, api_key=api_key)
        connection.execute(
            """
            INSERT INTO llm_channels (id, name, provider_type, base_url, api_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, name, provider_type, base_url, api_key),
        )
        has_primary_model = _has_primary_model(connection)
        for index, model_name in enumerate(cleaned_models):
            connection.execute(
                """
                INSERT INTO llm_models (id, channel_id, name, is_default, thinking_enabled, reasoning_effort, context_window)
                VALUES (?, ?, ?, ?, 1, 'high', ?)
                """,
                (str(uuid4()), channel_id, model_name, int(index == 0 and not has_primary_model), context_window),
            )
        channel_row = connection.execute(
            "SELECT * FROM llm_channels WHERE id = ?",
            (channel_id,),
        ).fetchone()
        model_rows = connection.execute(
            """
            SELECT * FROM llm_models
            WHERE channel_id = ?
            ORDER BY is_default DESC, name ASC
            """,
            (channel_id,),
        ).fetchall()

    return _channel_from_row(channel_row), [_model_from_row(row) for row in model_rows]


def create_preset_channel(config_db: Path, *, preset_id: str, api_key: str) -> tuple[LLMChannel, list[LLMModel]]:
    preset = PROVIDER_PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(f"Unsupported provider preset: {preset_id}")

    return create_channel_with_models(
        config_db,
        name=preset.name,
        provider_type=preset.provider_type,
        base_url=preset.base_url,
        api_key=api_key,
        model_names=preset.model_names,
        context_window=preset.context_window,
    )


def add_llm_model(config_db: Path, *, channel_id: str, name: str, is_default: bool = False, context_window: int = 125_000) -> LLMModel:
    if not name.strip():
        raise ValueError("Model name is required")

    model_id = str(uuid4())
    with _connect(config_db) as connection:
        if is_default:
            connection.execute(
                "UPDATE llm_models SET is_default = 0 WHERE channel_id = ?",
                (channel_id,),
            )
        connection.execute(
            """
            INSERT INTO llm_models (id, channel_id, name, is_default, thinking_enabled, reasoning_effort, context_window)
            VALUES (?, ?, ?, ?, 1, 'high', ?)
            """,
            (model_id, channel_id, name, int(is_default), context_window),
        )
        row = connection.execute(
            "SELECT * FROM llm_models WHERE id = ?",
            (model_id,),
        ).fetchone()

    return _model_from_row(row)


def list_llm_channels(config_db: Path) -> list[LLMChannel]:
    with _connect(config_db) as connection:
        rows = connection.execute(
            "SELECT * FROM llm_channels ORDER BY name ASC, created_at ASC",
        ).fetchall()

    return [_channel_from_row(row) for row in rows]


def list_llm_models(config_db: Path, *, channel_id: str | None = None) -> list[LLMModel]:
    with _connect(config_db) as connection:
        if channel_id is None:
            rows = connection.execute(
                "SELECT * FROM llm_models ORDER BY channel_id ASC, is_default DESC, name ASC",
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM llm_models
                WHERE channel_id = ?
                ORDER BY is_default DESC, name ASC
                """,
                (channel_id,),
            ).fetchall()

    return [_model_from_row(row) for row in rows]


def get_primary_llm_model(config_db: Path) -> tuple[LLMChannel, LLMModel] | None:
    with _connect(config_db) as connection:
        row = connection.execute(
            """
            SELECT
                c.id AS channel_id,
                c.name AS channel_name,
                c.provider_type,
                c.base_url,
                c.api_key,
                c.created_at AS channel_created_at,
                c.updated_at AS channel_updated_at,
                m.id AS model_id,
                m.name AS model_name,
                m.is_default,
                m.thinking_enabled,
                m.reasoning_effort,
                m.context_window,
                m.created_at AS model_created_at,
                m.updated_at AS model_updated_at
            FROM llm_models m
            JOIN llm_channels c ON c.id = m.channel_id
            WHERE m.is_default = 1
            ORDER BY c.name ASC, m.name ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    return _channel_model_from_joined_row(row)


def set_primary_llm_model(config_db: Path, *, model_id: str) -> tuple[LLMChannel, LLMModel]:
    with _connect(config_db) as connection:
        row = connection.execute(
            "SELECT * FROM llm_models WHERE id = ?",
            (model_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Model not found")

        connection.execute("UPDATE llm_models SET is_default = 0")
        connection.execute(
            "UPDATE llm_models SET is_default = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (model_id,),
        )
        joined_row = connection.execute(
            """
            SELECT
                c.id AS channel_id,
                c.name AS channel_name,
                c.provider_type,
                c.base_url,
                c.api_key,
                c.created_at AS channel_created_at,
                c.updated_at AS channel_updated_at,
                m.id AS model_id,
                m.name AS model_name,
                m.is_default,
                m.thinking_enabled,
                m.reasoning_effort,
                m.context_window,
                m.created_at AS model_created_at,
                m.updated_at AS model_updated_at
            FROM llm_models m
            JOIN llm_channels c ON c.id = m.channel_id
            WHERE m.id = ?
            """,
            (model_id,),
        ).fetchone()

    return _channel_model_from_joined_row(joined_row)


def set_model_thinking(config_db: Path, *, model_id: str, enabled: bool) -> LLMModel:
    with _connect(config_db) as connection:
        connection.execute(
            "UPDATE llm_models SET thinking_enabled = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (int(enabled), model_id),
        )
        row = connection.execute("SELECT * FROM llm_models WHERE id = ?", (model_id,)).fetchone()
    return _model_from_row(row)


def set_model_reasoning_effort(config_db: Path, *, model_id: str, effort: str) -> LLMModel:
    if effort not in ("low", "medium", "high"):
        raise ValueError(f"Invalid reasoning effort: {effort}. Must be low, medium, or high.")
    with _connect(config_db) as connection:
        connection.execute(
            "UPDATE llm_models SET reasoning_effort = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (effort, model_id),
        )
        row = connection.execute("SELECT * FROM llm_models WHERE id = ?", (model_id,)).fetchone()
    return _model_from_row(row)


def set_model_context_window(config_db: Path, *, model_id: str, context_window: int) -> LLMModel:
    with _connect(config_db) as connection:
        connection.execute(
            "UPDATE llm_models SET context_window = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (context_window, model_id),
        )
        row = connection.execute("SELECT * FROM llm_models WHERE id = ?", (model_id,)).fetchone()
    return _model_from_row(row)


def create_conversation(chat_db: Path, *, title: str) -> Conversation:
    if not title.strip():
        raise ValueError("Conversation title is required")

    conversation_id = str(uuid4())
    with _connect(chat_db) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?)",
            (conversation_id, title),
        )
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

    return _conversation_from_row(row)


def get_conversation(chat_db: Path, *, conversation_id: str) -> Conversation | None:
    with _connect(chat_db) as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None
    return _conversation_from_row(row)


def list_conversations(chat_db: Path) -> list[Conversation]:
    with _connect(chat_db) as connection:
        rows = connection.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC, created_at DESC",
        ).fetchall()

    return [_conversation_from_row(row) for row in rows]


def add_message(chat_db: Path, *, conversation_id: str, role: str, content: str) -> Message:
    if role not in _MESSAGE_ROLES:
        raise ValueError(f"Unsupported message role: {role}")
    if not content:
        raise ValueError("Message content is required")

    message_id = str(uuid4())
    with _connect(chat_db) as connection:
        connection.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (conversation_id,),
        )
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()

    return _message_from_row(row)


def update_conversation_usage(
    chat_db: Path, *, conversation_id: str, total_output_tokens: int, last_input_tokens: int
) -> None:
    with _connect(chat_db) as connection:
        connection.execute(
            """
            UPDATE conversations
            SET total_output_tokens = ?, last_input_tokens = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (total_output_tokens, last_input_tokens, conversation_id),
        )


def list_messages(chat_db: Path, *, conversation_id: str) -> list[Message]:
    with _connect(chat_db) as connection:
        rows = connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()

    return [_message_from_row(row) for row in rows]


def update_message_content(chat_db: Path, *, message_id: str, content: str) -> None:
    with _connect(chat_db) as connection:
        connection.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (content, message_id),
        )


def update_conversation_compacted_count(
    chat_db: Path, *, conversation_id: str, count: int
) -> None:
    with _connect(chat_db) as connection:
        connection.execute(
            """
            UPDATE conversations
            SET compacted_message_count = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (count, conversation_id),
        )


def list_active_messages(chat_db: Path, *, conversation_id: str) -> list[Message]:
    """Load messages for API use, skipping pre-compact messages."""
    all_msgs = list_messages(chat_db, conversation_id=conversation_id)
    boundary_idx: int | None = None
    for i, msg in enumerate(all_msgs):
        try:
            parsed = json.loads(msg.content)
            if isinstance(parsed, dict) and parsed.get("type") == "compact_boundary":
                boundary_idx = i
        except (json.JSONDecodeError, TypeError):
            pass

    if boundary_idx is None:
        return all_msgs

    start = boundary_idx
    if start > 0:
        try:
            prev = json.loads(all_msgs[start - 1].content)
            if isinstance(prev, dict) and prev.get("type") == "compact_summary":
                start = boundary_idx - 1
        except (json.JSONDecodeError, TypeError):
            pass

    return all_msgs[start:]


def _validate_channel_fields(*, name: str, provider_type: str, api_key: str) -> None:
    if provider_type not in _PROVIDER_TYPES:
        raise ValueError(f"Unsupported provider_type: {provider_type}")
    if not name.strip():
        raise ValueError("Channel name is required")
    if not api_key.strip():
        raise ValueError("API key is required")


def _clean_model_names(model_names: Sequence[str]) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(model_name.strip() for model_name in model_names if model_name.strip()))
    if not cleaned:
        raise ValueError("At least one model is required")
    return cleaned


def _has_primary_model(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM llm_models WHERE is_default = 1 LIMIT 1",
    ).fetchone()
    return row is not None


def _channel_from_row(row: sqlite3.Row) -> LLMChannel:
    return LLMChannel(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _model_from_row(row: sqlite3.Row) -> LLMModel:
    return LLMModel(
        id=row["id"],
        channel_id=row["channel_id"],
        name=row["name"],
        is_default=bool(row["is_default"]),
        thinking_enabled=bool(row["thinking_enabled"]),
        reasoning_effort=row["reasoning_effort"],
        context_window=row["context_window"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _channel_model_from_joined_row(row: sqlite3.Row) -> tuple[LLMChannel, LLMModel]:
    return (
        LLMChannel(
            id=row["channel_id"],
            name=row["channel_name"],
            provider_type=row["provider_type"],
            base_url=row["base_url"],
            api_key=row["api_key"],
            created_at=row["channel_created_at"],
            updated_at=row["channel_updated_at"],
        ),
        LLMModel(
            id=row["model_id"],
            channel_id=row["channel_id"],
            name=row["model_name"],
            is_default=bool(row["is_default"]),
            thinking_enabled=bool(row["thinking_enabled"]),
            reasoning_effort=row["reasoning_effort"],
            context_window=row["context_window"],
            created_at=row["model_created_at"],
            updated_at=row["model_updated_at"],
        ),
    )


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        total_output_tokens=row["total_output_tokens"],
        last_input_tokens=row["last_input_tokens"],
        compacted_message_count=row["compacted_message_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
    )
