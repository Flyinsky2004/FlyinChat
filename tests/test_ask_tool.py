import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.ask_tool import AskUserQuestionTool
from flyinchat.tools.core import (
    USER_INPUT_REQUIRED,
    PermissionContext,
    ToolContext,
)


def _make_context(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="test",
        user_id="test-user",
        workspace_root=workspace,
        permission=PermissionContext(allowed_tools={"ask_user_question"}),
    )


class TestAskUserQuestionTool:
    def test_returns_user_input_required(self, tmp_path: Path) -> None:
        tool = AskUserQuestionTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({
            "questions": [
                {
                    "question": "Which approach?",
                    "header": "Approach",
                    "options": [
                        {"label": "A", "description": "Option A"},
                        {"label": "B", "description": "Option B"},
                    ],
                }
            ],
        }, ctx))
        assert result.ok is True
        assert result.error_code == USER_INPUT_REQUIRED
        assert len(result.meta["questions"]) == 1

    def test_always_permitted(self, tmp_path: Path) -> None:
        tool = AskUserQuestionTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission({"questions": []}, ctx)
        assert decision.allowed is True
