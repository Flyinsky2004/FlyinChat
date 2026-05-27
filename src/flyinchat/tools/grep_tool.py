from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from flyinchat.tools.core import (
    PermissionDecision,
    ToolContext,
    ToolResult,
    normalize_path,
    path_allowed,
)

_TEXT_EXTS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh",
    ".rb", ".php", ".cs", ".scala", ".clj", ".cljs", ".ex", ".exs",
    ".html", ".css", ".scss", ".less", ".svg", ".xml", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".rst", ".tex",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".sql", ".graphql",
    ".Makefile", ".Dockerfile", ".env",
    ".conf", ".lock",
}


def _is_searchable_file(path: Path) -> bool:
    """Check if file is likely a readable text file."""
    if path.suffix in _TEXT_EXTS:
        return True
    if path.name in (".gitignore", "Makefile", "Dockerfile", "LICENSE"):
        return True
    # bail out for very large files
    try:
        if path.stat().st_size > 2_000_000:
            return False
    except OSError:
        return False
    # try reading first few bytes as utf-8
    try:
        with open(path, "rb") as f:
            sample = f.read(256)
        sample.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


class GrepTool:
    name = "grep"
    description = "Search file contents for a regex pattern using ripgrep with Python fallback"
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": "Search directory, relative to workspace root",
                },
                "include": {
                    "type": "string",
                    "description": "Glob filter for filenames, e.g. '*.py'",
                },
                "ignore_case": {
                    "type": "boolean",
                    "default": False,
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                },
            },
            "required": ["pattern"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        try:
            search_path = normalize_path(tool_input.get("path", "."), context.workspace_root)
        except Exception as e:
            return PermissionDecision(False, str(e))

        roots = context.permission.allowed_read_roots or [context.workspace_root]
        if not path_allowed(search_path, roots):
            return PermissionDecision(False, f"read not allowed: {search_path}")
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = tool_input["pattern"]
        search_path = normalize_path(tool_input.get("path", "."), context.workspace_root)
        include = tool_input.get("include", "")
        ignore_case = bool(tool_input.get("ignore_case", False))
        max_results = int(tool_input.get("max_results", 100))

        if not search_path.exists():
            return ToolResult(ok=False, content=f"path not found: {search_path}", error_code="FILE_NOT_FOUND")

        if shutil.which("rg"):
            return self._rg_search(pattern, search_path, include, ignore_case, max_results, context)
        return self._py_search(pattern, search_path, include, ignore_case, max_results, context)

    def _rg_search(
        self, pattern: str, search_path: Path, include: str,
        ignore_case: bool, max_results: int, context: ToolContext,
    ) -> ToolResult:
        base_cmd = [
            "rg", "--json", "--line-number", "--no-heading",
            "--max-count", str(max_results),
        ]
        if ignore_case:
            base_cmd.append("-i")
        if include:
            base_cmd.extend(["--glob", include])
        base_cmd.extend(["--", pattern, str(search_path)])

        try:
            proc = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                cwd=str(context.workspace_root),
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, content="grep timed out after 30s", error_code="TIMEOUT")

        if proc.returncode > 1:
            return ToolResult(ok=False, content=f"rg error: {proc.stderr.strip()}", error_code="TOOL_RUNTIME_ERROR")

        lines_out: list[str] = []
        files_seen: set[str] = set()
        count = 0
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "match":
                data = entry.get("data", {})
                path_text = data.get("path", {}).get("text", "")
                line_num = data.get("line_number", 0)
                match_text = data.get("lines", {}).get("text", "").rstrip("\n")
                if path_text:
                    try:
                        rel_path = str(Path(path_text).relative_to(context.workspace_root))
                    except ValueError:
                        rel_path = path_text
                    files_seen.add(rel_path)
                    lines_out.append(f"{rel_path}:{line_num}: {match_text}")
                    count += 1
                    if count >= max_results:
                        break

        return self._format_output(lines_out, files_seen, count, max_results)

    def _py_search(
        self, pattern: str, search_path: Path, include: str,
        ignore_case: bool, max_results: int, context: ToolContext,
    ) -> ToolResult:
        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(ok=False, content=f"invalid regex: {e}", error_code="INVALID_INPUT")

        lines_out: list[str] = []
        files_seen: set[str] = set()
        count = 0

        if include:
            candidates = sorted(search_path.rglob(include))
        else:
            candidates = sorted(search_path.rglob("*"))

        for file_path in candidates:
            if count >= max_results:
                break
            if not file_path.is_file():
                continue
            if not _is_searchable_file(file_path):
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for i, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    try:
                        rel_path = str(file_path.relative_to(context.workspace_root))
                    except ValueError:
                        rel_path = str(file_path)
                    files_seen.add(rel_path)
                    lines_out.append(f"{rel_path}:{i}: {line}")
                    count += 1
                    if count >= max_results:
                        break

        return self._format_output(lines_out, files_seen, count, max_results)

    @staticmethod
    def _format_output(
        lines_out: list[str], files_seen: set[str], count: int, max_results: int,
    ) -> ToolResult:
        if not lines_out:
            return ToolResult(
                ok=True,
                content="No matches found",
                data={"matches": 0, "files": 0},
            )

        suffix = f"\n... truncated, showing {count} of {count}+ results" if count >= max_results else ""
        content = "\n".join(lines_out) + suffix
        summary = f"\n---\n{len(lines_out)} matches across {len(files_seen)} files"
        content += summary

        return ToolResult(
            ok=True,
            content=content,
            data={"matches": count, "files": len(files_seen)},
        )
