from __future__ import annotations

import logging
import time
from typing import Any

from ..tools.core import (
    PERMISSION_REQUIRED,
    PermissionDecision,
    Tool,
    ToolContext,
    ToolResult,
)

logger = logging.getLogger("flyinchat.mcp.adapter")

_WRITE_KEYWORDS = frozenset({"write", "modify", "delete", "create", "remove", "update", "edit"})
_SHELL_KEYWORDS = frozenset({"shell", "exec", "run", "command", "process"})


def _infer_risk_level(name: str, description: str) -> str:
    """Infer risk level from tool name and description."""
    text = f"{name} {description}".lower()
    for kw in _SHELL_KEYWORDS:
        if kw in text:
            return "high"
    for kw in _WRITE_KEYWORDS:
        if kw in text:
            return "medium"
    return "low"


def _normalize_schema(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an MCP tool schema to a valid JSON schema."""
    if raw is None:
        return {"type": "object", "properties": {}, "required": []}
    schema = dict(raw)
    if "type" not in schema:
        schema["type"] = "object"
    if "properties" not in schema:
        schema["properties"] = {}
    if "required" not in schema:
        schema["required"] = []
    return schema


class MCPToolAdapter(Tool):
    """Wraps a single MCP server tool as a Tool Protocol implementation."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any] | None,
        session: Any,
        timeout_seconds: int = 30,
    ) -> None:
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = description
        self._raw_schema = input_schema
        self._schema = _normalize_schema(input_schema)
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._risk_level = _infer_risk_level(tool_name, description)

    @property
    def name(self) -> str:
        return f"mcp_{self._server_name}_{self._tool_name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def risk_level(self) -> str:
        return self._risk_level

    def input_schema(self) -> dict[str, Any]:
        return self._schema

    def requires_permission(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionDecision:
        if self._risk_level == "high":
            return PermissionDecision(False, "MCP tool requires approval (high risk)", ask_user=True)
        if self._risk_level == "medium":
            return PermissionDecision(False, "MCP tool requires approval (medium risk)", ask_user=True)
        return PermissionDecision(True, "")

    async def run(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        t0 = time.time()
        try:
            import asyncio

            result = await asyncio.wait_for(
                self._session.call_tool(self._tool_name, arguments=tool_input),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - t0) * 1000)
            return ToolResult(
                ok=False,
                content=f"MCP tool call timed out after {self._timeout_seconds}s",
                error_code="PROVIDER_TIMEOUT",
                meta={"elapsed_ms": elapsed_ms, "timeout_seconds": self._timeout_seconds},
            )
        except ConnectionError as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return ToolResult(
                ok=False,
                content=f"MCP connection error: {e}",
                error_code="TRANSPORT_UNAVAILABLE",
                meta={"elapsed_ms": elapsed_ms},
            )
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return ToolResult(
                ok=False,
                content=f"MCP server error: {e}",
                error_code="SERVER_EXEC_ERROR",
                meta={"elapsed_ms": elapsed_ms},
            )

        elapsed_ms = int((time.time() - t0) * 1000)
        content = _extract_content(result)
        return ToolResult(
            ok=True,
            content=content,
            data={"raw": _serialize_result(result)},
            meta={"elapsed_ms": elapsed_ms, "server": self._server_name},
        )


def _extract_content(result: Any) -> str:
    """Extract text content from an MCP call_tool result."""
    if hasattr(result, "content") and result.content:
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif hasattr(item, "data"):
                parts.append(str(item.data))
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else "(empty result)"
    if hasattr(result, "isError") and result.isError:
        return "(tool returned error)"
    return str(result) if result else "(empty result)"


def _serialize_result(result: Any) -> Any:
    """Serialize MCP result for storage (best-effort)."""
    if result is None:
        return None
    if hasattr(result, "model_dump"):
        try:
            return result.model_dump()
        except Exception:
            pass
    if hasattr(result, "dict"):
        try:
            return result.dict()
        except Exception:
            pass
    return str(result)
