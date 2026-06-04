from flyinchat.observability.sanitize import (
    REDACTED,
    is_sensitive_path,
    preview_text,
    preview_tool_result,
    sanitize_tool_args,
    sanitize_value,
    sha256_text,
)


def test_sensitive_keys_are_redacted_recursively() -> None:
    payload = {
        "api_key": "sk-secret",
        "nested": {"Authorization": "Bearer token", "safe": "value"},
        "items": [{"client_secret": "hidden"}],
    }

    sanitized = sanitize_value(payload)

    assert sanitized["api_key"] == REDACTED
    assert sanitized["nested"]["Authorization"] == REDACTED
    assert sanitized["nested"]["safe"] == "value"
    assert sanitized["items"][0]["client_secret"] == REDACTED


def test_sensitive_paths_are_detected() -> None:
    assert is_sensitive_path(".env") is True
    assert is_sensitive_path(".env.local") is True
    assert is_sensitive_path("private.pem") is True
    assert is_sensitive_path("id_ed25519") is True
    assert is_sensitive_path("src/app.py") is False


def test_preview_text_truncates_and_hashes() -> None:
    text = "abcdef"
    preview = preview_text(text, max_chars=3)

    assert preview.preview.startswith("abc")
    assert preview.truncated is True
    assert preview.original_length == 6
    assert preview.hash == sha256_text(text)


def test_tool_args_are_sanitized() -> None:
    args = sanitize_tool_args({"path": "a.py", "token": "secret"})

    assert args == {"path": "a.py", "token": REDACTED}


def test_sensitive_file_tool_result_is_redacted() -> None:
    result = preview_tool_result("file_read", {"path": ".env"}, "LANGFUSE_SECRET_KEY=sk\n")

    assert result["redacted"] is True
    assert "SECRET" not in result["preview"]
    assert result["path"] == ".env"
