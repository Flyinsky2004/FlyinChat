from __future__ import annotations

import time
from typing import Any, Dict

from flyinchat.tools.core import (
    PermissionDecision,
    ToolContext,
    ToolResult,
    normalize_path,
    path_allowed,
)

_READ_STALE_SECONDS = 300  # 5 minutes


class FileEditTool:
    name = "file_edit"
    description = "Edit a file by replacing a string with a new string. Requires the file to be read first."
    version = "1.0.0"
    risk_level = "medium"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File path under workspace root",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact string to replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement string",
                },
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace all occurrences when True",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        try:
            p = normalize_path(tool_input["file_path"], context.workspace_root)
        except Exception as e:
            return PermissionDecision(False, str(e))

        roots = context.permission.allowed_write_roots or [context.workspace_root]
        if not path_allowed(p, roots):
            return PermissionDecision(False, f"write not allowed: {p}")
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = tool_input["file_path"]
        old_string = tool_input["old_string"]
        new_string = tool_input["new_string"]
        replace_all = bool(tool_input.get("replace_all", False))

        if not old_string:
            return ToolResult(
                ok=False,
                content="old_string must not be empty",
                error_code="INVALID_INPUT",
            )

        p = normalize_path(file_path, context.workspace_root)

        if not p.exists() or not p.is_file():
            return ToolResult(ok=False, content=f"file not found: {p}", error_code="FILE_NOT_FOUND")

        # Read-before-edit check
        normalized = str(p)
        last_read = context.recently_read_files.get(normalized)
        if last_read is None:
            return ToolResult(
                ok=False,
                content=f"File must be read before editing: {p}. Use file_read first.",
                error_code="FILE_NOT_READ",
            )
        if time.time() - last_read > _READ_STALE_SECONDS:
            del context.recently_read_files[normalized]
            return ToolResult(
                ok=False,
                content=f"File read is stale (>5 min ago). Re-read the file before editing: {p}",
                error_code="FILE_NOT_READ",
            )

        try:
            content = p.read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult(ok=False, content=f"failed to read file: {e}", error_code="IO_ERROR")

        occurrences = content.count(old_string)
        if occurrences == 0:
            return ToolResult(
                ok=False,
                content=f"old_string not found in file: {p}",
                error_code="STRING_NOT_FOUND",
            )

        if occurrences > 1 and not replace_all:
            return ToolResult(
                ok=False,
                content=(
                    f"old_string appears {occurrences} times in the file. "
                    f"Set replace_all=True to replace all occurrences, "
                    f"or make the old_string more specific to target a single instance."
                ),
                error_code="AMBIGUOUS_MATCH",
            )

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

        if new_content == content:
            return ToolResult(
                ok=True,
                content=f"No changes made (old_string and new_string are identical): {p}",
                data={"path": str(p), "changes": 0},
            )

        try:
            p.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return ToolResult(ok=False, content=f"failed to write file: {e}", error_code="IO_ERROR")

        changed = 1 if not replace_all else occurrences
        return ToolResult(
            ok=True,
            content=f"Replaced {changed} occurrence(s) in {p}",
            data={"path": str(p), "changes": changed, "bytes_written": len(new_content.encode("utf-8"))},
        )
