import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.grep_tool import GrepTool
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
            allowed_tools={"grep"},
            allowed_read_roots=[workspace],
        ),
    )


class TestGrepTool:
    def test_basic_match(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("hello world\nfoo bar\nhello again")
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "hello"}, ctx))
        assert result.ok is True
        assert "hello" in result.content

    def test_ignore_case(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("Hello World\nfoo bar")
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "hello", "ignore_case": True}, ctx))
        assert result.ok is True
        assert "Hello" in result.content

    def test_case_sensitive_no_match(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("Hello World")
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "hello"}, ctx))
        assert result.ok is True
        assert "No matches found" in result.content

    def test_include_filter(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("hello")
        (tmp_path / "b.txt").write_text("hello")
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "hello", "include": "*.py"}, ctx))
        assert result.ok is True
        assert "a.py" in result.content
        assert "b.txt" not in result.content

    def test_no_matches(self, tmp_path: Path) -> None:
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "xyznonexistent"}, ctx))
        assert result.ok is True
        assert "No matches found" in result.content

    def test_invalid_regex(self, tmp_path: Path) -> None:
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "["}, ctx))
        # rg handles this gracefully (returning no matches or an error),
        # Python fallback returns INVALID_INPUT
        if not result.ok:
            assert result.error_code in ("INVALID_INPUT", "TOOL_RUNTIME_ERROR")

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        tool = GrepTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"pattern": "test", "path": "/etc"}, ctx
        )
        assert decision.allowed is False
