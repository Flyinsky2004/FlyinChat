import asyncio

import pytest

from flyinchat.mcp.config import MCPServerConfig
from flyinchat.mcp.manager import MCPManager
from flyinchat.tools.core import ToolRegistry


def test_connect_all_empty_servers() -> None:
    asyncio.run(_test_connect_all_empty_servers())


async def _test_connect_all_empty_servers() -> None:
    manager = MCPManager()
    registry = ToolRegistry()
    await manager.connect_all([], registry, None)
    assert manager.get_status() == {}


def test_manager_status_tracking() -> None:
    manager = MCPManager()
    manager._status["test_server"] = "connected"
    manager._status["bad_server"] = "error"
    status = manager.get_status()
    assert status["test_server"] == "connected"
    assert status["bad_server"] == "error"


def test_shutdown_clears_status() -> None:
    asyncio.run(_test_shutdown_clears_status())


async def _test_shutdown_clears_status() -> None:
    manager = MCPManager()
    manager._status["server1"] = "connected"
    manager._sessions["server1"] = None
    await manager.shutdown()
    assert manager.get_status().get("server1") == "disconnected"
    assert "server1" not in manager._sessions


def test_shutdown_handles_timeout() -> None:
    asyncio.run(_test_shutdown_handles_timeout())


async def _test_shutdown_handles_timeout() -> None:
    manager = MCPManager()
    manager._status["slow_server"] = "connected"
    manager._sessions["slow_server"] = None
    await manager.shutdown()
    status = manager.get_status()
    assert "slow_server" in status
