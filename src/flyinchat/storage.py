import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import Conversation, LLMApiProfile, Message
from .paths import AppPaths, resolve_app_paths

_PROVIDER_TYPES = frozenset({"openai_compatible", "anthropic"})
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
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
            CREATE TABLE IF NOT EXISTS llm_api_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL CHECK (provider_type IN ('openai_compatible', 'anthropic')),
                base_url TEXT,
                api_key TEXT NOT NULL,
                model TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_api_profiles_single_default
            ON llm_api_profiles (is_default)
            WHERE is_default = 1
            """
        )


def initialize_chat_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
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


def create_llm_api_profile(
    config_db: Path,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    is_default: bool = False,
) -> LLMApiProfile:
    if provider_type not in _PROVIDER_TYPES:
        raise ValueError(f"Unsupported provider_type: {provider_type}")
    if not name.strip():
        raise ValueError("Profile name is required")
    if not api_key.strip():
        raise ValueError("API key is required")
    if not model.strip():
        raise ValueError("Model is required")

    profile_id = str(uuid4())
    with _connect(config_db) as connection:
        if is_default:
            connection.execute("UPDATE llm_api_profiles SET is_default = 0")
        connection.execute(
            """
            INSERT INTO llm_api_profiles (id, name, provider_type, base_url, api_key, model, is_default)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (profile_id, name, provider_type, base_url, api_key, model, int(is_default)),
        )
        row = connection.execute(
            "SELECT * FROM llm_api_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()

    return _profile_from_row(row)


def list_llm_api_profiles(config_db: Path) -> list[LLMApiProfile]:
    with _connect(config_db) as connection:
        rows = connection.execute(
            """
            SELECT * FROM llm_api_profiles
            ORDER BY is_default DESC, name ASC, created_at ASC
            """
        ).fetchall()

    return [_profile_from_row(row) for row in rows]


def get_default_llm_api_profile(config_db: Path) -> LLMApiProfile | None:
    with _connect(config_db) as connection:
        row = connection.execute(
            "SELECT * FROM llm_api_profiles WHERE is_default = 1",
        ).fetchone()

    return _profile_from_row(row) if row is not None else None


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
        connection.execute("PRAGMA foreign_keys = ON")
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


def _profile_from_row(row: sqlite3.Row) -> LLMApiProfile:
    return LLMApiProfile(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        model=row["model"],
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
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
