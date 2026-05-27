import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.edit_tools import FileEditTool
from flyinchat.tools.file_tools import FileReadTool
from flyinchat.tools.core import (
    PermissionContext,
    PermissionDecision,
    ToolContext,
)


def _make_context(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="test",
        user_id="test-user",
        workspace_root=workspace,
        permission=PermissionContext(
            allowed_tools={"file_read", "file_edit", "file_write"},
            allowed_read_roots=[workspace],
            allowed_write_roots=[workspace],
        ),
    )


class TestFileEditToolPermission:
    def test_write_root_check(self, tmp_path: Path) -> None:
        tool = FileEditTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"file_path": "test.txt", "old_string": "a", "new_string": "b"}, ctx
        )
        assert decision.allowed is True

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        tool = FileEditTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"file_path": "/etc/passwd", "old_string": "a", "new_string": "b"}, ctx
        )
        assert decision.allowed is False


class TestFileEditToolExecution:
    def test_simple_replace(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        read_tool = FileReadTool()
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        asyncio.run(read_tool.run({"path": "test.txt"}, ctx))
        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "hello", "new_string": "hi"}, ctx
        ))

        assert result.ok is True
        assert f.read_text() == "hi world"
        assert result.data["changes"] == 1

    def test_replace_all(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo baz foo")
        read_tool = FileReadTool()
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        asyncio.run(read_tool.run({"path": "test.txt"}, ctx))
        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "foo", "new_string": "qux", "replace_all": True}, ctx
        ))

        assert result.ok is True
        assert f.read_text() == "qux bar qux baz qux"
        assert result.data["changes"] == 3

    def test_old_string_not_found(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        read_tool = FileReadTool()
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        asyncio.run(read_tool.run({"path": "test.txt"}, ctx))
        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "xyz", "new_string": "abc"}, ctx
        ))

        assert result.ok is False
        assert result.error_code == "STRING_NOT_FOUND"

    def test_requires_read_before_edit(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "hello", "new_string": "hi"}, ctx
        ))

        assert result.ok is False
        assert result.error_code == "FILE_NOT_READ"

    def test_multiple_occurrences_without_replace_all(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo")
        read_tool = FileReadTool()
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        asyncio.run(read_tool.run({"path": "test.txt"}, ctx))
        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "foo", "new_string": "qux"}, ctx
        ))

        assert result.ok is False
        assert result.error_code == "AMBIGUOUS_MATCH"

    def test_empty_old_string_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        read_tool = FileReadTool()
        edit_tool = FileEditTool()
        ctx = _make_context(tmp_path)

        asyncio.run(read_tool.run({"path": "test.txt"}, ctx))
        result = asyncio.run(edit_tool.run(
            {"file_path": "test.txt", "old_string": "", "new_string": "x"}, ctx
        ))

        assert result.ok is False
        assert result.error_code == "INVALID_INPUT"
