import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.glob_tool import GlobTool
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
            allowed_tools={"glob"},
            allowed_read_roots=[workspace],
        ),
    )


class TestGlobTool:
    def test_basic_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        tool = GlobTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "*.py"}, ctx))
        assert result.ok is True
        assert "a.py" in result.content
        assert "b.py" in result.content
        assert "c.txt" not in result.content

    def test_recursive_pattern(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.py").write_text("")
        (sub / "nested.py").write_text("")
        tool = GlobTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "**/*.py"}, ctx))
        assert result.ok is True
        assert "root.py" in result.content
        assert "sub/nested.py" in result.content

    def test_no_matches(self, tmp_path: Path) -> None:
        tool = GlobTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"pattern": "*.rs"}, ctx))
        assert result.ok is True
        assert "No files match" in result.content

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        tool = GlobTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"pattern": "*.py", "path": "/etc"}, ctx
        )
        assert decision.allowed is False
