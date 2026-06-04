from pathlib import Path

from flyinchat.observability.config import ObservabilityConfig


def test_langfuse_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    for key in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(key, raising=False)

    config = ObservabilityConfig.from_env(tmp_path / "missing.env")

    assert config.enabled is False
    assert config.disabled_reason == "LANGFUSE_ENABLED is false"


def test_langfuse_enabled_without_keys_disables_safely(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    config = ObservabilityConfig.from_env(tmp_path / "missing.env")

    assert config.enabled is False
    assert config.disabled_reason == "Langfuse keys are missing"


def test_langfuse_enabled_with_keys(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("LANGFUSE_DEBUG", "yes")
    monkeypatch.setenv("AGENT_ENV", "test")
    monkeypatch.setenv("AGENT_VERSION", "v-test")

    config = ObservabilityConfig.from_env(tmp_path / "missing.env")

    assert config.enabled is True
    assert config.public_key == "pk-test"
    assert config.secret_key == "sk-test"
    assert config.host == "https://langfuse.example.com"
    assert config.debug is True
    assert config.agent_env == "test"
    assert config.agent_version == "v-test"
