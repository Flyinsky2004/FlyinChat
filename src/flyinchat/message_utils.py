import json

from .models import Message


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
            parts: list[str] = []
            for block in parsed:
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
                    parts.append(
                        f"\n\n🔧 **{block['name']}**\n```json\n"
                        f"{json.dumps(block['input'], indent=2)}\n```\n"
                    )
            return "".join(parts)
        if isinstance(parsed, dict):
            if parsed.get("type") == "compact_boundary":
                before_k = parsed.get("tokens_before", 0) // 1000
                after_k = parsed.get("tokens_after", 0) // 1000
                strategy = parsed.get("strategy", "")
                return (
                    f"\n\n---\n\n📦 **Conversation Compacted** ({strategy})\n"
                    f"{before_k}K → {after_k}K tokens\n"
                )
            if parsed.get("type") == "compact_summary":
                return (
                    f"\n\n📋 **Summary of earlier conversation:**\n\n"
                    f"{parsed.get('summary', '')}\n"
                )
            if "tool_use_id" in parsed:
                return f"```\n{parsed['content']}\n```"
    except (json.JSONDecodeError, TypeError):
        pass
    return msg.content
