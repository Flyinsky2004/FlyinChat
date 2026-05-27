import json
from pathlib import Path

from .models import Message

_MAX_RESULT_CHARS = 8000


def sanitize_api_messages(messages: list[dict]) -> list[dict]:
    """Insert placeholder assistant messages between consecutive user messages.

    This recovers from crashes or cancellations that leave orphaned user
    messages in the database, ensuring valid role alternation for the API.
    """
    if not messages:
        return messages
    cleaned: list[dict] = []
    for msg in messages:
        if cleaned and msg.get("role") == "user" and cleaned[-1].get("role") == "user":
            cleaned.append({"role": "assistant", "content": "[Interrupted]"})
        cleaned.append(msg)
    return cleaned


def message_to_api_format(msg: Message) -> dict | None:
    if msg.subtype == "permission_event":
        return None
    try:
        parsed = json.loads(msg.content)
        if isinstance(parsed, list):
            return {"role": msg.role, "content": parsed}
        if isinstance(parsed, dict):
            if "tool_use_id" in parsed:
                return {
                    "role": "tool",
                    "tool_use_id": parsed["tool_use_id"],
                    "content": parsed["content"],
                }
            if parsed.get("type") == "compact_boundary":
                return None
            if parsed.get("type") == "compact_summary":
                return {"role": "system", "content": parsed.get("summary", "")}
    except (json.JSONDecodeError, TypeError):
        pass
    return {"role": msg.role, "content": msg.content}


def message_to_display(msg: Message) -> str:
    try:
        parsed = json.loads(msg.content)
        if isinstance(parsed, list):
            return _format_assistant_blocks(parsed)
        if isinstance(parsed, dict):
            if "event" in parsed:
                return _format_permission_event(parsed)
            if parsed.get("type") == "compact_boundary":
                return _format_compact_boundary(parsed)
            if parsed.get("type") == "compact_summary":
                return _format_compact_summary(parsed)
            if "tool_use_id" in parsed:
                return _format_tool_result(msg, parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    return msg.content


def _parse_meta(msg: Message) -> dict:
    try:
        return json.loads(msg.meta)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_assistant_blocks(blocks: list[dict]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block["type"] == "thinking":
            think_text = block.get("thinking", "")
            preview = (
                think_text[:200] + "..."
                if len(think_text) > 200
                else think_text
            )
            parts.append(f"\n\n💭 **thinking**\n```\n{preview}\n```\n")
        elif block["type"] == "text":
            parts.append(block["text"])
        elif block["type"] == "tool_use":
            parts.append(_format_tool_use_block(block))
    return "".join(parts)


def _format_compact_boundary(parsed: dict) -> str:
    before_k = parsed.get("tokens_before", 0) // 1000
    after_k = parsed.get("tokens_after", 0) // 1000
    strategy = parsed.get("strategy", "")
    return (
        f"\n\n---\n\n📦 **Conversation Compacted** ({strategy})\n"
        f"{before_k}K → {after_k}K tokens\n"
    )


def _format_compact_summary(parsed: dict) -> str:
    return (
        f"\n\n📋 **Summary of earlier conversation:**\n\n"
        f"{parsed.get('summary', '')}\n"
    )


def _format_tool_result(msg: Message, parsed: dict) -> str:
    content = parsed.get("content", "")
    meta = _parse_meta(msg)

    tool_name = meta.get("tool_name", "")
    ok = meta.get("ok", True)
    error_code = meta.get("error_code")
    elapsed_ms = meta.get("elapsed_ms", 0)

    status_icon = "✅" if ok else "❌"
    status_line = f"{status_icon} **{tool_name}**"
    if elapsed_ms:
        status_line += f" _({elapsed_ms}ms)_"
    if not ok and error_code:
        status_line += f" — `{error_code}`"

    parts: list[str] = [f"\n\n{status_line}\n"]
    if tool_name == "file_read" and ok:
        parts.append(_format_file_read_result(meta))
    elif tool_name == "web_fetch" and ok:
        parts.append(_format_web_fetch_result(meta, content))
    elif tool_name == "grep" and ok:
        parts.append(_format_grep_result(meta, content))
    elif tool_name == "glob" and ok:
        parts.append(_format_glob_result(meta, content))
    elif tool_name == "file_edit" and ok:
        parts.append(_format_file_edit_result(meta))
    else:
        parts.append(_format_result_content(content))
    return "".join(parts)


def _format_file_read_result(meta: dict) -> str:
    data = meta.get("data")
    if not isinstance(data, dict):
        data = {}

    path = str(data.get("path") or "")
    filename = Path(path).name if path else "file"
    lines: list[str] = [f"File: **{filename}**"]
    if path:
        lines.append(f"`{path}`")

    returned_lines = data.get("returned_lines")
    total_lines = data.get("total_lines")
    offset = data.get("offset")
    if isinstance(offset, int) and isinstance(returned_lines, int) and isinstance(total_lines, int):
        end_line = max(offset, offset + returned_lines - 1)
        lines.append(f"Lines {offset}-{end_line} of {total_lines}")

    return "\n".join(lines)


def _format_web_fetch_result(meta: dict, content: str) -> str:
    data = meta.get("data")
    if not isinstance(data, dict):
        data = {}
    url = data.get("url", "unknown URL")
    content_length = data.get("content_length", len(content))
    preview = content[:300] + ("..." if len(content) > 300 else "")
    return f"Fetched: `{url}`\nSize: {content_length:,} chars\n\nContent is available in conversation context.\n```\n{preview}\n```"


def _format_grep_result(meta: dict, content: str) -> str:
    data = meta.get("data")
    if not isinstance(data, dict):
        data = {}
    matches = data.get("matches", 0)
    files = data.get("files", 0)
    lines = content.splitlines()
    preview_lines = [l for l in lines if l.strip() and not l.startswith("---")][:6]
    preview = "\n".join(preview_lines)
    summary = f"{matches} matches across {files} files\n\n```\n{preview}\n```"
    if len(preview_lines) < matches:
        summary += "\n... (results in context)"
    return summary


def _format_glob_result(meta: dict, content: str) -> str:
    data = meta.get("data")
    if not isinstance(data, dict):
        data = {}
    matches = data.get("matches", 0)
    lines = content.splitlines()
    preview_lines = [l for l in lines if l.strip()][:8]
    preview = "\n".join(preview_lines)
    summary = f"{matches} files\n\n```\n{preview}\n```"
    if len(preview_lines) < matches:
        summary += "\n... (results in context)"
    return summary


def _format_file_edit_result(meta: dict) -> str:
    data = meta.get("data")
    if not isinstance(data, dict):
        data = {}
    path = str(data.get("path") or "")
    changes = data.get("changes", 0)
    if changes:
        return f"`{path}` — {changes} replacement(s)"
    return f"`{path}` — no changes"


def _format_result_content(content: str) -> str:
    if not content.strip():
        return "```\n(empty)\n```"

    if len(content) > _MAX_RESULT_CHARS:
        content = content[:_MAX_RESULT_CHARS] + "\n... [truncated]"

    try:
        structured = json.loads(content)
        lang = "json"
        formatted = json.dumps(structured, indent=2)
    except (json.JSONDecodeError, TypeError):
        lang = ""
        formatted = content

    return f"```{lang}\n{formatted}\n```"


def _format_tool_use_block(block: dict) -> str:
    name = block.get("name", "unknown")
    tool_input = block.get("input", {})
    lines: list[str] = [f"\n\n🔧 **{name}**"]
    lines.append(_format_tool_use_input(tool_input))
    return "\n".join(lines)


def _format_tool_use_input(tool_input: dict) -> str:
    lines: list[str] = []
    for key, value in tool_input.items():
        if isinstance(value, str):
            if len(value) <= 120 and "\n" not in value:
                lines.append(f"- **{key}**: `{value}`")
            else:
                preview = value[:500] + ("..." if len(value) > 500 else "")
                lines.append(f"- **{key}**:\n```\n{preview}\n```")
        elif isinstance(value, bool):
            lines.append(f"- **{key}**: `{'true' if value else 'false'}`")
        elif isinstance(value, (int, float)):
            lines.append(f"- **{key}**: `{value}`")
        elif value is None:
            lines.append(f"- **{key}**: `null`")
        else:
            lines.append(f"- **{key}**: `{json.dumps(value)}`")
    return "\n".join(lines)


def _format_permission_event(parsed: dict) -> str:
    event_type = parsed.get("event", "")
    tool_name = parsed.get("tool_name", "")
    risk = parsed.get("risk_level", "")

    if event_type == "permission_request_created":
        risk_badge = f" [{risk}]" if risk else ""
        return f"\n\n🔐 **{tool_name}** — permission required{risk_badge}"
    elif event_type == "permission_request_resolved":
        resolution = parsed.get("resolution", "")
        if resolution == "approved":
            return f"\n\n✅ **{tool_name}** — permission approved"
        elif resolution == "denied":
            return f"\n\n❌ **{tool_name}** — permission denied"
        elif resolution == "timeout":
            return f"\n\n⏰ **{tool_name}** — permission timed out"
        return f"\n\n🔐 **{tool_name}** — permission {resolution}"
    elif event_type == "permission_effect_applied":
        outcome = parsed.get("outcome", "")
        if outcome == "executed":
            return ""  # tool result message follows immediately, no need for extra line
        return f"\n\n⚠️ **{tool_name}** — execution failed"
    return ""

