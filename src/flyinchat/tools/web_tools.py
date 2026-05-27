from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from flyinchat.tools.core import (
    PermissionDecision,
    ToolContext,
    ToolResult,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "iframe"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "iframe"):
            self._skip = False
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"):
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._text.append(text)

    def get_text(self) -> str:
        return "\n".join(self._text)


def _extract_text_from_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = parser.get_text()
    # compress excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > 50_000:
        text = text[:50_000] + "\n\n... [content truncated]"
    return text


def _check_domain(url_str: str, context: ToolContext) -> PermissionDecision:
    allowed = context.feature_flags.get("web_allowed_domains", "")
    denied = context.feature_flags.get("web_denied_domains", "")

    try:
        hostname = urlparse(url_str).hostname or ""
    except Exception:
        return PermissionDecision(False, f"invalid URL: {url_str}")

    if denied:
        for d in denied.split(","):
            d = d.strip()
            if d and (hostname == d or hostname.endswith("." + d)):
                return PermissionDecision(False, f"domain denied: {hostname} (matches {d})")

    if allowed:
        for d in allowed.split(","):
            d = d.strip()
            if d and (hostname == d or hostname.endswith("." + d)):
                return PermissionDecision(True, "")
        return PermissionDecision(False, f"domain not in allowlist: {hostname}")

    return PermissionDecision(True)


class WebFetchTool:
    name = "web_fetch"
    description = "Fetch a URL and extract its text content. Use to read documentation or web pages."
    version = "1.0.0"
    risk_level = "medium"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to fetch",
                },
                "prompt": {
                    "type": "string",
                    "description": "What information to extract from the page",
                },
            },
            "required": ["url"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        url_str = tool_input.get("url", "")
        if not url_str:
            return PermissionDecision(False, "URL is required")
        return _check_domain(url_str, context)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        url_str = tool_input["url"].strip()
        prompt = tool_input.get("prompt", "").strip()

        if not url_str.startswith(("http://", "https://")):
            url_str = "https://" + url_str

        try:
            result = urlparse(url_str)
            if not result.scheme or not result.netloc:
                return ToolResult(ok=False, content=f"invalid URL: {url_str}", error_code="INVALID_INPUT")
        except Exception:
            return ToolResult(ok=False, content=f"invalid URL: {url_str}", error_code="INVALID_INPUT")

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, max_redirects=5) as client:
                response = await client.get(
                    url_str,
                    headers={"User-Agent": "FlyinChat/1.0"},
                )
                response.raise_for_status()
                html = response.text
        except httpx.TimeoutException:
            return ToolResult(ok=False, content=f"timeout fetching {url_str}", error_code="TIMEOUT")
        except httpx.HTTPStatusError as e:
            return ToolResult(
                ok=False,
                content=f"HTTP {e.response.status_code} fetching {url_str}",
                error_code="HTTP_ERROR",
            )
        except Exception as e:
            return ToolResult(ok=False, content=f"failed to fetch {url_str}: {e}", error_code="NETWORK_ERROR")

        text = _extract_text_from_html(html)

        if prompt:
            content = f"Extract info about: {prompt}\n\n--- Page content ---\n{text}"
        else:
            content = text

        return ToolResult(
            ok=True,
            content=content,
            data={"url": url_str, "content_length": len(text)},
        )


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the web for information. Currently requires configuration of a search provider. "
        "When no provider is configured, use web_fetch on specific URLs instead."
    )
    version = "1.0.0"
    risk_level = "high"

    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only include results from these domains",
                },
                "blocked_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
            },
            "required": ["query"],
        }

    def requires_permission(self, tool_input: Dict[str, Any], context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True)

    async def run(self, tool_input: Dict[str, Any], context: ToolContext) -> ToolResult:
        query = tool_input.get("query", "").strip()
        if not query:
            return ToolResult(ok=False, content="search query is required", error_code="INVALID_INPUT")

        return ToolResult(
            ok=False,
            content=(
                f"Web search is not configured. To search for '{query}', you can:\n"
                "1. Use web_fetch to read specific documentation pages directly\n"
                "2. Configure a search provider in settings (future feature)"
            ),
            error_code="NOT_CONFIGURED",
        )
