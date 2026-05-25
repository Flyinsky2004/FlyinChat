from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol


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


@dataclass
class PermissionContext:
    allowed_tools: Optional[set[str]] = None
    denied_tools: set[str] = field(default_factory=set)
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

    def _emit(self, context: ToolContext, event: str, payload: Dict[str, Any]) -> None:
        if context.emit_event:
            context.emit_event(event, payload)

    def _tool_allowed(self, tool_name: str, context: ToolContext) -> PermissionDecision:
        p = context.permission
        if p.allowed_tools is not None and tool_name not in p.allowed_tools:
            return PermissionDecision(False, f"tool not in allow list: {tool_name}")
        if tool_name in p.denied_tools:
            return PermissionDecision(False, f"tool denied: {tool_name}")
        return PermissionDecision(True, "")

    def execute(self, tool_name: str, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        t0 = time.time()
        self._emit(context, "tool.start", {"tool": tool_name, "input": tool_input})

        try:
            tool = self.registry.get(tool_name)
        except KeyError as e:
            result = ToolResult(ok=False, content=str(e), error_code="TOOL_NOT_FOUND")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            return result

        gate = self._tool_allowed(tool_name, context)
        if not gate.allowed:
            result = ToolResult(ok=False, content=gate.reason, error_code="PERMISSION_DENIED")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            return result

        perm = tool.requires_permission(tool_input, context)
        if not perm.allowed:
            result = ToolResult(ok=False, content=perm.reason, error_code="PERMISSION_DENIED")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            return result

        try:
            result = tool.run(tool_input, context)
        except Exception as e:
            result = ToolResult(ok=False, content=f"{type(e).__name__}: {e}", error_code="TOOL_RUNTIME_ERROR")
            self._emit(context, "tool.error", {"tool": tool_name, "error": result.content})
            return result

        result.meta["elapsed_ms"] = int((time.time() - t0) * 1000)
        self._emit(context, "tool.complete", {"tool": tool_name, "ok": result.ok, "meta": result.meta})
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
