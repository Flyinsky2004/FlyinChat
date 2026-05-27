from __future__ import annotations

from typing import Any, Dict

from flyinchat.tools.core import (
    PermissionDecision,
    ToolContext,
    ToolResult,
)


class TodoWriteTool:
    name = "todo_write"
    description = "Create and track a structured task list for the current coding session"
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task status",
                            },
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        todos = tool_input.get("todos", [])

        completed = 0
        in_progress = 0
        pending = 0
        lines: list[str] = []
        for i, t in enumerate(todos):
            status = t.get("status", "pending")
            content = t.get("content", "")
            marker = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(status, "[?]")
            lines.append(f"{i + 1}. {marker} {content}")
            if status == "completed":
                completed += 1
            elif status == "in_progress":
                in_progress += 1
            else:
                pending += 1

        context.turn_state["todos"] = todos

        summary_parts = []
        if completed:
            summary_parts.append(f"{completed} done")
        if in_progress:
            summary_parts.append(f"{in_progress} in progress")
        if pending:
            summary_parts.append(f"{pending} pending")
        summary = ", ".join(summary_parts) if summary_parts else "empty"

        content = "\n".join(lines) if lines else "(empty list)"
        content += f"\n\n--- {summary} ---"

        return ToolResult(
            ok=True,
            content=content,
            data={"tasks_total": len(todos), "completed": completed, "in_progress": in_progress, "pending": pending},
        )


class EnterPlanModeTool:
    name = "enter_plan_mode"
    description = "Enter plan mode to explore and design before making changes. Plan mode restricts write operations."
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_context": {
                    "type": "string",
                    "description": "Optional description of what you plan to design or implement",
                },
            },
            "required": [],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        plan_context = tool_input.get("plan_context", "").strip()
        context.turn_state["plan_mode"] = True
        if plan_context:
            context.turn_state["plan_context"] = plan_context

        if context.emit_event:
            context.emit_event("mode.change", {"mode": "plan"})

        content = "Entered plan mode. Write operations are now restricted. Explore the codebase and design your approach."
        if plan_context:
            content += f"\n\nPlan context: {plan_context}"

        return ToolResult(
            ok=True,
            content=content,
            data={"mode": "plan"},
        )


class ExitPlanModeTool:
    name = "exit_plan_mode"
    description = "Exit plan mode and submit your plan for user approval before implementation"
    version = "1.0.0"
    risk_level = "medium"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_content": {
                    "type": "string",
                    "description": "The plan content to present for approval",
                },
            },
            "required": ["plan_content"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        plan_content = tool_input.get("plan_content", "").strip()
        context.turn_state["plan_mode"] = False
        context.turn_state["plan_output"] = plan_content

        if context.emit_event:
            context.emit_event("mode.change", {"mode": "normal"})

        return ToolResult(
            ok=True,
            content=f"Plan submitted:\n\n{plan_content}\n\nRestored normal mode.",
            data={"mode": "normal"},
        )
