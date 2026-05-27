from __future__ import annotations

from typing import Any, Dict

from flyinchat.tools.core import (
    USER_INPUT_REQUIRED,
    PermissionDecision,
    ToolContext,
    ToolResult,
)


class AskUserQuestionTool:
    name = "ask_user_question"
    description = (
        "Ask the user structured questions to clarify requirements, "
        "resolve ambiguity, or make decisions. Use when you need the user "
        "to choose between options or confirm a direction."
    )
    version = "1.0.0"
    risk_level = "low"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The complete question to ask",
                            },
                            "header": {
                                "type": "string",
                                "description": "Short label (max 12 chars) shown as a chip",
                            },
                            "options": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "Display text for the option",
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Explanation of what this choice means",
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                            },
                            "multiSelect": {
                                "type": "boolean",
                                "default": False,
                            },
                        },
                        "required": ["question", "header", "options"],
                    },
                },
            },
            "required": ["questions"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        questions = tool_input["questions"]
        return ToolResult(
            ok=True,
            content="",
            error_code=USER_INPUT_REQUIRED,
            meta={"questions": questions},
        )
