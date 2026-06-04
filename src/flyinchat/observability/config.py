from __future__ import annotations

import os
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
    def from_env(cls, env_path: Path | None = None) -> "ObservabilityConfig":
        _load_dotenv(env_path)

        enabled = _env_bool("LANGFUSE_ENABLED", default=False)
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()
        debug = _env_bool("LANGFUSE_DEBUG", default=False)
        agent_env = os.getenv("AGENT_ENV", "development").strip() or "development"
        agent_version = os.getenv("AGENT_VERSION", "local").strip() or "local"

        if not enabled:
            return cls(
                enabled=False,
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                debug=debug,
                agent_env=agent_env,
                agent_version=agent_version,
                disabled_reason="LANGFUSE_ENABLED is false",
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


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _load_dotenv(env_path: Path | None) -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    if env_path is not None:
        load_dotenv(env_path)
        return
    load_dotenv()
