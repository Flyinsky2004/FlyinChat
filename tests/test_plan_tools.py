import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.plan_tools import (
    EnterPlanModeTool,
    ExitPlanModeTool,
    TodoWriteTool,
)
from flyinchat.tools.core import (
    PermissionContext,
    ToolContext,
)


def _make_context(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="test",
        user_id="test-user",
        workspace_root=workspace,
        permission=PermissionContext(
            allowed_tools={"todo_write", "enter_plan_mode", "exit_plan_mode"},
        ),
    )


class TestTodoWriteTool:
    def test_basic_todo_list(self, tmp_path: Path) -> None:
        tool = TodoWriteTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({
            "todos": [
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "in_progress"},
                {"content": "Task 3", "status": "pending"},
            ],
        }, ctx))
        assert result.ok is True
        assert "[x]" in result.content
        assert "[>]" in result.content
        assert "[ ]" in result.content
        assert "1 done" in result.content
        assert "1 in progress" in result.content
        assert "1 pending" in result.content

    def test_empty_todo_list(self, tmp_path: Path) -> None:
        tool = TodoWriteTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"todos": []}, ctx))
        assert result.ok is True

    def test_always_permitted(self, tmp_path: Path) -> None:
        tool = TodoWriteTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission({"todos": []}, ctx)
        assert decision.allowed is True


class TestPlanModeTools:
    def test_enter_plan_mode(self, tmp_path: Path) -> None:
        tool = EnterPlanModeTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"plan_context": "Refactor auth module"}, ctx))
        assert result.ok is True
        assert "plan mode" in result.content.lower()
        assert ctx.turn_state.get("plan_mode") is True
        assert ctx.turn_state.get("plan_context") == "Refactor auth module"

    def test_exit_plan_mode(self, tmp_path: Path) -> None:
        tool = ExitPlanModeTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"plan_content": "1. Do X\n2. Do Y"}, ctx))
        assert result.ok is True
        assert ctx.turn_state.get("plan_mode") is False
        assert "1. Do X" in ctx.turn_state.get("plan_output", "")
