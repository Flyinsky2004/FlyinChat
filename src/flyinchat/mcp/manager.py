from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from .adapter import MCPToolAdapter
from .config import MCPServerConfig

logger = logging.getLogger("flyinchat.mcp.manager")


class MCPManager:
    """Manages MCP server connections, tool discovery, and registration."""

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self._clients: dict[str, Any] = {}
        self._exit_stacks: dict[str, Any] = {}
        self._status: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._server_configs: dict[str, MCPServerConfig] = {}

    async def connect_all(
        self,
        servers: list[MCPServerConfig],
        registry: Any,
        tool_context: Any,
    ) -> None:
        """Connect to all configured MCP servers and register their tools."""
        for server in servers:
            self._server_configs[server.name] = server
        if not servers:
            logger.info("No MCP servers configured")
            return

        for server in servers:
            try:
                await self._connect_server(server, registry, tool_context)
            except Exception:
                logger.exception("Failed to connect to MCP server: %s", server.name)
                self._status[server.name] = "error"

    async def _connect_server(
        self,
        server: MCPServerConfig,
        registry: Any,
        tool_context: Any,
    ) -> None:
        """Connect to a single MCP server and register its tools."""
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self._status[server.name] = "connecting"
        self._server_configs[server.name] = server
        logger.info("Connecting to MCP server: %s", server.name)

        exit_stack = AsyncExitStack()
        self._exit_stacks[server.name] = exit_stack

        params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env={**server.env} if server.env else None,
        )

        try:
            stdio_transport = await exit_stack.enter_async_context(stdio_client(params))
            read_stream, write_stream = stdio_transport
            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            tools_result = await session.list_tools()
            tool_count = 0

            for tool in tools_result.tools:
                adapter = MCPToolAdapter(
                    server_name=server.name,
                    tool_name=tool.name,
                    description=tool.description or "",
                    input_schema=getattr(tool, "inputSchema", None),
                    session=session,
                    timeout_seconds=server.timeout_seconds,
                )
                try:
                    registry.register(adapter)
                    tool_count += 1
                    logger.info(
                        "Registered MCP tool: %s (risk=%s)",
                        adapter.name,
                        adapter.risk_level,
                    )
                except ValueError:
                    logger.warning(
                        "MCP tool name conflict, skipping: %s", adapter.name
                    )

            self._sessions[server.name] = session
            self._clients[server.name] = stdio_transport
            self._status[server.name] = "connected"
            self._errors.pop(server.name, None)
            logger.info(
                "MCP server %s connected: %d tools registered",
                server.name,
                tool_count,
            )

        except Exception as e:
            await exit_stack.aclose()
            self._status[server.name] = "error"
            self._errors[server.name] = str(e)
            logger.exception("Failed to connect to MCP server: %s", server.name)
            raise

    def get_status(self) -> dict[str, str]:
        """Return connection status for all configured servers."""
        return dict(self._status)

    def get_error(self, server_name: str) -> str | None:
        """Return error message for a server, or None if no error."""
        return self._errors.get(server_name)

    def get_server_config(self, server_name: str) -> MCPServerConfig | None:
        """Return server config by name."""
        return self._server_configs.get(server_name)

    async def reconnect_server(
        self,
        server: MCPServerConfig,
        registry: Any,
        tool_context: Any,
    ) -> int:
        """Disconnect and reconnect a single server, return tool count."""
        await self._disconnect_one(server.name)
        await self._connect_server(server, registry, tool_context)
        return sum(
            1 for tn in registry.list_tools() if tn.startswith(f"mcp_{server.name}_")
        )

    async def _disconnect_one(self, server_name: str) -> None:
        """Disconnect a single server."""
        exit_stack = self._exit_stacks.pop(server_name, None)
        if exit_stack is not None:
            try:
                await asyncio.wait_for(exit_stack.aclose(), timeout=5.0)
            except Exception:
                pass
        self._sessions.pop(server_name, None)
        self._clients.pop(server_name, None)
        self._status.pop(server_name, None)
        self._errors.pop(server_name, None)
        logger.info("MCP server disconnected: %s", server_name)

    async def shutdown(self) -> None:
        """Gracefully shut down all MCP connections."""
        for name in list(self._sessions.keys()):
            try:
                exit_stack = self._exit_stacks.pop(name, None)
                if exit_stack is not None:
                    await asyncio.wait_for(exit_stack.aclose(), timeout=5.0)
                self._sessions.pop(name, None)
                self._clients.pop(name, None)
                self._status[name] = "disconnected"
                self._errors.pop(name, None)
                logger.info("MCP server disconnected: %s", name)
            except asyncio.TimeoutError:
                logger.warning("MCP shutdown timed out for server: %s", name)
                self._status[name] = "error"
            except Exception:
                logger.exception("Error shutting down MCP server: %s", name)
                self._status[name] = "error"
