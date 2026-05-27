import asyncio
from pathlib import Path

import pytest

from flyinchat.tools.web_tools import WebFetchTool, WebSearchTool
from flyinchat.tools.core import (
    PermissionContext,
    ToolContext,
)


def _make_context(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="test",
        user_id="test-user",
        workspace_root=workspace,
        permission=PermissionContext(allowed_tools={"web_fetch", "web_search"}),
    )


class TestWebFetchTool:
    def test_invalid_url_short(self, tmp_path: Path) -> None:
        tool = WebFetchTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"url": "not-a-url"}, ctx))
        assert result.ok is False
        assert result.error_code in ("INVALID_INPUT", "NETWORK_ERROR")

    def test_empty_url_rejected(self, tmp_path: Path) -> None:
        tool = WebFetchTool()
        ctx = _make_context(tmp_path)
        decision = tool.requires_permission({"url": ""}, ctx)
        assert decision.allowed is False

    def test_domain_denied(self, tmp_path: Path) -> None:
        tool = WebFetchTool()
        ctx = _make_context(tmp_path)
        ctx.feature_flags["web_denied_domains"] = "evil.com"
        decision = tool.requires_permission({"url": "https://evil.com/page"}, ctx)
        assert decision.allowed is False


class TestWebSearchTool:
    def test_not_configured(self, tmp_path: Path) -> None:
        tool = WebSearchTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"query": "python asyncio"}, ctx))
        assert result.ok is False
        assert result.error_code == "NOT_CONFIGURED"

    def test_empty_query_rejected(self, tmp_path: Path) -> None:
        tool = WebSearchTool()
        ctx = _make_context(tmp_path)
        result = asyncio.run(tool.run({"query": ""}, ctx))
        assert result.ok is False
        assert result.error_code == "INVALID_INPUT"
