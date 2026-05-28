import asyncio
from pathlib import Path

import pytest

from flyinchat.mcp.adapter import MCPToolAdapter, _infer_risk_level, _normalize_schema
from flyinchat.tools.core import PermissionDecision, ToolContext, PermissionContext


class FakeSession:
    """Mock MCP session for testing."""

    def __init__(self, result=None, raise_exc=None):
        self._result = result
        self._raise_exc = raise_exc

    async def call_tool(self, tool_name, arguments=None):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


class FakeContent:
    def __init__(self, text: str):
        self.text = text


class FakeResult:
    def __init__(self, content=None, isError=False):
        self.content = content or []
        self.isError = isError


def test_adapter_naming() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="filesystem",
        tool_name="read_file",
        description="Read a file",
        input_schema=None,
        session=session,
    )
    assert adapter.name == "mcp_filesystem_read_file"


def test_adapter_risk_level_read() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read_file",
        description="Read contents of a file",
        input_schema=None,
        session=session,
    )
    assert adapter.risk_level == "low"


def test_adapter_risk_level_write() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="write_file",
        description="Write contents to a file",
        input_schema=None,
        session=session,
    )
    assert adapter.risk_level == "medium"


def test_adapter_risk_level_shell() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="exec",
        tool_name="run_command",
        description="Execute a shell command",
        input_schema=None,
        session=session,
    )
    assert adapter.risk_level == "high"


def test_adapter_requires_permission_low() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read_file",
        description="Read a file",
        input_schema=None,
        session=session,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    decision = adapter.requires_permission({}, ctx)
    assert decision == PermissionDecision(True, "")


def test_adapter_requires_permission_high() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="exec",
        tool_name="run_shell",
        description="Run a shell command",
        input_schema=None,
        session=session,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    decision = adapter.requires_permission({}, ctx)
    assert decision.ask_user is True


def test_adapter_input_schema_normalized() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read",
        description="Read file",
        input_schema={"properties": {"path": {"type": "string"}}},
        session=session,
    )
    schema = adapter.input_schema()
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "required" in schema


def test_adapter_input_schema_none() -> None:
    session = FakeSession()
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read",
        description="Read file",
        input_schema=None,
        session=session,
    )
    schema = adapter.input_schema()
    assert schema == {"type": "object", "properties": {}, "required": []}


def test_adapter_run_success() -> None:
    result = FakeResult(content=[FakeContent("file contents here")])
    session = FakeSession(result=result)
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read",
        description="Read file",
        input_schema=None,
        session=session,
        timeout_seconds=5,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    tool_result = asyncio.run(adapter.run({}, ctx))
    assert tool_result.ok is True
    assert "file contents here" in tool_result.content


def test_adapter_run_timeout() -> None:
    session = FakeSession(raise_exc=asyncio.TimeoutError())
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="slow_read",
        description="Slow read",
        input_schema=None,
        session=session,
        timeout_seconds=1,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    tool_result = asyncio.run(adapter.run({}, ctx))
    assert tool_result.ok is False
    assert tool_result.error_code == "PROVIDER_TIMEOUT"


def test_adapter_run_connection_error() -> None:
    session = FakeSession(raise_exc=ConnectionError("server gone"))
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read",
        description="Read file",
        input_schema=None,
        session=session,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    tool_result = asyncio.run(adapter.run({}, ctx))
    assert tool_result.ok is False
    assert tool_result.error_code == "TRANSPORT_UNAVAILABLE"


def test_adapter_run_generic_error() -> None:
    session = FakeSession(raise_exc=ValueError("bad args"))
    adapter = MCPToolAdapter(
        server_name="fs",
        tool_name="read",
        description="Read file",
        input_schema=None,
        session=session,
    )
    ctx = ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=Path("/tmp"),
        permission=PermissionContext(),
    )
    tool_result = asyncio.run(adapter.run({}, ctx))
    assert tool_result.ok is False
    assert tool_result.error_code == "SERVER_EXEC_ERROR"


def test_infer_risk_level_keywords() -> None:
    assert _infer_risk_level("delete", "delete a resource") == "medium"
    assert _infer_risk_level("create", "create something") == "medium"
    assert _infer_risk_level("exec", "execute process") == "high"
    assert _infer_risk_level("shell", "run shell command") == "high"
    assert _infer_risk_level("read", "read a file") == "low"
    assert _infer_risk_level("list", "list items") == "low"


def test_normalize_schema_defaults() -> None:
    assert _normalize_schema(None) == {"type": "object", "properties": {}, "required": []}
    assert _normalize_schema({}) == {"type": "object", "properties": {}, "required": []}
    schema = _normalize_schema({"properties": {"x": {"type": "int"}}})
    assert schema["type"] == "object"


# ── Permission gating tests ──

class FakeMCPTool:
    """Minimal fake Tool for testing executor gating."""
    name = "mcp_test_read"
    description = "test"
    version = "1.0"
    risk_level = "low"
    def input_schema(self): return {}
    def requires_permission(self, tool_input, context):
        return PermissionDecision(True, "")
    async def run(self, tool_input, context):
        from flyinchat.tools.core import ToolResult
        return ToolResult(ok=True, content="ok")


def _make_context(allowed=None, ask=None, denied=None):
    from flyinchat.tools.core import ToolContext, PermissionContext
    from pathlib import Path
    perm = PermissionContext(
        allowed_tools=allowed or {"file_read"},
        ask_tools=ask or {"file_write", "bash"},
        denied_tools=denied or set(),
        allowed_read_roots=[Path.cwd()],
        allowed_write_roots=[Path.cwd()],
    )
    return ToolContext(session_id="t", user_id="u", workspace_root=Path.cwd(), permission=perm)


def test_mcp_tool_is_ask_by_default():
    """MCP tools not in allowed/ask/denied lists should be 'ask' (not hard-deny)."""
    from flyinchat.tools.core import ToolRegistry, ToolExecutor
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    decision = executor._tool_allowed("mcp_test_read", _make_context())
    assert decision.ask_user is True, f"MCP tools should ask user, got allowed={decision.allowed} ask_user={decision.ask_user}"


def test_mcp_tool_in_allowed_is_allowed():
    """MCP tools explicitly in allowed_tools should be auto-allowed."""
    from flyinchat.tools.core import ToolRegistry, ToolExecutor
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    decision = executor._tool_allowed("mcp_test_read", _make_context(allowed={"mcp_test_read"}, ask=set()))
    assert decision.allowed is True


def test_mcp_tool_in_denied_is_denied():
    """MCP tools in denied_tools should be hard-denied."""
    from flyinchat.tools.core import ToolRegistry, ToolExecutor
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    decision = executor._tool_allowed("mcp_test_read", _make_context(allowed={"file_read"}, denied={"mcp_test_read"}))
    assert decision.allowed is False and decision.ask_user is False


def test_mcp_tool_autoadded_is_auto_allowed():
    """After add_auto_allow_tool, MCP tool should be auto-allowed without asking."""
    from flyinchat.tools.core import ToolRegistry, ToolExecutor
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    executor.add_auto_allow_tool("mcp_test_read")
    assert executor._is_tool_auto_allowed("mcp_test_read", {}) is True
    assert executor._is_tool_auto_allowed("mcp_other", {}) is False


def test_bash_auto_allow_still_works():
    """Existing bash command auto-allow should not be affected."""
    from flyinchat.tools.core import ToolRegistry, ToolExecutor
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    assert executor._is_tool_auto_allowed("bash", {"command": "ls -la"}) is True  # seed pattern
    assert executor._is_tool_auto_allowed("bash", {"command": "rm -rf /"}) is False
