import asyncio
from pathlib import Path
from typing import Any

from flyinchat.skills.models import RuntimeGuard
from flyinchat.tools.bash_tool import BashTool
from flyinchat.tools.core import PermissionContext, ToolContext, ToolExecutor, ToolRegistry, ToolResult


class DummyTool:
    name = "dummy"
    description = "dummy"
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def requires_permission(self, tool_input: dict[str, Any], context: ToolContext):
        from flyinchat.tools.core import PermissionDecision

        return PermissionDecision(True, "")

    async def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content="ran")


def _context(workspace: Path, guard: RuntimeGuard) -> ToolContext:
    return ToolContext(
        session_id="test",
        user_id="user",
        workspace_root=workspace,
        permission=PermissionContext(allowed_tools=None),
        turn_state={"runtime_guards": (guard,)},
    )


def test_deny_tool_guard_blocks_before_execution(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    guard = RuntimeGuard(
        guard_id="g1",
        skill_name="safe",
        guard_type="deny_tool",
        action="deny",
        reason="blocked",
        parameters={"tools": ["dummy"]},
    )

    result = asyncio.run(ToolExecutor(registry).execute("dummy", {}, _context(tmp_path, guard)))

    assert result.ok is False
    assert result.error_code == "SKILL_GUARD_DENIED"
    assert result.meta["skill_guard_id"] == "g1"


def test_approved_execution_cannot_bypass_deny_guard(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    guard = RuntimeGuard(
        guard_id="g1",
        skill_name="safe",
        guard_type="deny_tool",
        action="deny",
        reason="blocked",
        parameters={"tools": ["dummy"]},
    )

    result = asyncio.run(ToolExecutor(registry).execute_approved("dummy", {}, _context(tmp_path, guard)))

    assert result.ok is False
    assert result.error_code == "SKILL_GUARD_DENIED"


def test_bash_command_pattern_guard_blocks(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool())
    guard = RuntimeGuard(
        guard_id="g2",
        skill_name="safe",
        guard_type="deny_command_pattern",
        action="deny",
        reason="no remove",
        parameters={"patterns": ["rm "]},
    )

    result = asyncio.run(
        ToolExecutor(registry).execute("bash", {"command": "rm file.txt"}, _context(tmp_path, guard))
    )

    assert result.ok is False
    assert result.error_code == "SKILL_GUARD_DENIED"
