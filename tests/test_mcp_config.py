import json
from pathlib import Path

from flyinchat.mcp.config import MCPConfig, MCPServerConfig
from flyinchat.paths import resolve_app_paths
from flyinchat.storage import initialize_storage, load_mcp_config


def test_server_config_from_dict_valid() -> None:
    data = {
        "name": "filesystem",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {"HOME": "/tmp"},
        "timeout_seconds": 60,
    }
    config = MCPServerConfig.from_dict(data)
    assert config is not None
    assert config.name == "filesystem"
    assert config.command == "npx"
    assert config.timeout_seconds == 60


def test_server_config_from_dict_missing_name() -> None:
    data = {"command": "npx"}
    assert MCPServerConfig.from_dict(data) is None


def test_server_config_from_dict_missing_command() -> None:
    data = {"name": "test"}
    assert MCPServerConfig.from_dict(data) is None


def test_server_config_skips_non_stdio() -> None:
    data = {"name": "test", "transport": "http", "command": "http://localhost"}
    assert MCPServerConfig.from_dict(data) is None


def test_mcp_config_from_dict_empty() -> None:
    config = MCPConfig.from_dict({})
    assert config.servers == []


def test_mcp_config_from_dict_with_servers() -> None:
    data = {
        "mcp_servers": [
            {"name": "fs", "command": "npx", "args": ["test"]},
            {"name": "skip", "command": None},
        ]
    }
    config = MCPConfig.from_dict(data)
    assert len(config.servers) == 1
    assert config.servers[0].name == "fs"


def test_load_mcp_config_no_servers(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    config = load_mcp_config(paths)
    assert config.servers == []


def test_load_mcp_config_with_servers(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    store = json.loads(paths.config_path.read_text())
    store["mcp_servers"] = [
        {"name": "fs", "command": "npx", "args": ["test"], "timeout_seconds": 45},
    ]
    paths.config_path.write_text(json.dumps(store))
    config = load_mcp_config(paths)
    assert len(config.servers) == 1
    assert config.servers[0].name == "fs"
    assert config.servers[0].timeout_seconds == 45
