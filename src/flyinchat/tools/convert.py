from __future__ import annotations

from typing import Any

from flyinchat.tools.core import Tool


def to_anthropic_tool(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema(),
    }


def to_openai_tool(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema(),
        },
    }


def tools_to_api_format(tools: list[Tool], provider_type: str) -> list[dict[str, Any]]:
    if provider_type == "anthropic":
        return [to_anthropic_tool(t) for t in tools]
    return [to_openai_tool(t) for t in tools]
