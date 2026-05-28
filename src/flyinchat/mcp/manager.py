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

    async def connect_all(
        self,
        servers: list[MCPServerConfig],
        registry: Any,
        tool_context: Any,
    ) -> None:
        """Connect to all configured MCP servers and register their tools."""
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
            logger.info(
                "MCP server %s connected: %d tools registered",
                server.name,
                tool_count,
            )

        except Exception:
            await exit_stack.aclose()
            self._status[server.name] = "error"
            raise

    def get_status(self) -> dict[str, str]:
        """Return connection status for all configured servers."""
        return dict(self._status)

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
                logger.info("MCP server disconnected: %s", name)
            except asyncio.TimeoutError:
                logger.warning("MCP shutdown timed out for server: %s", name)
                self._status[name] = "error"
            except Exception:
                logger.exception("Error shutting down MCP server: %s", name)
                self._status[name] = "error"
