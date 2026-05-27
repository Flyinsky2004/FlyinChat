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


class GlobTool:
    name = "glob"
    description = "Find files matching a glob pattern under a directory"
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*_test.py'",
                },
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": "Base directory for the search, relative to workspace root",
                },
            },
            "required": ["pattern"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        try:
            base = normalize_path(tool_input.get("path", "."), context.workspace_root)
        except Exception as e:
            return PermissionDecision(False, str(e))

        roots = context.permission.allowed_read_roots or [context.workspace_root]
        if not path_allowed(base, roots):
            return PermissionDecision(False, f"read not allowed: {base}")
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = tool_input["pattern"]
        base = normalize_path(tool_input.get("path", "."), context.workspace_root)

        if not base.exists():
            return ToolResult(ok=False, content=f"directory not found: {base}", error_code="FILE_NOT_FOUND")
        if not base.is_dir():
            base = base.parent

        try:
            results = sorted(str(p.relative_to(context.workspace_root)) for p in base.glob(pattern))
        except Exception as e:
            return ToolResult(ok=False, content=f"glob error: {e}", error_code="TOOL_RUNTIME_ERROR")

        max_results = 500
        truncated = len(results) > max_results
        if truncated:
            results = results[:max_results]

        if not results:
            return ToolResult(
                ok=True,
                content=f"No files match pattern '{pattern}' in {base.relative_to(context.workspace_root)}",
                data={"matches": 0},
            )

        suffix = f"\n... and {len(results) - max_results} more (truncated)" if truncated else ""
        content = "\n".join(results) + suffix if truncated else "\n".join(results)

        return ToolResult(
            ok=True,
            content=content,
            data={"matches": len(results), "pattern": pattern},
        )
