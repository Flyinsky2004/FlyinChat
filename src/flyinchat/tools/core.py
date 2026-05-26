from __future__ import annotations

import logging
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger("flyinchat.tools")

PERMISSION_REQUIRED = "PERMISSION_REQUIRED"

SEED_AUTO_ALLOW_PATTERNS: set[str] = {
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "find",
    "echo", "date", "pwd", "which", "file", "stat", "sort", "uniq",
    "du", "df", "ps", "env", "printenv", "tree",
    "basename", "dirname", "realpath", "readlink",
    "cut", "tr", "diff", "jq",
    "md5sum", "sha1sum", "sha256sum",
    "git status", "git log", "git diff", "git show", "git branch",
    "git stash list", "git remote", "git ls-files", "git tag",
    "git rev-parse", "git config --get",
}


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str = ""
    ask_user: bool = False


@dataclass
class PermissionContext:
    allowed_tools: Optional[set[str]] = None
    denied_tools: set[str] = field(default_factory=set)
    ask_tools: set[str] = field(default_factory=set)
    allowed_read_roots: List[Path] = field(default_factory=list)
    allowed_write_roots: List[Path] = field(default_factory=list)


@dataclass
class ToolContext:
    session_id: str
    user_id: str
    workspace_root: Path
    permission: PermissionContext
    feature_flags: Dict[str, bool] = field(default_factory=dict)
    emit_event: Optional[Callable[[str, Dict[str, Any]], None]] = None


class Tool(Protocol):
    name: str
    description: str
    version: str
    risk_level: str

    def input_schema(self) -> Dict[str, Any]:
        ...

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        ...

    def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"tool not found: {name}")
        return self._tools[name]

    def list_tools(self) -> List[str]:
        return sorted(self._tools.keys())

    @property
    def tools(self) -> List[Tool]:
        return list(self._tools.values())


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.command_auto_allowlist: set[str] = set(SEED_AUTO_ALLOW_PATTERNS)

    def add_command_to_allowlist(self, pattern: str) -> None:
        self.command_auto_allowlist.add(pattern)

    def _is_command_auto_allowed(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> bool:
        if tool_name != "bash":
            return False
        cmd = tool_input.get("command", "").strip()
        if not cmd:
            return False
        for pattern in self.command_auto_allowlist:
            if cmd == pattern or cmd.startswith(pattern + " "):
                return True
        return False

    def _emit(self, context: ToolContext, event: str, payload: Dict[str, Any]) -> None:
        if context.emit_event:
            context.emit_event(event, payload)

    def _tool_allowed(self, tool_name: str, context: ToolContext) -> PermissionDecision:
        p = context.permission
        if tool_name in p.denied_tools:
            return PermissionDecision(False, f"tool denied: {tool_name}")
        if p.allowed_tools is not None and tool_name in p.allowed_tools:
            return PermissionDecision(True, "")
        if tool_name in p.ask_tools:
            return PermissionDecision(False, f"requires user approval: {tool_name}", ask_user=True)
        if p.allowed_tools is None:
            return PermissionDecision(True, "")
        return PermissionDecision(False, f"tool not in allow list: {tool_name}")

    def execute(self, tool_name: str, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        t0 = time.time()
        self._emit(context, "tool.start", {"tool": tool_name, "input": tool_input})

        try:
            tool = self.registry.get(tool_name)
        except KeyError as e:
            result = ToolResult(ok=False, content=str(e), error_code="TOOL_NOT_FOUND")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            logger.warning(
                "tool not found",
                extra={"tool_name": tool_name, "error_code": "TOOL_NOT_FOUND"},
            )
            return result

        gate = self._tool_allowed(tool_name, context)
        if not gate.allowed:
            if gate.ask_user:
                if self._is_command_auto_allowed(tool_name, tool_input):
                    logger.info(
                        "command auto-allowed, skipping permission",
                        extra={"tool_name": tool_name},
                    )
                    return self._run_tool(tool, tool_name, tool_input, context, t0)
                result = ToolResult(
                    ok=False,
                    content=gate.reason,
                    error_code=PERMISSION_REQUIRED,
                )
                result.meta["tool_name"] = tool_name
                result.meta["tool_input"] = tool_input
                logger.info(
                    "tool requires user permission",
                    extra={"tool_name": tool_name, "reason": gate.reason},
                )
            else:
                result = ToolResult(ok=False, content=gate.reason, error_code="PERMISSION_DENIED")
                self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
                logger.warning(
                    "tool permission denied",
                    extra={"tool_name": tool_name, "error_code": "PERMISSION_DENIED", "reason": gate.reason},
                )
            return result

        return self._run_tool(tool, tool_name, tool_input, context, t0)

    def execute_approved(
        self, tool_name: str, tool_input: Dict[str, Any], context: ToolContext
    ) -> ToolResult:
        t0 = time.time()
        self._emit(context, "tool.start", {"tool": tool_name, "input": tool_input, "approved": True})

        try:
            tool = self.registry.get(tool_name)
        except KeyError as e:
            result = ToolResult(ok=False, content=str(e), error_code="TOOL_NOT_FOUND")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            return result

        try:
            result = tool.run(tool_input, context)
        except Exception as e:
            result = ToolResult(ok=False, content=f"{type(e).__name__}: {e}", error_code="TOOL_RUNTIME_ERROR")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            logger.exception(
                "tool runtime error",
                extra={"tool_name": tool_name, "error_code": "TOOL_RUNTIME_ERROR"},
            )
            return result

        elapsed_ms = int((time.time() - t0) * 1000)
        result.meta["elapsed_ms"] = elapsed_ms
        self._emit(context, "tool.complete", {"tool": tool_name, "ok": result.ok, "meta": result.meta})
        logger.info(
            "tool executed",
            extra={
                "tool_name": tool_name,
                "ok": result.ok,
                "error_code": result.error_code or "",
                "elapsed_ms": elapsed_ms,
            },
        )
        return result

    def _run_tool(
        self,
        tool: Tool,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: ToolContext,
        t0: float,
    ) -> ToolResult:
        perm = tool.requires_permission(tool_input, context)
        if not perm.allowed:
            result = ToolResult(ok=False, content=perm.reason, error_code="PERMISSION_DENIED")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            logger.warning(
                "tool input permission denied",
                extra={"tool_name": tool_name, "error_code": "PERMISSION_DENIED", "reason": perm.reason},
            )
            return result

        try:
            result = tool.run(tool_input, context)
        except Exception as e:
            result = ToolResult(ok=False, content=f"{type(e).__name__}: {e}", error_code="TOOL_RUNTIME_ERROR")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            logger.exception(
                "tool runtime error",
                extra={"tool_name": tool_name, "error_code": "TOOL_RUNTIME_ERROR"},
            )
            return result

        elapsed_ms = int((time.time() - t0) * 1000)
        result.meta["elapsed_ms"] = elapsed_ms
        self._emit(context, "tool.complete", {"tool": tool_name, "ok": result.ok, "meta": result.meta})
        logger.info(
            "tool executed",
            extra={
                "tool_name": tool_name,
                "ok": result.ok,
                "error_code": result.error_code or "",
                "elapsed_ms": elapsed_ms,
            },
        )
        return result


def normalize_path(path_str: str, workspace_root: Path) -> Path:
    p = (workspace_root / path_str).resolve() if not Path(path_str).is_absolute() else Path(path_str).resolve()
    ws = workspace_root.resolve()
    if p != ws and ws not in p.parents:
        raise PermissionError(f"path escapes workspace: {p}")
    return p


def path_allowed(path: Path, roots: List[Path]) -> bool:
    rp = path.resolve()
    for root in roots:
        rr = root.resolve()
        if rp == rr or rr in rp.parents:
            return True
    return False
