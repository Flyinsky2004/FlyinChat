from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"
DEFAULT_PREVIEW_CHARS = 8_000
TEST_OUTPUT_PREVIEW_CHARS = 20_000
GIT_DIFF_PREVIEW_CHARS = 12_000

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "access_key",
    "refresh_token",
    "client_secret",
)

_SENSITIVE_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.yaml",
)


@dataclass(frozen=True)
class TextPreview:
    preview: str
    hash: str
    truncated: bool
    original_length: int
    redacted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "preview": self.preview,
            "hash": self.hash,
            "truncated": self.truncated,
            "original_length": self.original_length,
            "redacted": self.redacted,
        }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def is_sensitive_path(path: str | Path) -> bool:
    name = Path(str(path)).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in _SENSITIVE_PATH_PATTERNS)


def preview_text(
    text: str,
    *,
    max_chars: int = DEFAULT_PREVIEW_CHARS,
    redacted: bool = False,
) -> TextPreview:
    text = str(text)
    if redacted:
        return TextPreview(
            preview=REDACTED,
            hash=sha256_text(text),
            truncated=False,
            original_length=len(text),
            redacted=True,
        )
    truncated = len(text) > max_chars
    preview = text[:max_chars]
    if truncated:
        preview = f"{preview}\n... [truncated {len(text) - max_chars} chars]"
    return TextPreview(
        preview=preview,
        hash=sha256_text(text),
        truncated=truncated,
        original_length=len(text),
    )


def sanitize_value(value: Any, *, parent_key: str = "") -> Any:
    if parent_key and is_sensitive_key(parent_key):
        return REDACTED

    if isinstance(value, dict):
        return {
            str(key): sanitize_value(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        if _looks_like_env_content(value):
            return REDACTED
        return value
    return value


def sanitize_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    raw = json.dumps(messages, ensure_ascii=False, default=str)
    sanitized = sanitize_value(messages)
    sanitized_raw = json.dumps(sanitized, ensure_ascii=False, default=str)
    preview = preview_text(sanitized_raw)
    return {
        "messages": sanitized,
        "preview": preview.preview,
        "hash": sha256_text(raw),
        "sanitized_hash": preview.hash,
        "truncated": preview.truncated,
        "original_length": preview.original_length,
    }


def sanitize_tool_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_value(tool_args)
    if not isinstance(sanitized, dict):
        return {}
    return sanitized


def preview_tool_result(
    tool_name: str,
    tool_args: dict[str, Any],
    content: str,
) -> dict[str, Any]:
    path = _extract_path(tool_args)
    if path and is_sensitive_path(path):
        return {
            "preview": "[REDACTED sensitive file content]",
            "hash": sha256_text(str(content)),
            "truncated": False,
            "original_length": len(str(content)),
            "redacted": True,
            "path": str(path),
        }

    max_chars = _preview_limit_for_tool(tool_name, tool_args)
    return preview_text(str(content), max_chars=max_chars).as_dict()


def _preview_limit_for_tool(tool_name: str, tool_args: dict[str, Any]) -> int:
    if tool_name == "bash":
        command = str(tool_args.get("command", "")).lower()
        if "pytest" in command or "test" in command:
            return TEST_OUTPUT_PREVIEW_CHARS
        if command.startswith("git diff"):
            return GIT_DIFF_PREVIEW_CHARS
    return DEFAULT_PREVIEW_CHARS


def _extract_path(tool_args: dict[str, Any]) -> str | None:
    for key in ("path", "file_path"):
        value = tool_args.get(key)
        if isinstance(value, str):
            return value
    return None


def _looks_like_env_content(value: str) -> bool:
    if len(value) > 20_000:
        return False
    lines = [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith("#")]
    if len(lines) < 2:
        return False
    assignments = 0
    for line in lines[:20]:
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key and key.replace("_", "").replace("-", "").isalnum():
            assignments += 1
    return assignments >= 2 and any(is_sensitive_key(line.split("=", 1)[0]) for line in lines if "=" in line)
