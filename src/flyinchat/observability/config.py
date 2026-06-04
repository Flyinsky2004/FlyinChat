from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObservabilityConfig:
    enabled: bool
    public_key: str
    secret_key: str
    host: str
    debug: bool = False
    agent_env: str = "development"
    agent_version: str = "local"
    disabled_reason: str = ""

    @property
    def has_credentials(self) -> bool:
        return bool(self.public_key and self.secret_key)

    @classmethod
    def from_config_store(cls, config_path: Path) -> "ObservabilityConfig":
        settings = _load_app_settings(config_path)

        enabled = _bool_setting(settings, "langfuse_enabled", default=False)
        public_key = settings.get("langfuse_public_key", "").strip()
        secret_key = settings.get("langfuse_secret_key", "").strip()
        host = settings.get("langfuse_host", "https://cloud.langfuse.com").strip() or "https://cloud.langfuse.com"
        debug = _bool_setting(settings, "langfuse_debug", default=False)
        agent_env = settings.get("agent_env", "development").strip() or "development"
        agent_version = settings.get("agent_version", "local").strip() or "local"

        if not enabled:
            return cls(
                enabled=False,
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                debug=debug,
                agent_env=agent_env,
                agent_version=agent_version,
                disabled_reason="langfuse_enabled is false",
            )

        if not public_key or not secret_key:
            return cls(
                enabled=False,
                public_key="",
                secret_key="",
                host=host,
                debug=debug,
                agent_env=agent_env,
                agent_version=agent_version,
                disabled_reason="Langfuse keys are missing",
            )

        return cls(
            enabled=True,
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            debug=debug,
            agent_env=agent_env,
            agent_version=agent_version,
        )


def _load_app_settings(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    raw = data.get("app_settings", {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _bool_setting(settings: dict[str, str], key: str, *, default: bool) -> bool:
    raw = settings.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}