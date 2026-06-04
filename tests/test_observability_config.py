import json
from pathlib import Path

from flyinchat.observability.config import ObservabilityConfig


def _write_config(path: Path, settings: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"app_settings": settings}), encoding="utf-8")


def test_langfuse_disabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path, {})

    config = ObservabilityConfig.from_config_store(config_path)

    assert config.enabled is False
    assert config.disabled_reason == "langfuse_enabled is false"


def test_langfuse_enabled_without_keys_disables_safely(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path, {"langfuse_enabled": "true"})

    config = ObservabilityConfig.from_config_store(config_path)

    assert config.enabled is False
    assert config.disabled_reason == "Langfuse keys are missing"


def test_langfuse_enabled_with_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(
        config_path,
        {
            "langfuse_enabled": "true",
            "langfuse_public_key": "pk-test",
            "langfuse_secret_key": "sk-test",
            "langfuse_host": "https://langfuse.example.com",
            "langfuse_debug": "yes",
            "agent_env": "test",
            "agent_version": "v-test",
        },
    )

    config = ObservabilityConfig.from_config_store(config_path)

    assert config.enabled is True
    assert config.public_key == "pk-test"
    assert config.secret_key == "sk-test"
    assert config.host == "https://langfuse.example.com"
    assert config.debug is True
    assert config.agent_env == "test"
    assert config.agent_version == "v-test"


def test_missing_config_file_returns_disabled(tmp_path: Path) -> None:
    config = ObservabilityConfig.from_config_store(tmp_path / "nonexistent.json")
    assert config.enabled is False
    assert config.disabled_reason == "langfuse_enabled is false"