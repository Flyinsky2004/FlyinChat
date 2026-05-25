from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from flyinchat.tools.core import (
    PermissionDecision,
    ToolContext,
    ToolResult,
    normalize_path,
    path_allowed,
)


class FileReadTool:
    name = "file_read"
    description = "Read UTF-8 text file with line range"
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path under workspace root"},
                "offset": {"type": "integer", "minimum": 1, "default": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
            },
            "required": ["path"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        try:
            p = normalize_path(tool_input["path"], context.workspace_root)
        except Exception as e:
            return PermissionDecision(False, str(e))

        roots = context.permission.allowed_read_roots or [context.workspace_root]
        if not path_allowed(p, roots):
            return PermissionDecision(False, f"read not allowed: {p}")
        return PermissionDecision(True)

    def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        p = normalize_path(tool_input["path"], context.workspace_root)
        offset = int(tool_input.get("offset", 1))
        limit = int(tool_input.get("limit", 200))
        if offset < 1:
            offset = 1
        if limit < 1:
            limit = 1
        if limit > 2000:
            limit = 2000

        if not p.exists() or not p.is_file():
            return ToolResult(ok=False, content=f"file not found: {p}", error_code="FILE_NOT_FOUND")

        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        total = len(lines)
        start = offset - 1
        end = min(start + limit, total)
        picked = lines[start:end]
        numbered = "\n".join(f"{i+1}|{line}" for i, line in enumerate(picked, start=start))

        return ToolResult(
            ok=True,
            content=numbered,
            data={"path": str(p), "offset": offset, "limit": limit, "returned_lines": len(picked), "total_lines": total},
        )


class FileWriteTool:
    name = "file_write"
    description = "Write UTF-8 text file (overwrite by default)"
    version = "1.0.0"
    risk_level = "medium"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path under workspace root"},
                "content": {"type": "string", "description": "Full file content"},
                "create_dirs": {"type": "boolean", "default": True},
                "overwrite": {"type": "boolean", "default": True},
            },
            "required": ["path", "content"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        try:
            p = normalize_path(tool_input["path"], context.workspace_root)
        except Exception as e:
            return PermissionDecision(False, str(e))

        roots = context.permission.allowed_write_roots or [context.workspace_root]
        if not path_allowed(p, roots):
            return PermissionDecision(False, f"write not allowed: {p}")
        return PermissionDecision(True)

    def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        p = normalize_path(tool_input["path"], context.workspace_root)
        content = str(tool_input["content"])
        create_dirs = bool(tool_input.get("create_dirs", True))
        overwrite = bool(tool_input.get("overwrite", True))

        if p.exists() and not overwrite:
            return ToolResult(ok=False, content=f"file exists and overwrite=false: {p}", error_code="FILE_EXISTS")

        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)

        p.write_text(content, encoding="utf-8")

        return ToolResult(
            ok=True,
            content=f"wrote file: {p}",
            data={"path": str(p), "bytes_written": len(content.encode("utf-8"))},
        )
