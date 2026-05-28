from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    transport: str  # "stdio" in phase 1
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerConfig | None:
        name = data.get("name")
        command = data.get("command")
        if not name or not command:
            return None
        transport = data.get("transport", "stdio")
        if transport != "stdio":
            return None
        return cls(
            name=name,
            transport=transport,
            command=command,
            args=data.get("args", []),
            env=data.get("env", {}),
            timeout_seconds=data.get("timeout_seconds", 30),
        )


@dataclass(frozen=True)
class MCPConfig:
    """Top-level MCP configuration."""
    servers: list[MCPServerConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPConfig:
        raw_servers = data.get("mcp_servers", [])
        servers = []
        for item in raw_servers:
            config = MCPServerConfig.from_dict(item)
            if config is not None:
                servers.append(config)
        return cls(servers=servers)
