from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flyinchat.storage import get_primary_llm_model
from flyinchat.subagents.definition_loader import SubAgentRegistry
from flyinchat.tools.core import PermissionDecision, ToolContext, ToolExecutor, ToolRegistry, ToolResult


class SubAgentTool:
    name = "sub_agent"
    description = (
        "Delegate a self-contained sub-task to an independent sub-agent with isolated context. "
        "Available agent types include general-purpose, code-reviewer, debugger, and test-runner. "
        "Use this when a sub-task needs extensive searching, independent analysis, test/log investigation, "
        "or a specialized reviewer role. The sub-agent transcript stays isolated; this tool returns only "
        "a structured summary. The task must be complete and must not depend on hidden parent context."
    )
    version = "1.0.0"
    risk_level = "medium"

    def __init__(
        self,
        *,
        config_path: Path,
        chat_path: Path,
        subagent_registry: SubAgentRegistry,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
    ) -> None:
        self.config_path = config_path
        self.chat_path = chat_path
        self.subagent_registry = subagent_registry
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_type": {
                    "type": "string",
                    "description": "Sub-agent type: general-purpose, code-reviewer, debugger, or test-runner.",
                },
                "task": {
                    "type": "string",
                    "description": "Self-contained task for the sub-agent. Do not rely on hidden parent context.",
                },
                "context": {
                    "type": "string",
                    "default": "",
                    "description": "Selected parent context to pass to the sub-agent.",
                },
                "expected_output": {
                    "type": "string",
                    "default": "",
                    "description": "Optional expected output shape or emphasis.",
                },
                "constraints": {
                    "type": "string",
                    "default": "",
                    "description": "Optional constraints such as read-only analysis or specific files to inspect.",
                },
                "allowed_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional workspace-relative paths that limit file reads.",
                },
                "max_turns": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Optional turn limit, capped by the sub-agent definition.",
                },
            },
            "required": ["agent_type", "task"],
        }

    def requires_permission(
        self,
        tool_input: dict[str, Any],
        context: ToolContext,
    ) -> PermissionDecision:
        task = str(tool_input.get("task") or "").strip()
        if not task:
            return PermissionDecision(False, "sub-agent task is required")
        agent_type = str(tool_input.get("agent_type") or "").strip()
        if not agent_type:
            return PermissionDecision(False, "sub-agent type is required")
        return PermissionDecision(True)

    async def run(
        self,
        tool_input: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        agent_type = str(tool_input.get("agent_type") or "").strip()
        definition = self.subagent_registry.get(agent_type)
        if definition is None:
            available = ", ".join(item.name for item in self.subagent_registry.list_definitions())
            return ToolResult(
                ok=False,
                content=f"Unknown sub-agent type: {agent_type}. Available: {available}",
                error_code="SUBAGENT_NOT_FOUND",
            )

        primary = get_primary_llm_model(self.config_path)
        if primary is None:
            return ToolResult(
                ok=False,
                content="No model configured. Add one with /api, then /model.",
                error_code="NO_MODEL",
            )
        channel, model = primary
        parent_conversation_id = str(context.turn_state.get("conversation_id") or context.session_id)
        if parent_conversation_id == "flyinchat":
            return ToolResult(
                ok=False,
                content="Sub-agent parent conversation is not available.",
                error_code="SUBAGENT_NO_PARENT_CONVERSATION",
            )

        expected_output = str(tool_input.get("expected_output") or "").strip()
        constraints = str(tool_input.get("constraints") or "").strip()
        if expected_output:
            constraints = f"{constraints}\nExpected output:\n{expected_output}".strip()
        requested_max_turns = tool_input.get("max_turns")
        max_turns = _bounded_max_turns(requested_max_turns, definition.max_turns)
        allowed_paths = _as_str_list(tool_input.get("allowed_paths"))
        from flyinchat.subagents.executor import SubAgentExecutor

        executor = SubAgentExecutor(
            definition,
            channel,
            model,
            self.tool_registry,
            self.tool_executor,
            context,
            self.chat_path,
            parent_conversation_id,
            emit_event=context.emit_event,
        )
        result = await executor.execute(
            str(tool_input["task"]),
            context=str(tool_input.get("context") or ""),
            constraints=constraints,
            allowed_paths=allowed_paths,
            max_turns=max_turns,
        )
        content = json.dumps(asdict(result), ensure_ascii=False, indent=2)
        return ToolResult(
            ok=result.status in {"success", "partial", "max_turns_exceeded", "max_tokens_exceeded"},
            content=content,
            data={
                "subagent_session_id": result.subagent_session_id,
                "agent_type": definition.name,
                "status": result.status,
            },
            error_code=None if result.status == "success" else "SUBAGENT_PARTIAL",
        )


def _bounded_max_turns(value: Any, definition_max: int) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = definition_max
    return max(1, min(requested, definition_max))


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
