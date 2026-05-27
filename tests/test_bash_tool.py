import asyncio
import platform
from pathlib import Path

import pytest

from flyinchat.tools.bash_tool import BashTool
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
            allowed_tools={"bash"},
            allowed_read_roots=[workspace],
            allowed_write_roots=[workspace],
        ),
    )


class TestBashToolPermission:
    def test_allowed_command_passes(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"command": "echo hello"}, ctx
        )
        assert decision.allowed is True

    def test_denied_sudo_blocked(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"command": "sudo rm -rf /"}, ctx
        )
        assert decision.allowed is False
        assert "denied pattern" in decision.reason.lower()

    def test_denied_rm_rf_root_blocked(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"command": "rm -rf /"}, ctx
        )
        assert decision.allowed is False

    def test_unknown_command_blocked(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"command": "malware --evil"}, ctx
        )
        assert decision.allowed is False
        assert "not in allowlist" in decision.reason.lower()

    def test_empty_command_blocked(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission({"command": ""}, ctx)
        assert decision.allowed is False

    def test_allowed_git_status(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission(
            {"command": "git status"}, ctx
        )
        assert decision.allowed is True


class TestBashToolExecution:
    def test_echo_output(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"command": "echo hello world"}, ctx))
        assert result.ok is True
        assert "hello world" in result.content

    def test_ls_in_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "afile.txt").write_text("data")
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"command": "ls"}, ctx))
        assert result.ok is True
        assert "afile.txt" in result.content

    def test_nonzero_exit(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"command": "exit 1"}, ctx))
        assert result.ok is False
        assert result.error_code == "NONZERO_EXIT"
        assert result.data.get("exit_code") == 1

    def test_timeout(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"command": "sleep 60", "timeout": 1}, ctx))
        assert result.ok is False
        assert result.error_code == "TIMEOUT"

    def test_nonexistent_command(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run(
            {"command": "nonexistent_binary_xyz"}, ctx
        ))
        assert result.ok is False
        assert result.data.get("exit_code") != 0

    def test_pwd_is_workspace(self, tmp_path: Path) -> None:
        tool = BashTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"command": "pwd"}, ctx))
        assert result.ok is True
        resolved = str(tmp_path.resolve())
        assert resolved in result.content
