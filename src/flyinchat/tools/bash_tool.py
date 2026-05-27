import re
import shlex
import subprocess
from typing import Any

from .core import PermissionDecision, Tool, ToolContext, ToolResult

_CMD_SEPARATOR = re.compile(r'\s*(?:&&|\|\||[;&|\n])\s*')


class BashTool:
    name = "bash"
    description = (
        "Execute a shell command in the workspace directory. "
        "Use for running scripts, building, testing, or inspecting the filesystem."
    )
    version = "1.0.0"
    risk_level = "high"

    ALLOWED_COMMANDS: set[str] = {
        "ls", "cat", "head", "tail", "find", "grep", "wc",
        "sort", "uniq", "echo", "pwd", "date", "env",
        "git", "python", "python3", "pip", "npm", "npx",
        "mkdir", "cp", "mv", "rm", "touch", "chmod",
        "diff", "patch", "tar", "zip", "unzip", "curl", "wget",
        "make", "cargo", "go", "node", "tsc",
        "cd", "gcc", "g++", "clang", "clang++", "cmake",
        "./a.out", "./vector_demo", "./demo", "./test",
    }

    DENIED_PATTERNS: tuple[str, ...] = (
        "rm -rf /",
        "rm -rf ~",
        "rm -rf .",
        "sudo ",
        "su ",
        "chown",
        "mkfs",
        "dd if=",
        ">:",
        "| sh",
        "$(",
        "`",
        "/etc/passwd",
        "/etc/shadow",
        "~/.ssh",
    )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute in the workspace directory.",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "maximum": 120,
                    "description": "Timeout in seconds (max 120).",
                },
            },
            "required": ["command"],
        }

    def requires_permission(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionDecision:
        cmd = tool_input.get("command", "").strip()
        if not cmd:
            return PermissionDecision(False, "empty command")

        for pattern in self.DENIED_PATTERNS:
            if pattern in cmd:
                return PermissionDecision(
                    False, f"command matches denied pattern: {pattern}"
                )

        segments = [
            s.strip() for s in _CMD_SEPARATOR.split(cmd) if s.strip()
        ]
        for segment in segments:
            try:
                parts = shlex.split(segment)
            except ValueError as e:
                return PermissionDecision(False, f"invalid shell syntax in '{segment[:40]}': {e}")
            if not parts:
                continue
            base = parts[0]
            if base not in self.ALLOWED_COMMANDS and not self._is_executable(base):
                return PermissionDecision(False, f"command not in allowlist: {base}", ask_user=True)

        return PermissionDecision(True, "")

    @staticmethod
    def _is_executable(name: str) -> bool:
        return name.startswith("./") or name.startswith("/")

    async def run(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        cmd = tool_input.get("command", "").strip()
        timeout = min(int(tool_input.get("timeout", 30)), 120)

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(context.workspace_root),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                content=f"command timed out after {timeout}s",
                error_code="TIMEOUT",
            )

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = f"(exit code: {result.returncode})"

        max_len = 8000
        if len(output) > max_len:
            output = output[:max_len] + "\n... [output truncated]"

        return ToolResult(
            ok=(result.returncode == 0),
            content=output,
            data={"exit_code": result.returncode},
            error_code="NONZERO_EXIT" if result.returncode != 0 else None,
        )
