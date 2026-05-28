from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import RuntimeGuard


@dataclass(frozen=True)
class GuardOutcome:
    allowed: bool
    reason: str = ""
    ask_user: bool = False
    guard: RuntimeGuard | None = None


def evaluate_skill_guards(
    guards: tuple[RuntimeGuard, ...],
    tool_name: str,
    tool_input: dict[str, Any],
    context: Any,
) -> GuardOutcome:
    for guard in guards:
        matched = _guard_matches(guard, tool_name, tool_input, context)
        if not matched:
            continue
        if guard.action == "ask":
            return GuardOutcome(False, guard.reason, ask_user=True, guard=guard)
        return GuardOutcome(False, guard.reason, guard=guard)
    return GuardOutcome(True)


def guards_from_turn_state(turn_state: dict[str, Any]) -> tuple[RuntimeGuard, ...]:
    raw_guards = turn_state.get("runtime_guards")
    if not isinstance(raw_guards, tuple):
        return ()
    return tuple(guard for guard in raw_guards if isinstance(guard, RuntimeGuard))


def _guard_matches(
    guard: RuntimeGuard,
    tool_name: str,
    tool_input: dict[str, Any],
    context: Any,
) -> bool:
    match guard.guard_type:
        case "deny_tool" | "ask_tool":
            return tool_name in _values(guard.parameters, "tool", "tools")
        case "deny_command_pattern":
            if tool_name != "bash":
                return False
            command = str(tool_input.get("command", ""))
            return any(_pattern_matches(pattern, command) for pattern in _values(guard.parameters, "pattern", "patterns", "commands"))
        case "require_read_before_write":
            if tool_name not in {"file_write", "file_edit"}:
                return False
            path_value = tool_input.get("file_path") or tool_input.get("path")
            if not path_value:
                return False
            try:
                path = _resolve_path(str(path_value), context.workspace_root)
            except Exception:
                return True
            return str(path) not in getattr(context, "recently_read_files", {})
        case "path_scope":
            path_value = tool_input.get("file_path") or tool_input.get("path")
            if not path_value:
                return False
            try:
                path = _resolve_path(str(path_value), context.workspace_root)
            except Exception:
                return True
            scopes = _values(guard.parameters, "path", "paths", "roots")
            if not scopes:
                return False
            allowed_roots = [_resolve_path(scope, context.workspace_root) for scope in scopes]
            return not any(path == root or root in path.parents for root in allowed_roots)
        case _:
            return False


def _values(parameters: dict[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = parameters.get(key)
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            return tuple(str(item) for item in value)
    return ()


def _pattern_matches(pattern: str, text: str) -> bool:
    try:
        if re.search(pattern, text):
            return True
    except re.error:
        pass
    return pattern in text


def _resolve_path(path_value: str, workspace_root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()
